import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.urls import reverse
from django.utils import timezone


def _parse_steps(value: str) -> list[int]:
    return [int(step) for step in value.split(",") if step.strip()]


class Config(models.Model):
    """Singleton mit den Einstellungen der Strichliste, immer pk=1."""

    test_mode = models.BooleanField(
        default=True,
        verbose_name="Testbetrieb",
        help_text="Zeigt auf allen Seiten einen Hinweis, dass nur Spieldaten enthalten sind. "
                  "Wird beim Import der alten Strichliste automatisch abgeschaltet.",
    )
    transfers_enabled = models.BooleanField(
        default=False,
        verbose_name="Überweisungen erlauben",
        help_text="Mitglieder können Geld an andere Konten überweisen.",
    )
    paypal_link = models.URLField(
        blank=True,
        verbose_name="PayPal-Link",
        help_text="Ziel des QR-Codes unter „Mit PayPal aufladen“. Leer lassen, um den Button auszublenden.",
    )
    warn_below = models.IntegerField(
        default=-4000,
        verbose_name="Warnschwelle (Cent)",
        help_text="Ab diesem Saldo wird deutlich zum Ausgleichen aufgefordert.",
    )
    hard_limit = models.IntegerField(
        default=-20000,
        verbose_name="Untergrenze (Cent)",
        help_text="Ausgaben, die den Saldo unter diesen Wert bringen würden, werden abgelehnt.",
    )
    undo_minutes = models.PositiveIntegerField(
        default=5,
        verbose_name="Storno-Frist (Minuten)",
    )
    tablet_idle_seconds = models.PositiveIntegerField(
        default=30,
        verbose_name="Tablet: zurück zur Übersicht nach (Sekunden)",
    )
    stale_days = models.PositiveIntegerField(
        default=100,
        verbose_name="Inaktiv nach (Tagen)",
    )
    deposit_steps = models.CharField(
        max_length=100,
        default="10,50,100,200,500,1000",
        verbose_name="Einzahlungs-Buttons (Cent, kommagetrennt)",
    )

    class Meta:
        verbose_name = "Einstellungen"
        verbose_name_plural = "Einstellungen"

    def __str__(self):
        return "Einstellungen der Strichliste"

    @classmethod
    def get(cls) -> "Config":
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    @property
    def deposit_list(self) -> list[int]:
        return _parse_steps(self.deposit_steps)


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

    def get_absolute_url(self):
        return reverse("strichliste:konto", kwargs={"pk": self.pk})

    @property
    def is_extern(self) -> bool:
        return self.kind == self.KIND_EXTERN

    def is_stale(self, config: Config) -> bool:
        if self.last_booking_at is None:
            return False
        return self.last_booking_at < timezone.now() - timezone.timedelta(days=config.stale_days)


class Tablet(models.Model):
    MAX_FAILED_ATTEMPTS = 5
    LOCK_MINUTES = 15

    label = models.CharField(max_length=60, verbose_name="Bezeichnung", help_text="z.B. „Tablet Aufenthaltsraum“")
    token = models.CharField(max_length=64, unique=True, editable=False, default=secrets.token_urlsafe)
    pin_hash = models.CharField(max_length=200, editable=False)
    # Erhöhen meldet alle Geräte ab, die mit diesem Tablet-Zugang angemeldet sind
    session_version = models.PositiveIntegerField(default=1, editable=False)
    active = models.BooleanField(default=True, verbose_name="Aktiv")
    failed_attempts = models.PositiveIntegerField(default=0, editable=False)
    locked_until = models.DateTimeField(null=True, blank=True, editable=False)
    last_seen_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label

    def get_absolute_url(self):
        return reverse("strichliste:tablet_start", kwargs={"token": self.token})

    def set_pin(self, pin: str):
        self.pin_hash = make_password(pin)
        self.session_version += 1
        self.failed_attempts = 0
        self.locked_until = None

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > timezone.now()

    def check_pin(self, pin: str) -> bool:
        if self.is_locked:
            return False
        if check_password(pin, self.pin_hash):
            self.failed_attempts = 0
            self.locked_until = None
            self.save(update_fields=["failed_attempts", "locked_until"])
            return True
        self.failed_attempts += 1
        if self.failed_attempts >= self.MAX_FAILED_ATTEMPTS:
            self.failed_attempts = 0
            self.locked_until = timezone.now() + timezone.timedelta(minutes=self.LOCK_MINUTES)
        self.save(update_fields=["failed_attempts", "locked_until"])
        return False


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
    tablet = models.ForeignKey(Tablet, null=True, blank=True, on_delete=models.SET_NULL)
    pair = models.OneToOneField("self", null=True, blank=True, on_delete=models.SET_NULL,
                                help_text="Gegenbuchung einer Überweisung")
    reverted_at = models.DateTimeField(null=True, blank=True)
    reverted_by_name = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.account}: {self.amount / 100:+.2f} € {self.label}"
