from django.db import models
from django.utils import timezone

from . import settings as app_settings


class DispenseButton(models.Model):
    """Ein Button zum Abbuchen, z.B. „Getränk“ für 1,10 €."""
    label = models.CharField(max_length=30, verbose_name="Bezeichnung")
    cents = models.PositiveIntegerField(verbose_name="Preis (Cent)")
    position = models.PositiveIntegerField(default=0, verbose_name="Reihenfolge")

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "Ausgabe-Button"
        verbose_name_plural = "Ausgabe-Buttons"

    def __str__(self):
        return f"{self.label} ({self.cents / 100:.2f} €)"


class Tag(models.Model):
    label = models.CharField(max_length=40, unique=True, verbose_name="Bezeichnung")

    class Meta:
        ordering = ["label"]

    def __str__(self):
        return self.label


class Account(models.Model):
    KIND_NEXTCLOUD = "nc"
    KIND_EXTERN = "ext"
    KIND_LEGACY = "alt"
    KINDS = [
        (KIND_NEXTCLOUD, "Nextcloud"),
        (KIND_EXTERN, "Extern"),
        (KIND_LEGACY, "Altes System, noch nicht verknüpft"),
    ]

    kind = models.CharField(max_length=3, choices=KINDS, verbose_name="Art")
    username = models.CharField(
        max_length=50, null=True, blank=True, unique=True,
        verbose_name="Benutzername", help_text="Benutzername in NextCloud, nur bei Nextcloud-Konten.",
    )
    name = models.CharField(max_length=100, verbose_name="Name")
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="Tags")
    contact = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        limit_choices_to={"kind": KIND_NEXTCLOUD},
        verbose_name="Betreut von", help_text="Ansprechperson im OV für externe Personen.",
    )
    note = models.CharField(max_length=200, blank=True, verbose_name="Notiz")
    balance = models.IntegerField(default=0, verbose_name="Saldo (Cent)")
    legacy_id = models.IntegerField(null=True, blank=True, unique=True, verbose_name="ID im alten System")
    disabled = models.BooleanField(default=False, verbose_name="Deaktiviert")
    created_at = models.DateTimeField(auto_now_add=True)
    last_booking_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_extern(self) -> bool:
        return self.kind == self.KIND_EXTERN

    def is_stale(self) -> bool:
        if self.last_booking_at is None:
            return False
        return self.last_booking_at < timezone.now() - timezone.timedelta(days=app_settings.STALE_DAYS)


class Transaction(models.Model):
    KIND_DISPENSE = "dispense"
    KIND_DEPOSIT = "deposit"
    KIND_TRANSFER = "transfer"
    KIND_IMPORT = "import"
    KIND_CORRECTION = "correction"
    KINDS = [
        (KIND_DISPENSE, "Ausgabe"),
        (KIND_DEPOSIT, "Einzahlung"),
        (KIND_TRANSFER, "Überweisung"),
        (KIND_IMPORT, "Übernahme altes System"),
        (KIND_CORRECTION, "Korrektur"),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=10, choices=KINDS)
    amount = models.IntegerField(verbose_name="Betrag (Cent)")
    label = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)
    booked_by_uid = models.CharField(max_length=50, blank=True)
    booked_by_name = models.CharField(max_length=100)
    via_tablet = models.BooleanField(default=False)
    pair = models.OneToOneField("self", null=True, blank=True, on_delete=models.SET_NULL,
                                help_text="Gegenbuchung einer Überweisung")
    reverted_at = models.DateTimeField(null=True, blank=True)
    reverted_by_name = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.account}: {self.amount / 100:+.2f} € {self.label}"
