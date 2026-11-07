import json
import os
import tempfile
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .auth import cookie_name
from .models import Account, Config, DispenseButton, Tablet, Transaction


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
        button = DispenseButton.objects.get(cents=110)
        with mock.patch.dict(os.environ, {"STRICHLISTE_ADMINS": "mmuster"}):
            self.client.post(reverse("strichliste:admin_buttons"), {"pk": button.pk, "label": "Getränke", "price": "1,20", "position": 1})
            self.client.post(reverse("strichliste:admin_buttons"), {"label": "Kaffee", "price": "0,50", "position": 4})
        self.assertContains(self.client.get(reverse("strichliste:start")), "Kaffee")
        self.book(reverse("strichliste:start"), 120)
        tx = self.own().transactions.get()
        self.assertEqual((tx.amount, tx.label), (-120, "Getränke (1,20 €)"))

    def test_book_extern_but_not_other_member(self):
        self.client.get(reverse("strichliste:start"))
        self.book(reverse("strichliste:konto", args=[self.extern.pk]), 110)
        self.extern.refresh_from_db()
        self.assertEqual(self.extern.balance, -110)

        response = self.book(reverse("strichliste:konto", args=[self.other.pk]), 110)
        self.assertEqual(response.status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.balance, 0)

    def test_admin_can_book_other_member(self):
        with mock.patch.dict(os.environ, {"STRICHLISTE_ADMINS": "mmuster"}):
            self.book(reverse("strichliste:konto", args=[self.other.pk]), 110)
        self.other.refresh_from_db()
        self.assertEqual(self.other.balance, -110)

    def test_hard_limit(self):
        Config.objects.filter(pk=1).update(hard_limit=-200)
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

        Config.objects.filter(pk=1).update(transfers_enabled=True)
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

    def test_verwaltung_only_for_admins(self):
        self.assertEqual(self.client.get(reverse("strichliste:admin_konten")).status_code, 404)
        with mock.patch.dict(os.environ, {"STRICHLISTE_ADMINS": "mmuster"}):
            self.assertEqual(self.client.get(reverse("strichliste:admin_konten")).status_code, 200)


class TabletTests(StrichlisteTestCase):
    def setUp(self):
        self.tablet = Tablet(label="Theke")
        self.tablet.set_pin("2468")
        self.tablet.save()
        self.member = Account.objects.create(kind=Account.KIND_NEXTCLOUD, username="member", name="Mitglied")

    def url(self, name, *args):
        return reverse(f"strichliste:tablet_{name}", args=[self.tablet.token, *args])

    def unlock(self, pin="2468"):
        return self.client.post(self.url("pin"), {"pin": pin})

    def test_requires_pin(self):
        response = self.client.get(self.url("konten"))
        self.assertRedirects(response, self.url("pin"))

    def test_wrong_token(self):
        self.assertEqual(self.client.get(reverse("strichliste:tablet_konten", args=["falsch"])).status_code, 404)

    def test_pin_unlocks_permanently_and_books_any_account(self):
        response = self.unlock()
        self.assertRedirects(response, self.url("konten"))
        self.assertGreater(response.cookies[cookie_name(self.tablet)]["max-age"], 365 * 24 * 3600)

        self.assertEqual(self.client.get(self.url("konten")).status_code, 200)
        self.book(self.url("konto", self.member.pk), 110)
        self.member.refresh_from_db()
        self.assertEqual(self.member.balance, -110)
        tx = self.member.transactions.get()
        self.assertEqual((tx.tablet, tx.booked_by_name), (self.tablet, "Theke"))

    def test_tablet_has_no_admin_access(self):
        self.unlock()
        with mock.patch.dict(os.environ, {"STRICHLISTE_ADMINS": ""}):
            self.assertNotEqual(self.client.get(reverse("strichliste:admin_konten")).status_code, 200)

    def test_lock_after_failed_attempts(self):
        for _ in range(Tablet.MAX_FAILED_ATTEMPTS):
            self.unlock("0000")
        self.unlock()
        self.assertRedirects(self.client.get(self.url("konten")), self.url("pin"))

    def test_logout_all_devices(self):
        self.unlock()
        Tablet.objects.filter(pk=self.tablet.pk).update(session_version=self.tablet.session_version + 1)
        self.assertRedirects(self.client.get(self.url("konten")), self.url("pin"))

    def test_disabled_tablet(self):
        self.unlock()
        Tablet.objects.filter(pk=self.tablet.pk).update(active=False)
        self.assertEqual(self.client.get(self.url("konten")).status_code, 404)


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

    def test_testdata_present(self):
        self.assertTrue(Config.get().test_mode)
        self.assertTrue(Account.objects.filter(username__startswith="spiel-").exists())

    def test_import_replaces_testdata(self):
        self.run_import()
        self.assertFalse(Config.get().test_mode)
        self.assertEqual(Account.objects.count(), 3)
        self.assertFalse(Account.objects.filter(username__startswith="spiel-").exists())
        self.assertEqual(sum(Account.objects.values_list("balance", flat=True)), -950)
        self.assertEqual(Account.objects.get(legacy_id=1).transactions.get().kind, Transaction.KIND_IMPORT)

        with self.assertRaises(CommandError):
            self.run_import()

    def test_dry_run_changes_nothing(self):
        before = Account.objects.count()
        self.run_import("--dry-run")
        self.assertTrue(Config.get().test_mode)
        self.assertEqual(Account.objects.count(), before)

    def test_login_links_legacy_account_by_name(self):
        self.run_import()
        self.login("mmuster", "Max Muster")
        self.client.get(reverse("strichliste:start"))
        account = self.own()
        self.assertEqual((account.legacy_id, account.balance, account.kind), (1, -1250, Account.KIND_NEXTCLOUD))

    def test_admin_links_legacy_account(self):
        self.run_import()
        self.login("emuster", "Erika Muster")
        self.book(reverse("strichliste:start"), 110)
        legacy = Account.objects.get(legacy_id=2)
        with mock.patch.dict(os.environ, {"STRICHLISTE_ADMINS": "emuster"}):
            self.client.post(reverse("strichliste:admin_verknuepfen", args=[legacy.pk]), {"username": "emuster", "name": ""})
        account = self.own("emuster")
        self.assertEqual((account.balance, account.legacy_id, account.transactions.count()), (190, 2, 2))
        self.assertFalse(Account.objects.filter(pk=legacy.pk).exists())
