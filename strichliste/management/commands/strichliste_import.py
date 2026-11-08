import json
import os
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from strichliste.booking import format_cents
from strichliste.models import Account, Transaction

FETCH_LIMIT = 5000


class Command(BaseCommand):
    help = "Übernimmt die Konten der bisherigen Strichliste (strichliste.org) in die leere Datenbank."

    def add_arguments(self, parser):
        parser.add_argument("--url", default="https://strichliste.thw-darmstadt.de",
                            help="Adresse der alten Strichliste")
        parser.add_argument("--auth", default=os.environ.get("STRICHLISTE_IMPORT_AUTH", ""),
                            help="Zugangsdaten für den Verzeichnisschutz als benutzer:passwort "
                                 "(oder Umgebungsvariable STRICHLISTE_IMPORT_AUTH)")
        parser.add_argument("--file", help="Statt der URL eine gespeicherte Antwort von /api/user lesen")
        parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, was passieren würde")

    def handle(self, *args, url, auth, file, dry_run, **options):
        if Account.objects.exists():
            raise CommandError("Es gibt schon Konten. Der Import geht nur in eine leere Datenbank.")

        users = self._load(url, auth, file)
        if len(users) >= FETCH_LIMIT:
            raise CommandError(f"Mindestens {FETCH_LIMIT} Konten erhalten, vermutlich unvollständig.")
        if len({user["id"] for user in users}) != len(users):
            raise CommandError("Die Daten enthalten doppelte Konto-IDs.")

        total = sum(int(user["balance"]) for user in users)
        self.stdout.write(f"{len(users)} Konten mit einem Gesamtsaldo von {format_cents(total)} gefunden.")

        with transaction.atomic():
            now = timezone.now()
            for user in users:
                balance = int(user["balance"])
                account = Account.objects.create(
                    kind=Account.KIND_LEGACY,
                    name=user["name"].strip(),
                    legacy_id=user["id"],
                    disabled=bool(user.get("isDisabled")),
                    balance=balance,
                    last_booking_at=self._parse_date(user.get("updated")),
                )
                if balance:
                    Transaction.objects.create(
                        account=account, kind=Transaction.KIND_IMPORT, amount=balance, created_at=now,
                        label="Übertrag aus der alten Strichliste", booked_by_name="Import",
                    )

            imported = sum(Account.objects.values_list("balance", flat=True))
            if imported != total:
                raise CommandError(f"Gesamtsaldo stimmt nicht: {format_cents(imported)} statt {format_cents(total)}")

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Probelauf, es wurde nichts geändert."))
                return

        self.stdout.write(self.style.SUCCESS(
            f"{len(users)} Konten übernommen. Die Konten werden beim ersten Nextcloud-Login "
            f"mit gleichem Namen automatisch verknüpft, den Rest im Django-Admin zuordnen."))

    def _load(self, url, auth, file):
        if file:
            with open(file, encoding="utf-8") as handle:
                return json.load(handle)["users"]

        session = requests.Session()
        if auth:
            session.auth = tuple(auth.split(":", 1))
        try:
            response = session.get(f"{url.rstrip('/')}/api/user", params={"limit": FETCH_LIMIT}, timeout=30)
            response.raise_for_status()
            return response.json()["users"]
        except (requests.RequestException, ValueError, KeyError) as error:
            raise CommandError(f"Konten konnten nicht geladen werden: {error}") from error

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        return timezone.make_aware(datetime.strptime(value, "%Y-%m-%d %H:%M:%S"))
