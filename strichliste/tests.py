import json
import os
import tempfile
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import settings as app_settings
from .models import Account, DispenseButton, Transaction


# ManifestStaticFilesStorage bräuchte vorher collectstatic
@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class StrichlisteTestCase(TestCase):
    def login(self, uid="mmuster", name="Max Muster"):
        session = self.client.session
        session["jwt_userdata"] = {"uid": uid, "displayName": name}
        session.save()

    def spend(self, url, cents):
        return self.client.post(url, {"button": DispenseButton.objects.get(cents=cents).pk})


class OwnAccountTests(StrichlisteTestCase):
    def setUp(self):
        self.login()
        DispenseButton.objects.create(label="Getränk klein", cents=60)
        DispenseButton.objects.create(label="Getränke", cents=110)
        DispenseButton.objects.create(label="Essen", cents=450)
        self.account = Account.objects.create(kind=Account.KIND_NEXTCLOUD, username="mmuster", name="Max Muster")
        self.other = Account.objects.create(kind=Account.KIND_NEXTCLOUD, username="other", name="Erika Beispiel")

    def test_spend(self):
        self.spend(reverse("strichliste:spend"), 110)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, -110)
        tx = self.account.transactions.get()
        self.assertEqual((tx.label, tx.booked_by_uid, tx.via_tablet), ("Getränke (1,10 €)", "mmuster", False))

    def test_unknown_button(self):
        self.client.post(reverse("strichliste:spend"), {"button": 999999})
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 0)

    def test_no_cash_deposit_without_tablet(self):
        self.assertEqual(self.client.post(reverse("strichliste:start"), {"amount": 500}).status_code, 405)

    def test_hard_limit(self):
        with mock.patch.object(app_settings, "HARD_LIMIT", -200):
            self.spend(reverse("strichliste:spend"), 110)
            self.spend(reverse("strichliste:spend"), 110)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, -110)

    def test_revert_within_window_only(self):
        self.spend(reverse("strichliste:spend"), 450)
        tx = self.account.transactions.get()
        self.client.post(reverse("strichliste:revert", args=[tx.pk]))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 0)

        self.spend(reverse("strichliste:spend"), 450)
        old = self.account.transactions.filter(reverted_at__isnull=True).get()
        Transaction.objects.filter(pk=old.pk).update(created_at=timezone.now() - timezone.timedelta(minutes=10))
        self.client.post(reverse("strichliste:revert", args=[old.pk]))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, -450)

    def test_cannot_revert_foreign_booking(self):
        self.login("other", "Erika Beispiel")
        self.spend(reverse("strichliste:spend"), 110)
        tx = self.other.transactions.get()
        self.login()
        self.assertEqual(self.client.post(reverse("strichliste:revert", args=[tx.pk])).status_code, 404)

    def test_transfer(self):
        url = reverse("strichliste:transfer")
        self.assertEqual(self.client.get(url).status_code, 404)

        with mock.patch.object(app_settings, "TRANSFERS_ENABLED", True):
            self.client.post(url, {"target": self.other.pk, "amount": "2,50", "comment": ""})
        self.account.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual((self.account.balance, self.other.balance), (-250, 250))

        self.client.post(reverse("strichliste:revert", args=[self.account.transactions.get().pk]))
        self.account.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual((self.account.balance, self.other.balance), (0, 0))

    def test_warning_below_threshold(self):
        Account.objects.filter(pk=self.account.pk).update(balance=-4000)
        self.assertContains(self.client.get(reverse("strichliste:start")), "bitte ausgleichen")
        Account.objects.filter(pk=self.account.pk).update(balance=-3990)
        self.assertNotContains(self.client.get(reverse("strichliste:start")), "bitte ausgleichen")

    def test_history_paginated(self):
        for _ in range(12):
            self.spend(reverse("strichliste:spend"), 60)
        response = self.client.get(reverse("strichliste:start"))
        self.assertEqual(len(response.context["page"]), 10)
        self.assertContains(response, "Seite 1 von 2")


class UnassignedTests(StrichlisteTestCase):
    def setUp(self):
        self.login()
        self.legacy = Account.objects.create(kind=Account.KIND_LEGACY, name="Maxi", balance=-1250)

    def test_start_lists_unassigned(self):
        self.assertContains(self.client.get(reverse("strichliste:start")), "Maxi")

    def test_assign_user(self):
        self.client.post(reverse("strichliste:assign_user", args=[self.legacy.pk]))
        self.legacy.refresh_from_db()
        self.assertEqual((self.legacy.kind, self.legacy.username, self.legacy.balance),
                         (Account.KIND_NEXTCLOUD, "mmuster", -1250))

    def test_create_user(self):
        self.client.post(reverse("strichliste:create_user"))
        self.assertEqual(Account.objects.get(username="mmuster").name, "Max Muster")

    def test_only_one_account(self):
        self.client.post(reverse("strichliste:create_user"))
        self.client.post(reverse("strichliste:assign_user", args=[self.legacy.pk]))
        self.client.post(reverse("strichliste:create_user"))
        self.legacy.refresh_from_db()
        self.assertEqual((self.legacy.kind, Account.objects.filter(username="mmuster").count()),
                         (Account.KIND_LEGACY, 1))


class PaypalTests(StrichlisteTestCase):
    def test_public(self):
        self.assertEqual(self.client.get(reverse("strichliste:paypal")).status_code, 404)
        with mock.patch.object(app_settings, "PAYPAL_LINK", "https://paypal.me/example"):
            self.assertContains(self.client.get(reverse("strichliste:paypal")), "data:image/svg+xml")


@mock.patch.object(app_settings, "TABLET_PIN", "2468")
class TabletTests(StrichlisteTestCase):
    def setUp(self):
        DispenseButton.objects.create(label="Getränke", cents=110)
        self.member = Account.objects.create(kind=Account.KIND_NEXTCLOUD, username="member", name="Mitglied")

    def url(self, name, *args, pin="2468"):
        return reverse(f"strichliste:tablet_{name}", args=[pin, *args])

    def test_wrong_pin(self):
        self.assertEqual(self.client.get(self.url("accounts", pin="0000")).status_code, 404)

    def test_no_pin_configured(self):
        with mock.patch.object(app_settings, "TABLET_PIN", ""):
            self.assertEqual(self.client.get(self.url("accounts")).status_code, 404)

    def test_books_any_account(self):
        self.assertContains(self.client.get(self.url("accounts")), "Mitglied")
        self.assertContains(self.client.get(self.url("account", self.member.pk)), "Bar eingezahlt")
        self.spend(self.url("spend", self.member.pk), 110)
        self.client.post(self.url("credit", self.member.pk), {"amount": 500})
        self.member.refresh_from_db()
        self.assertEqual(self.member.balance, 390)

        tx = self.member.transactions.last()
        self.assertEqual((tx.via_tablet, tx.booked_by_name), (True, "Theken-Tablet"))
        self.client.post(self.url("revert", self.member.pk, tx.pk))
        self.member.refresh_from_db()
        self.assertEqual(self.member.balance, 500)

    def test_only_configured_deposit_steps(self):
        self.client.post(self.url("credit", self.member.pk), {"amount": 1234})
        self.member.refresh_from_db()
        self.assertEqual(self.member.balance, 0)

    def test_create_extern(self):
        self.client.post(self.url("create_extern"), {"name": "Gast", "contact": self.member.pk, "note": ""})
        self.assertEqual(Account.objects.get(name="Gast").kind, Account.KIND_EXTERN)


class ImportTests(StrichlisteTestCase):
    USERS = {"users": [
        {"id": 1, "name": "Max Muster", "balance": -1250, "isDisabled": False, "updated": "2026-02-20 14:23:06"},
        {"id": 2, "name": "Spitzname", "balance": 300, "isDisabled": False, "updated": "2025-01-01 10:00:00"},
        {"id": 3, "name": "Weg", "balance": 0, "isDisabled": True, "updated": None},
    ]}

    def run_import(self, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(self.USERS, handle)
        try:
            call_command("strichliste_import", "--file", handle.name, *args, stdout=open(os.devnull, "w"))
        finally:
            os.unlink(handle.name)

    def test_import(self):
        self.run_import()
        self.assertEqual(Account.objects.count(), 3)
        self.assertEqual(sum(Account.objects.values_list("balance", flat=True)), -950)
        self.assertEqual(Account.objects.get(legacy_id=1).transactions.get().kind, Transaction.KIND_IMPORT)

        with self.assertRaises(CommandError):
            self.run_import()

    def test_dry_run_changes_nothing(self):
        self.run_import("--dry-run")
        self.assertFalse(Account.objects.exists())
