"""Buchungslogik und Rechte der Strichliste.

Alle Saldo-Änderungen laufen über book(), revert() und transfer(), damit
Account.balance immer der Summe der nicht stornierten Buchungen entspricht.
"""
import os
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Account, Config, DispenseButton, Tablet, Transaction


def admin_usernames() -> set[str]:
    return {name.strip() for name in os.environ.get("STRICHLISTE_ADMINS", "").split(",") if name.strip()}


@dataclass
class Actor:
    """Wer gerade bucht: ein Nextcloud-Benutzer oder ein Theken-Tablet."""
    name: str
    uid: str = ""
    account: Account | None = None
    tablet: Tablet | None = None

    @property
    def is_tablet(self) -> bool:
        return self.tablet is not None

    @property
    def is_admin(self) -> bool:
        return not self.is_tablet and self.uid in admin_usernames()

    def can_book(self, account: Account) -> bool:
        if account.disabled:
            return False
        return (self.is_tablet or self.is_admin or account.is_extern
                or (self.account is not None and account.pk == self.account.pk))

    def can_revert(self, tx: Transaction, config: Config) -> bool:
        if tx.reverted_at is not None or tx.kind == Transaction.KIND_IMPORT:
            return False
        if tx.created_at < timezone.now() - timezone.timedelta(minutes=config.undo_minutes):
            return False
        if self.is_admin:
            return True
        if self.is_tablet:
            return tx.tablet_id == self.tablet.pk
        return tx.tablet_id is None and tx.booked_by_uid == self.uid


def _apply(account_pk: int, amount: int, at) -> None:
    Account.objects.filter(pk=account_pk).update(balance=F("balance") + amount, last_booking_at=at)


def _check_limit(account: Account, amount: int, config: Config) -> None:
    if amount < 0 and account.balance + amount < config.hard_limit:
        raise ValidationError(f"Die Buchung würde das Konto unter {format_cents(config.hard_limit)} bringen. "
                              "Bitte zuerst einzahlen.")


def book(account: Account, amount: int, kind: str, label: str, actor: Actor, *, created_at=None) -> Transaction:
    config = Config.get()
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        if not actor.can_book(account):
            raise PermissionDenied
        _check_limit(account, amount, config)
        tx = Transaction.objects.create(
            account=account, kind=kind, amount=amount, label=label,
            created_at=created_at or timezone.now(),
            booked_by_uid=actor.uid, booked_by_name=actor.name, tablet=actor.tablet,
        )
        _apply(account.pk, amount, tx.created_at)
    return tx


def book_step(account: Account, action: str, value: int, actor: Actor) -> Transaction:
    """Bucht einen Ausgabe-Button (value ist dessen ID) oder eine der Einzahlungsstufen (value in Cent)."""
    if action == "dispense":
        button = DispenseButton.objects.filter(pk=value).first()
        if button is not None:
            return book(account, -button.cents, Transaction.KIND_DISPENSE,
                        f"{button.label} ({format_cents(button.cents)})", actor)
    cents = value
    if action == "deposit" and cents in Config.get().deposit_list:
        return book(account, cents, Transaction.KIND_DEPOSIT, f"Einzahlung bar {format_cents(cents)}", actor)
    raise ValidationError("Dieser Betrag ist nicht vorgesehen.")


def transfer(source: Account, target: Account, amount: int, comment: str, actor: Actor) -> Transaction:
    config = Config.get()
    if not config.transfers_enabled:
        raise PermissionDenied
    if amount <= 0:
        raise ValidationError("Der Betrag muss größer als 0 sein.")
    if source.pk == target.pk:
        raise ValidationError("Überweisungen an das eigene Konto sind nicht möglich.")
    suffix = f" – {comment}" if comment else ""
    with transaction.atomic():
        # feste Reihenfolge beim Sperren vermeidet Deadlocks
        locked = {acc.pk: acc for acc in Account.objects.select_for_update().filter(pk__in=[source.pk, target.pk]).order_by("pk")}
        source, target = locked[source.pk], locked[target.pk]
        if not actor.can_book(source) or target.disabled:
            raise PermissionDenied
        _check_limit(source, -amount, config)
        now = timezone.now()
        common = {"kind": Transaction.KIND_TRANSFER, "created_at": now, "booked_by_uid": actor.uid,
                  "booked_by_name": actor.name, "tablet": actor.tablet}
        outgoing = Transaction.objects.create(account=source, amount=-amount, label=f"Überweisung an {target.name}{suffix}", **common)
        incoming = Transaction.objects.create(account=target, amount=amount, label=f"Überweisung von {source.name}{suffix}", pair=outgoing, **common)
        outgoing.pair = incoming
        outgoing.save(update_fields=["pair"])
        _apply(source.pk, -amount, now)
        _apply(target.pk, amount, now)
    return outgoing


def revert(tx: Transaction, actor: Actor) -> None:
    config = Config.get()
    with transaction.atomic():
        tx = Transaction.objects.select_for_update().get(pk=tx.pk)
        if not actor.can_revert(tx, config):
            raise PermissionDenied
        now = timezone.now()
        for item in filter(None, [tx, tx.pair]):
            if item.reverted_at is None:
                item.reverted_at = now
                item.reverted_by_name = actor.name
                item.save(update_fields=["reverted_at", "reverted_by_name"])
                Account.objects.filter(pk=item.account_id).update(balance=F("balance") - item.amount)


def link_account(account: Account, username: str, name: str | None = None) -> Account:
    """Verknüpft ein externes oder altes Konto mit einem Nextcloud-Benutzer.

    Gibt es für den Benutzer schon ein Konto, wird account dort hinein übernommen
    (Buchungen und Saldo) und anschließend gelöscht."""
    with transaction.atomic():
        existing = Account.objects.select_for_update().filter(username=username).exclude(pk=account.pk).first()
        if existing is None:
            account.kind = Account.KIND_NEXTCLOUD
            account.username = username
            if name:
                account.name = name
            account.contact = None
            account.save()
            account.tags.clear()
            return account

        account.transactions.update(account=existing)
        Account.objects.filter(pk=existing.pk).update(balance=F("balance") + account.balance)
        if account.last_booking_at and (existing.last_booking_at is None or existing.last_booking_at < account.last_booking_at):
            Account.objects.filter(pk=existing.pk).update(last_booking_at=account.last_booking_at)
        if existing.legacy_id is None and account.legacy_id is not None:
            legacy_id = account.legacy_id
            account.delete()
            Account.objects.filter(pk=existing.pk).update(legacy_id=legacy_id)
        else:
            account.delete()
        existing.refresh_from_db()
        return existing


def own_account(uid: str, display_name: str) -> Account:
    """Konto des angemeldeten Nextcloud-Benutzers, wird beim ersten Aufruf angelegt.

    Passt der Name genau zu einem noch nicht verknüpften Konto aus dem alten
    System, wird dieses übernommen."""
    account = Account.objects.filter(username=uid).first()
    if account is not None:
        if account.name != display_name:
            account.name = display_name
            account.save(update_fields=["name"])
        return account

    candidates = list(Account.objects.filter(kind=Account.KIND_LEGACY, name__iexact=display_name)[:2])
    if len(candidates) == 1:
        return link_account(candidates[0], uid, display_name)

    return Account.objects.create(kind=Account.KIND_NEXTCLOUD, username=uid, name=display_name)


def format_cents(cents: int, signed: bool = False) -> str:
    sign = "−" if cents < 0 else ("+" if signed and cents > 0 else "")
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", ".") + f",{rest:02d} €"
