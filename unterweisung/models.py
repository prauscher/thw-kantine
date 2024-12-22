import time
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.template.loader import render_to_string
from django.urls import reverse
from polymorphic.models import PolymorphicModel
from markdownx.models import MarkdownxField
from kantine.hermine import get_hermine_client
from . import utils


# https://github.com/django-polymorphic/django-polymorphic/issues/229#issuecomment-398434412
def NON_POLYMORPHIC_CASCADE(collector, field, sub_objs, using):
    return models.CASCADE(collector, field, sub_objs.non_polymorphic(), using)


class Unterweisung(models.Model):
    label = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Bezeichnung",
        help_text='Eindeutiger Name der Unterweisung, z.B. "Kraftfahrerunterweisung 2024"',
    )
    short_label = models.CharField(
        max_length=20,
        verbose_name="Kurzbezeichnung",
        help_text='Bezeichnung in Tabellenüberschriften, z.B. "Kf"',
    )
    description = models.TextField(
        verbose_name="Beschreibung",
        help_text="Beschreibung der Unterweisung, z.B. an welche Zielgruppe diese sich richtet.",
    )
    success_text = models.TextField(
        verbose_name="Abschluss-Informationen",
        help_text="Text der nach Abschluss der Unterweisung angezeigt wird, z.B. um PIN-Codes beka"
                  "nnt zu geben.",
    )
    active = models.BooleanField(
        verbose_name="Aktiv?",
        help_text="Soll die Unterweisung aktuell angezeigt werden?",
    )

    def get_teilnahme(self, username: str) -> "Teilnahme | None":
        try:
            return Teilnahme.objects.get(username=username, unterweisung=self)
        except Teilnahme.DoesNotExist:
            return None

    def get_absolute_url(self) -> str:
        return reverse("unterweisung:unterweisung_detail",
                       kwargs={"pk": self.pk})

    def __str__(self) -> str:
        return f"{self.label} ({self.short_label})"

    class Meta:
        verbose_name = "Unterweisung"
        verbose_name_plural = "Unterweisungen"
        ordering = ["label"]


class Seite(PolymorphicModel):
    unterweisung = models.ForeignKey("Unterweisung", on_delete=NON_POLYMORPHIC_CASCADE,
                                     related_name="seiten")
    sort = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Sortierreihenfolge der Seite innerhalb der Unterweisung",
    )
    titel = models.CharField(
        max_length=70,
        help_text="Überschrift der Seite",
    )

    def __str__(self) -> str:
        return f"{self.unterweisung}: #{self.sort} {self.titel}"

    def render(self, request, *, export: bool = False) -> str:
        seite_template_name, seite_context = self.get_template_context(request, export=export)
        return render_to_string(seite_template_name, seite_context)

    def clone(self):
        self.pk = None
        self.id = None
        self.save()
        return self

    def get_template_context(self, request, *, export: bool = False) -> tuple[str, dict]:
        raise NotImplementedError

    def parse_result(self, request, kwargs, *, teilnahme: "Teilnahme | None") -> str | None:
        raise NotImplementedError

    def get_absolute_url(self) -> str:
        return reverse("unterweisung:seite_detail",
                       kwargs={"pk": self.pk})

    class Meta:
        ordering = ["sort"]
        verbose_name = "Seite"
        verbose_name_plural = "Seiten"


class FuehrerscheinDatenSeite(Seite):
    def get_template_context(self, request, *, export: bool = False) -> tuple[str, dict]:
        if export:
            return "unterweisung/seite_fuehrerschein_export.html", {}
        return "unterweisung/seite_fuehrerschein.html", {}

    def parse_result(self, request, kwargs, teilnahme: "Teilnahme | None") -> str:
        nummer_papier = kwargs.get("nummer_papier", "")
        nummer_karte = kwargs.get("nummer_karte", "")

        if nummer_papier and nummer_karte:
            raise ValidationError("Entweder Papier- oder EU-Kartenführerscheinnummer angeben")
        elif nummer_papier:
            nummer = nummer_papier
            klassen = ",".join(sorted(kwargs.getlist("klassen_papier")))
        elif nummer_karte:
            nummer = utils.validate_kartenfuehrerschein_nummer(nummer_karte)
            klassen = ",".join(sorted(kwargs.getlist("klassen_karte")))
        else:
            raise ValidationError("Keine Führerscheinnummer angegeben")

        if not klassen:
            raise ValidationError("Keine Führerscheinklassen angegeben")

        return f"{nummer} ({klassen})"

    class Meta:
        verbose_name = "Führerscheindaten-Eingabemaske"
        verbose_name_plural = "Führerscheindaten-Eingabemasken"


class InfoSeite(Seite):
    content = MarkdownxField()
    min_time = models.IntegerField(
        default=10,
        validators=[MinValueValidator(0)],
        verbose_name="Mindestaufenthalt",
        help_text="Wie lange (in Sekunden) muss diese Seite mindestens angezeigt werden, um als be"
                  "standen zu zählen?",
    )

    def get_template_context(self, request, *, export: bool = False) -> tuple[str, dict]:
        # store last timestamp
        seite_pk, timestamp = request.session.get(f"unterweisung_seite_{self.unterweisung.pk}",
                                                  (None, 0))
        if seite_pk != self.pk:
            request.session[f"unterweisung_seite_{self.unterweisung.pk}"] = (self.pk, time.monotonic())

        return "unterweisung/seite_info.html", {
            "content": self.content,
        }

    def parse_result(self, request, kwargs, teilnahme: "Teilnahme | None") -> str | None:
        # ignore minimum time iff unterweisung is done
        if teilnahme is None:
            seite_pk, timestamp = request.session.get(f"unterweisung_seite_{self.unterweisung.pk}",
                                                      (None, 0))

            if seite_pk != self.pk:
                raise ValidationError("Ungültige Bearbeitungsreihenfolge")

            if time.monotonic() - timestamp < self.min_time:
                raise ValidationError("Die Folie wurde zu schnell weitergeschaltet. Bitte lese die Inhalte aufmerksam durch, bevor du auf \"Weiter\" klickst.")

        return None

    class Meta:
        verbose_name = "Folie"
        verbose_name_plural = "Folien"


class HermineNachrichtSeite(Seite):
    ziel_gruppe = models.CharField(
        max_length=20,
        verbose_name="Hermine-Gruppe",
        help_text="Gruppe, in der die Nachricht geschrieben werden soll. In dieser muss der Bot Schreibrechte haben.",
    )
    description = models.TextField(
        verbose_name="Beschreibung",
        help_text="Informationstext für den Benutzer",
    )
    anonymous = models.BooleanField(
        verbose_name="Anonym?",
        help_text="Soll die Hermine-Nachricht anonym erfolgen oder den Namen des aktuellen Benutzers enthalten?",
    )
    required = models.BooleanField(
        verbose_name="Erforderlich?",
        help_text="Muss eine Nachricht angegeben werden oder kann dies unterbleiben?",
    )
    force_message = models.BooleanField(
        verbose_name="Erzwinge eine Nachricht?",
        help_text="Soll auch eine (leere) Nachricht gesendet werden wenn der Benutzer keine angegeben hat?",
    )

    def get_template_context(self, request, *, export: bool = False) -> tuple[str, dict]:
        return "unterweisung/seite_hermine_nachricht.html", {
            "description": self.description,
            "anonymous": self.anonymous,
            "required": self.required,
        }

    def parse_result(self, request, kwargs, teilnahme: "Teilnahme | None") -> str | None:
        message = kwargs.get("message", "").strip()
        if not message and self.required:
            raise ValidationError("Es muss eine Nachricht angegeben werden")

        if message or self.force_message:
            # Send message
            hermine_client = get_hermine_client()

            channels = [channel
                        for company in hermine_client.get_companies()
                        for channel in hermine_client.get_channels(company["id"])]
            channel_dict = next(filter(lambda chan_dict: chan_dict["name"] == hermine_channel, channels))

            if self.anonymous:
                hermine_message = (
                    f"In Unterweisung {self.unterweisung.label} wurde bei Folie {self.titel} eine"
                    f"Nachricht hinterlassen: {message}")
            else:
                hermine_message = (
                    f"{request.jwt_user_display} hat bei Folie {self.titel} in Unterweisung "
                    f"{self.unterweisung.label} eine Nachricht hinterlassen: {message}")

            hermine_client.send_msg(("channel", self.ziel_gruppe),
                                    hermine_message)

        return None

    class Meta:
        verbose_name = "Nachrichten-Seite"
        verbose_name_plural = "Nachrichten-Seiten"


class MultipleChoiceSeite(Seite):
    min_richtig = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Benötigte richtig beantwortete Fragen",
        help_text="Wie viele Fragen muss ein*e Teilnehmer*in richtig beantworten, um die Seite zu "
                  "bestehen. Hinweis: Erforderliche Fragen müssen immer richtig beantwortet werden"
                  ".",
    )
    fragen = models.ManyToManyField("MultipleChoiceFrage",
                                    related_name="seiten")

    def clone(self):
        fragen = []
        for frage in self.fragen.all():
            antworten = []
            for antwort in frage.antworten.all():
                antwort.pk = None
                antwort.save()
                antworten.append(antwort)

            frage.pk = None
            frage.save()
            frage.antworten.set(antworten)
            fragen.append(frage)

        clone = super().clone()
        clone.fragen.set(fragen)
        return clone

    def get_template_context(self, request, *, export: bool = False) -> tuple[str, dict]:
        fragen = [
            {"pk": frage.pk,
             "frage": frage.text,
             "optional": frage.optional,
             "antworten": [(antwort.pk, antwort.text,
                            antwort.richtig if export else str(antwort.pk) in request.POST.getlist(f"frage_{frage.pk}"))
                           for antwort in frage.antworten.order_by("?").all()],
             "richtige_antworten": sum(
                 1 if antwort.richtig else 0
                 for antwort in frage.antworten.all())}
            for frage in self.fragen.all()
        ]

        return "unterweisung/seite_multiplechoice.html", {
            "fragen": fragen,
            "min_richtig": self.min_richtig,
        }

    def parse_result(self, request, kwargs, teilnahme: "Teilnahme | None") -> str | None:
        result = ""
        richtige_fragen = 0
        for frage in self.fragen.all():
            gewaehlte_antworten = set(kwargs.getlist(f"frage_{frage.pk}"))
            richtige_antworten = set(str(antwort.pk)
                                     for antwort in frage.antworten.all()
                                     if antwort.richtig)
            if gewaehlte_antworten != richtige_antworten:
                if not frage.optional:
                    raise ValidationError("Mindestens eine erforderliche Antwort war falsch")
                result += "❌"
            else:
                richtige_fragen += 1
                result += "✓"

        if richtige_fragen < self.min_richtig:
            raise ValidationError("Zu viele Falsche Antworten")

        return result

    class Meta:
        verbose_name = "Multiple-Choice Seite"
        verbose_name_plural = "Multiple-Choice Seiten"


class MultipleChoiceFrage(models.Model):
    text = models.TextField(
        verbose_name="Fragetext",
        help_text="Überschrift der einzelnen Optionen",
    )
    sort = models.IntegerField(
        default=0,
        db_index=True,
        verbose_name="Sortierreihenfolge",
        help_text="Sortierreihenfolge der Frage innerhalb der Seite",
    )
    optional = models.BooleanField(
        default=False,
        verbose_name="Optionale Frage",
        help_text="Eine optionale Frage muss nicht zwingend richtig beantwortet werden, um den Fra"
                  "genkatalog einer Seite abzuschließen. Allerdings müssen je Seite mindestens ein"
                  "e einstellbare Zahl von Fragen richtig beantwortet werden, zu denen auch die op"
                  "tionalen Fragen zählen.",
    )

    def __str__(self) -> str:
        return f"{self.text}"

    class Meta:
        ordering = ["sort"]
        verbose_name = "Multiple-Choice Frage"
        verbose_name_plural = "Multiple-Choice Fragen"


class MultipleChoiceOption(models.Model):
    frage = models.ForeignKey("MultipleChoiceFrage", on_delete=models.CASCADE,
                              related_name="antworten")
    richtig = models.BooleanField(
        verbose_name="Richtige Antwort?",
        help_text="Hinweis: Wird genau eine Antwort der Frage als richtig ausgewählt, werden diese"
                  " als Auswahlbox angezeigt, anderenfalls wird eine Mehrfachauswahl angeboten.",
    )
    text = models.TextField(
        verbose_name="Antworttext",
        help_text="Antwortmöglichkeit zur Frage, welche in zufälliger Reihenfolge angezeigt werden",
    )

    def __str__(self) -> str:
        return f"{self.frage} - {self.text}"

    class Meta:
        verbose_name = "Multiple-Choice Antwort"
        verbose_name_plural = "Multiple-Choice Antworten"


class Teilnahme(models.Model):
    username = models.CharField(max_length=50)
    fullname = models.CharField(max_length=70, blank=True)
    unterweisung = models.ForeignKey("Unterweisung", on_delete=models.CASCADE,
                                     related_name="teilnahmen")
    abgeschlossen_at = models.DateTimeField(null=True, blank=True)
    ergebnis = models.TextField(blank=True)

    def __str__(self) -> str:
        return (f'{self.unterweisung}: {self.fullname or self.username} ('
                f'{"Offen" if self.abgeschlossen_at is None else "Abgeschlossen"})')

    class Meta:
        verbose_name = "Teilnahme"
        verbose_name_plural = "Teilnahmen"
        ordering = ["unterweisung", "username"]
        constraints = [
            models.UniqueConstraint(fields=["username", "unterweisung"], name="teilnahme_unique"),
        ]
