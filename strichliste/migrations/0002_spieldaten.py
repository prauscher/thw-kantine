"""Spieldaten für den Testbetrieb.

Werden beim Import der alten Strichliste (manage.py strichliste_import) wieder
gelöscht. Die Benutzernamen beginnen mit "spiel-", damit sie nie mit echten
Nextcloud-Benutzern kollidieren.
"""
from datetime import timedelta

from django.db import migrations
from django.utils import timezone

TAGS = ["Gast", "Feuerwehr", "Ehemalige", "Helfervereinigung", "Eltern THW-Jugend"]

MEMBERS = [
    ("spiel-jkoch", "Julia Koch"), ("spiel-mweber", "Marco Weber"), ("spiel-aschmidt", "Andreas Schmidt"),
    ("spiel-lhofmann", "Lena Hofmann"), ("spiel-tbecker", "Tobias Becker"), ("spiel-swolf", "Sarah Wolf"),
    ("spiel-kneumann", "Kai Neumann"), ("spiel-pfischer", "Paul Fischer"), ("spiel-nmeyer", "Nina Meyer"),
    ("spiel-dbraun", "Daniel Braun"), ("spiel-cschulz", "Christian Schulz"), ("spiel-mrichter", "Miriam Richter"),
]

EXTERNALS = [
    ("Ralf Krause", ["Feuerwehr"], "spiel-jkoch", "FF Arheilgen, kommt zu gemeinsamen Übungen"),
    ("Monika Lang", ["Eltern THW-Jugend"], "spiel-swolf", "Mutter von Leon (Jugend)"),
    ("Herbert Zimmermann", ["Ehemalige", "Helfervereinigung"], "spiel-mweber", "bis 2019 Zugführer"),
    ("Gast Übungsabend", ["Gast"], "spiel-lhofmann", "Sammelkonto für Tagesgäste"),
]

# (Name oder Benutzername, Liste von (Betrag in Cent, vor wie vielen Tagen))
BOOKINGS = {
    "spiel-jkoch": [(2000, 40), (-110, 38), (-450, 30), (-60, 21), (-110, 14), (-110, 10), (-110, 3), (-60, 1)],
    "spiel-mweber": [(5000, 60), (-110, 20), (-60, 2)],
    "spiel-aschmidt": [(-450, 50), (-110, 30), (-110, 12), (-450, 4)],
    "spiel-pfischer": [(-450, 70), (-450, 60), (-1000, 45), (-1100, 30), (-450, 20), (-1100, 8)],
    "spiel-tbecker": [(-110, 9), (-110, 5)],
    "spiel-nmeyer": [(2000, 15), (-110, 6)],
    "spiel-dbraun": [(500, 160), (-110, 150)],
    "spiel-mrichter": [(-450, 25), (-450, 11)],
    "Ralf Krause": [(-110, 9), (-110, 2), (-110, 2)],
    "Monika Lang": [(500, 6)],
    "Herbert Zimmermann": [(2000, 90), (-110, 33)],
    "Gast Übungsabend": [(-450, 1), (-440, 1)],
}


def create(apps, schema_editor):
    Config = apps.get_model("strichliste", "Config")
    Tag = apps.get_model("strichliste", "Tag")
    Account = apps.get_model("strichliste", "Account")
    Transaction = apps.get_model("strichliste", "Transaction")

    Config.objects.update_or_create(pk=1, defaults={"test_mode": True})
    tags = {label: Tag.objects.get_or_create(label=label)[0] for label in TAGS}

    accounts = {}
    for username, name in MEMBERS:
        accounts[username] = Account.objects.create(kind="nc", username=username, name=name)
    for name, tag_labels, contact, note in EXTERNALS:
        account = Account.objects.create(kind="ext", name=name, contact=accounts[contact], note=note)
        account.tags.set([tags[label] for label in tag_labels])
        accounts[name] = account

    now = timezone.now()
    for key, bookings in BOOKINGS.items():
        account = accounts[key]
        for amount, days in bookings:
            created_at = now - timedelta(days=days)
            if amount > 0:
                kind, label = "deposit", f"Einzahlung bar {amount // 100},{amount % 100:02d} €"
            else:
                kind, label = "dispense", f"Ausgabe {-amount // 100},{-amount % 100:02d} €"
            Transaction.objects.create(account=account, kind=kind, amount=amount, label=label,
                                       created_at=created_at, booked_by_name="Spieldaten")
            account.balance += amount
            account.last_booking_at = max(filter(None, [account.last_booking_at, created_at]))
        account.save()


def remove(apps, schema_editor):
    Account = apps.get_model("strichliste", "Account")
    Account.objects.filter(username__startswith="spiel-").delete()
    Account.objects.filter(kind="ext", name__in=[name for name, *_ in EXTERNALS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("strichliste", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create, remove),
    ]
