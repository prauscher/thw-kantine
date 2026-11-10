"""Buchungslogik der Strichliste.

Alle Saldo-Änderungen laufen über book(), revert() und transfer(), damit
Account.balance immer der Summe der nicht stornierten Buchungen entspricht.

booked_by enthält booked_by_uid, booked_by_name und via_tablet der Buchung.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import settings as app_settings
from .models import Account, Transaction


def _apply(account_pk: int, amount: int, at) -> None:
    Account.objects.filter(pk=account_pk).update(balance=F("balance") + amount, last_booking_at=at)


def _check(account: Account, amount: int) -> None:
    if account.disabled:
        raise PermissionDenied
    if amount < 0 and account.balance + amount < app_settings.HARD_LIMIT:
        raise ValidationError(f"Die Buchung würde das Konto unter {format_cents(app_settings.HARD_LIMIT)} bringen. "
                              "Bitte zuerst einzahlen.")


def book(account: Account, amount: int, kind: str, label: str, booked_by: dict) -> Transaction:
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        _check(account, amount)
        tx = Transaction.objects.create(account=account, kind=kind, amount=amount, label=label, **booked_by)
        _apply(account.pk, amount, tx.created_at)
    return tx


def transfer(source: Account, target: Account, amount: int, comment: str, booked_by: dict) -> Transaction:
    if source.pk == target.pk:
        raise ValidationError("Überweisungen an das eigene Konto sind nicht möglich.")
    suffix = f" – {comment}" if comment else ""
    with transaction.atomic():
        # feste Reihenfolge beim Sperren vermeidet Deadlocks
        locked = {acc.pk: acc for acc in Account.objects.select_for_update().filter(pk__in=[source.pk, target.pk]).order_by("pk")}
        source, target = locked[source.pk], locked[target.pk]
        if target.disabled:
            raise PermissionDenied
        _check(source, -amount)
        common = {"kind": Transaction.KIND_TRANSFER, "created_at": timezone.now(), **booked_by}
        outgoing = Transaction.objects.create(account=source, amount=-amount, label=f"Überweisung an {target.name}{suffix}", **common)
        incoming = Transaction.objects.create(account=target, amount=amount, label=f"Überweisung von {source.name}{suffix}", pair=outgoing, **common)
        outgoing.pair = incoming
        outgoing.save(update_fields=["pair"])
        _apply(source.pk, -amount, common["created_at"])
        _apply(target.pk, amount, common["created_at"])
    return outgoing


def can_revert(tx: Transaction) -> bool:
    return (tx.reverted_at is None and tx.kind != Transaction.KIND_IMPORT
            and tx.created_at >= timezone.now() - timezone.timedelta(minutes=app_settings.UNDO_MINUTES))


def revert(tx: Transaction, reverted_by_name: str) -> None:
    with transaction.atomic():
        tx = Transaction.objects.select_for_update().get(pk=tx.pk)
        if not can_revert(tx):
            raise PermissionDenied
        now = timezone.now()
        for item in filter(None, [tx, tx.pair]):
            if item.reverted_at is None:
                item.reverted_at = now
                item.reverted_by_name = reverted_by_name
                item.save(update_fields=["reverted_at", "reverted_by_name"])
                Account.objects.filter(pk=item.account_id).update(balance=F("balance") - item.amount)


def format_cents(cents: int, signed: bool = False) -> str:
    sign = "−" if cents < 0 else ("+" if signed and cents > 0 else "")
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", ".") + f",{rest:02d} €"
