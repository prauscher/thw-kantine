import json
import os
import tempfile
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Account, DispenseButton, Transaction


# ManifestStaticFilesStorage bräuchte vorher collectstatic
@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class StrichlisteTestCase(TestCase):
    def login(self, uid="mmuster", name="Max Muster"):
        session = self.client.session
        session["jwt_userdata"] = {"uid": uid, "displayName": name}
        session.save()

    def own(self, uid="mmuster"):
        return Account.objects.get(username=uid)

    def book(self, url, cents, action="dispense"):
        value = DispenseButton.objects.get(cents=cents).pk if action == "dispense" else cents
        return self.client.post(url, {"action": action, "value": value})


class BookingTests(StrichlisteTestCase):
    def setUp(self):
        self.login()
        DispenseButton.objects.create(label="Getränk klein", cents=60)
        DispenseButton.objects.create(label="Getränke", cents=110)
        DispenseButton.objects.create(label="Essen", cents=450)
        self.extern = Account.objects.create(kind=Account.KIND_EXTERN, name="Gast")
        self.other = Account.objects.create(kind=Account.KIND_NEXTCLOUD, username="other", name="Erika Beispiel")

    def test_own_account_created_on_first_visit(self):
        self.assertEqual(self.client.get(reverse("strichliste:start")).status_code, 200)
        self.assertEqual(self.own().name, "Max Muster")

    def test_book_own_account(self):
        self.book(reverse("strichliste:start"), 110)
        self.book(reverse("strichliste:start"), 500, action="deposit")
        account = self.own()
        self.assertEqual(account.balance, 390)
        self.assertEqual(account.transactions.count(), 2)
        self.assertEqual(account.transactions.first().booked_by_uid, "mmuster")

    def test_only_configured_steps(self):
        self.client.post(reverse("strichliste:start"), {"action": "dispense", "value": 999999})
        self.book(reverse("strichliste:start"), 1234, action="deposit")
        self.assertEqual(self.own().balance, 0)

    def test_named_buttons(self):
        self.book(reverse("strichliste:start"), 110)
        tx = self.own().transactions.get()
        self.assertEqual((tx.amount, tx.label), (-110, "Getränke (1,10 €)"))

    def test_book_extern_but_not_other_member(self):
        self.client.get(reverse("strichliste:start"))
        self.book(reverse("strichliste:konto", args=[self.extern.pk]), 110)
        self.extern.refresh_from_db()
        self.assertEqual(self.extern.balance, -110)

        response = self.book(reverse("strichliste:konto", args=[self.other.pk]), 110)
        self.assertEqual(response.status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.balance, 0)

    def test_hard_limit(self):
        with mock.patch.dict(os.environ, {"STRICHLISTE_HARD_LIMIT": "-200"}):
            self.book(reverse("strichliste:start"), 110)
            self.book(reverse("strichliste:start"), 110)
        self.assertEqual(self.own().balance, -110)

    def test_revert_within_window_only(self):
        self.book(reverse("strichliste:start"), 450)
        tx = self.own().transactions.get()
        self.client.post(reverse("strichliste:storno", args=[tx.pk]))
        self.assertEqual(self.own().balance, 0)
        tx.refresh_from_db()
        self.assertIsNotNone(tx.reverted_at)

        self.book(reverse("strichliste:start"), 450)
        old = self.own().transactions.filter(reverted_at__isnull=True).get()
        Transaction.objects.filter(pk=old.pk).update(created_at=timezone.now() - timezone.timedelta(minutes=10))
        self.client.post(reverse("strichliste:storno", args=[old.pk]))
        self.assertEqual(self.own().balance, -450)

    def test_cannot_revert_foreign_booking(self):
        self.book(reverse("strichliste:konto", args=[self.extern.pk]), 110)
        tx = self.extern.transactions.get()
        self.login("someone", "Jemand Anderes")
        self.client.post(reverse("strichliste:storno", args=[tx.pk]))
        self.extern.refresh_from_db()
        self.assertEqual(self.extern.balance, -110)

    def test_transfer_disabled_by_default(self):
        own = self.client.get(reverse("strichliste:start")) and self.own()
        url = reverse("strichliste:ueberweisen", args=[own.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

        with mock.patch.dict(os.environ, {"STRICHLISTE_TRANSFERS": "1"}):
            self.client.post(url, {"target": self.other.pk, "amount": "2,50", "comment": ""})
        self.other.refresh_from_db()
        self.assertEqual(self.own().balance, -250)
        self.assertEqual(self.other.balance, 250)

        outgoing = own.transactions.get()
        self.client.post(reverse("strichliste:storno", args=[outgoing.pk]))
        self.other.refresh_from_db()
        self.assertEqual((self.own().balance, self.other.balance), (0, 0))

    def test_warning_below_threshold(self):
        self.client.get(reverse("strichliste:start"))
        Account.objects.filter(username="mmuster").update(balance=-4000)
        response = self.client.get(reverse("strichliste:start"))
        self.assertContains(response, "sl-debt")
        Account.objects.filter(username="mmuster").update(balance=-3990)
        self.assertNotContains(self.client.get(reverse("strichliste:start")), 'class="sl-debt')

    def test_history_paginated(self):
        for _ in range(12):
            self.book(reverse("strichliste:start"), 60)
        response = self.client.get(reverse("strichliste:start"))
        self.assertEqual(len(response.context["page"]), 10)
        self.assertContains(response, "Seite 1 von 2")


@mock.patch.dict(os.environ, {"STRICHLISTE_TABLET_PIN": "2468"})
class TabletTests(StrichlisteTestCase):
    def setUp(self):
        DispenseButton.objects.create(label="Getränke", cents=110)
        self.member = Account.objects.create(kind=Account.KIND_NEXTCLOUD, username="member", name="Mitglied")

    def url(self, name, *args, pin="2468"):
        return reverse(f"strichliste:tablet_{name}", args=[pin, *args])

    def test_wrong_pin(self):
        self.assertEqual(self.client.get(self.url("konten", pin="0000")).status_code, 404)

    def test_no_pin_configured(self):
        with mock.patch.dict(os.environ, {"STRICHLISTE_TABLET_PIN": ""}):
            self.assertEqual(self.client.get(self.url("konten")).status_code, 404)

    def test_books_any_account(self):
        self.assertEqual(self.client.get(self.url("konten")).status_code, 200)
        self.book(self.url("konto", self.member.pk), 110)
        self.member.refresh_from_db()
        self.assertEqual(self.member.balance, -110)
        tx = self.member.transactions.get()
        self.assertEqual((tx.via_tablet, tx.booked_by_name), (True, "Theken-Tablet"))
        self.client.post(self.url("storno", tx.pk))
        self.member.refresh_from_db()
        self.assertEqual(self.member.balance, 0)


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

    def test_login_links_legacy_account_by_name(self):
        self.run_import()
        self.login("mmuster", "Max Muster")
        self.client.get(reverse("strichliste:start"))
        account = self.own()
        self.assertEqual((account.legacy_id, account.balance, account.kind), (1, -1250, Account.KIND_NEXTCLOUD))
