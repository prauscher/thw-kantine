import csv
import statistics
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, UTC
from django import forms
from django.contrib import admin, messages
from django.db import models as db_models
from django.urls import path, reverse, reverse_lazy
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.generic import FormView, TemplateView
from polymorphic.admin import (
    PolymorphicInlineSupportMixin,
    PolymorphicParentModelAdmin,
    StackedPolymorphicInline,
)
from markdownx.admin import MarkdownxModelAdmin
from django_object_actions import DjangoObjectActions, action
from markdownx.models import MarkdownxField
from markdownx.widgets import MarkdownxWidget
from kantine.utils import find_login_url
from . import models, views


def _strxfrm(text):
    # yes, locale.strxfmt exists, but alpine (or musl) does not support LC_COLLATE
    # use DIN 5007 variant 2 here
    text = text.replace("ä", "ae")
    text = text.replace("ö", "oe")
    text = text.replace("ü", "ue")
    text = text.replace("ß", "ss")
    return text


class MultipleChoiceOptionInline(admin.StackedInline):
    model = models.MultipleChoiceOption
    extra = 3

    formfield_overrides = {
        MarkdownxField: {'widget': MarkdownxWidget(attrs={"rows": 1, "cols": 60})},
    }


@admin.register(models.MultipleChoiceFrage)
class MultipleChoiceFrageAdmin(admin.ModelAdmin):
    inlines = (MultipleChoiceOptionInline,)

    formfield_overrides = {
        MarkdownxField: {'widget': MarkdownxWidget(attrs={"rows": 2, "cols": 60})},
    }


class SeiteInline(StackedPolymorphicInline):
    class FuehrerscheinDatenInline(StackedPolymorphicInline.Child):
        model = models.FuehrerscheinDatenSeite

    class InfoInline(StackedPolymorphicInline.Child):
        model = models.InfoSeite

    class HermineNachrichtInline(StackedPolymorphicInline.Child):
        model = models.HermineNachrichtSeite

    class MultipleChoiceInline(StackedPolymorphicInline.Child):
        model = models.MultipleChoiceSeite

    model = models.Seite
    child_inlines = (FuehrerscheinDatenInline,
                     InfoInline,
                     HermineNachrichtInline,
                     MultipleChoiceInline)


class UnterweisungExportView(TemplateView):
    template_name = "admin/unterweisung/unterweisung/export.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["unterweisungen"] = [
            (unterweisung,
             [(nr, seite, mark_safe(seite.render(self.request, export=True)))
              for nr, seite in enumerate(unterweisung.seiten.all(), 1)])
            for unterweisung in models.Unterweisung.objects.filter(active=True)]

        return context


class TeilnahmeExportView(TemplateView):
    template_name = "admin/unterweisung/teilnahme/export.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        unterweisungen = list(models.Unterweisung.objects.filter(active=True))
        personen_teilnahmen = defaultdict(
            lambda: {"last_abgeschlossen": None,
                     "first_abgeschlossen": None,
                     "teilnahmen": [(None, None)
                                    for unterweisung in unterweisungen]})

        for teilnahme in models.Teilnahme.objects.filter(unterweisung__in=unterweisungen):
            personen_teilnahmen[teilnahme.teilnehmer]["first_abgeschlossen"] = min(
                filter(lambda i: i is not None,
                       [personen_teilnahmen[teilnahme.teilnehmer]["first_abgeschlossen"],
                        teilnahme.abgeschlossen_at]),
                default=None)
            personen_teilnahmen[teilnahme.teilnehmer]["last_abgeschlossen"] = max(
                filter(lambda i: i is not None,
                       [personen_teilnahmen[teilnahme.teilnehmer]["last_abgeschlossen"],
                        teilnahme.abgeschlossen_at]),
                default=None)

            unterweisung_index = unterweisungen.index(teilnahme.unterweisung)

            personen_teilnahmen[teilnahme.teilnehmer]["teilnahmen"][unterweisung_index] = (
                False if teilnahme.abgeschlossen_at is None else teilnahme.ergebnis,
                teilnahme.duration)

        personen_output = personen_teilnahmen.items()

        if "gruppe" in self.request.GET:
            personen_output = filter(lambda item: item[0].gruppe.endswith(self.request.GET["gruppe"]),
                                     personen_output)

        with suppress(ValueError):
            filter_after = timezone.make_aware(
                datetime.strptime(self.request.GET.get("after", ""), "%Y-%m-%d"))
            personen_output = filter(lambda item: item[1]["last_abgeschlossen"] is not None and
                                                  item[1]["last_abgeschlossen"] >= filter_after,
                                     personen_output)

        if "abgeschlossen_chart" in self.request.GET:
            # list of tuple with timestamp, relative change of part, relative change of done
            abgeschlossen_events = []
            for data in personen_teilnahmen.values():
                if data["first_abgeschlossen"] is not None:
                    abgeschlossen_events.append(
                        (data["first_abgeschlossen"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), 1, 0))
                if data["last_abgeschlossen"] is not None and \
                   all(teilnahme is not False for teilnahme, _ in data["teilnahmen"]):
                    abgeschlossen_events.append(
                        (data["last_abgeschlossen"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), -1, 1))
            abgeschlossen_events.append(
                (timezone.now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), 0, 0))
            abgeschlossen_events.sort()

            context["total_teilnehmer"] = len(personen_teilnahmen)
            context["abgeschlossen_events"] = abgeschlossen_events

        else:
            personen_output = sorted(personen_output, key=lambda item: _strxfrm(str(item[0])))

            gruppen_output = defaultdict(list)
            for teilnehmer, data in personen_output:
                gruppe = ""
                if "include_stats" in self.request.GET:
                    gruppe = teilnehmer.gruppe
                gruppen_output[gruppe].append((teilnehmer, data))

            context["unterweisungen"] = unterweisungen

            durations_combined = [[] for _ in unterweisungen]

            gruppen = []
            for gruppe, personen in gruppen_output.items():
                teilnehmer_open = None
                teilnehmer_done = None
                teilnehmer_part = None
                quantiles = None

                if "include_stats" in self.request.GET:
                    teilnehmer_open = 0
                    teilnehmer_done = 0
                    teilnehmer_part = 0
                    durations = [[] for _ in unterweisungen]

                    for teilnehmer, data in personen:
                        teilnahmen_open = 0
                        teilnahmen_done = 0
                        for i, _ in enumerate(unterweisungen):
                            if data["teilnahmen"][i][0] is False:
                                teilnahmen_open += 1
                            elif data["teilnahmen"][i][0] is not None:
                                teilnahmen_done += 1

                            if data["teilnahmen"][i][1] is not None:
                                durations[i].append(data["teilnahmen"][i][1])
                                durations_combined[i].append(data["teilnahmen"][i][1])

                        if teilnahmen_open == 0:
                            teilnehmer_done += 1
                        elif teilnahmen_done > 0:
                            teilnehmer_part += 1
                        else:
                            teilnehmer_open += 1

                    quantiles = []

                    for i, _ in enumerate(unterweisungen):
                        if len(durations[i]) == 1:
                            # avoid StatisticsWarning
                            durations[i].append(durations[i][0])

                        if durations[i]:
                            _quantiles = statistics.quantiles(durations[i], n=2)
                            quantiles.append({"median": _quantiles[0]})
                        else:
                            quantiles.append(None)

                gruppen.append((gruppe, personen, quantiles,
                                teilnehmer_open, teilnehmer_part, teilnehmer_done,
                                None if teilnehmer_open is None or teilnehmer_part is None or teilnehmer_done is None else teilnehmer_open + teilnehmer_part + teilnehmer_done))

            context["gruppen"] = []
            # ignore numeric prefix in gruppe (used for sorting only)
            for gruppe, *args in sorted(gruppen, key=lambda item: item[0]):
                prefix, _, suffix = gruppe.partition(" ")
                if prefix.isnumeric():
                    gruppe = suffix
                context["gruppen"].append((gruppe, *args))

            if "include_stats" in self.request.GET:
                context["teilnehmer_open"] = sum(item[3] for item in gruppen)
                context["teilnehmer_part"] = sum(item[4] for item in gruppen)
                context["teilnehmer_done"] = sum(item[5] for item in gruppen)
                context["teilnehmer_total"] = context["teilnehmer_open"] + context["teilnehmer_part"] + context["teilnehmer_done"]

                quantiles = []
                for i, _ in enumerate(unterweisungen):
                    if len(durations_combined[i]) == 1:
                        durations_combined[i].append(durations_combined[i][0])

                    if durations_combined[i]:
                        _quantiles = statistics.quantiles(durations_combined[i])
                        quantiles.append({"median": _quantiles[0]})
                    else:
                        quantiles.append(None)

                context["total_quantiles"] = quantiles

        return context


@admin.register(models.Unterweisung)
class UnterweisungAdmin(PolymorphicInlineSupportMixin, DjangoObjectActions, admin.ModelAdmin):
    inlines = (SeiteInline,)
    list_display = ["label", "active"]
    list_filter = ["active"]
    actions = ["activate", "deactivate"]
    change_actions = ["copy_recursive"]
    change_list_template = "admin/unterweisung/unterweisung/change_list.html"

    @action(label="Kopie erstellen",
            description="Kopiert die Unterweisung vollständig.")
    def copy_recursive(self, request, obj):
        seiten = list(obj.seiten.all())

        obj.pk = None
        orig_label = obj.label
        obj.label = f"Kopie von {orig_label}"
        obj.active = False
        i = 1
        while models.Unterweisung.objects.filter(label=obj.label).count() > 0:
            i += 1
            obj.label = f"Kopie({i}) von {orig_label}"
        obj.save()

        for seite in seiten:
            seite = seite.clone()
            seite.unterweisung = obj
            seite.save()

    @action(description="Ausgewählte aktivieren")
    def activate(self, request, queryset):
        queryset.update(active=True)

    @action(description="Ausgewählte deaktivieren")
    def deactivate(self, request, queryset):
        queryset.update(active=False)

    def get_urls(self):
        urls = super().get_urls()
        urls = [
            path("export/",
                 self.admin_site.admin_view(UnterweisungExportView.as_view()),
                 name="unterweisung_unterweisung_export"),
        ] + urls
        return urls


class ImportTeilnahmeForm(forms.Form):
    unterweisung = forms.ModelChoiceField(models.Unterweisung.objects)
    usernames = forms.CharField(widget=forms.Textarea(attrs={"cols": "60", "rows": "40"}))


class ImportTeilnahmeView(FormView):
    model_admin = None
    form_class = ImportTeilnahmeForm
    template_name = "admin/unterweisung/teilnahme/import.html"
    success_url = reverse_lazy("admin:unterweisung_teilnahme_changelist")

    def get_context_data(self, **kwargs):
        return {**admin.site.each_context(self.request),
                "title": "Teilnehmer importieren",
                **super().get_context_data(**kwargs)}

    def form_valid(self, form):
        unterweisung = form.cleaned_data["unterweisung"]
        created = 0
        for username in form.cleaned_data["usernames"].splitlines():
            username = username.strip()
            if not username:
                continue
            teilnehmer, _ = models.Teilnehmer.objects.get_or_create(
                username=username)
            _, obj_created = models.Teilnahme.objects.get_or_create(
                unterweisung=unterweisung,
                teilnehmer=teilnehmer,
                defaults={"abgeschlossen_at": None},
            )
            if obj_created:
                created += 1

        self.model_admin.message_user(
            self.request,
            f"Teilnahme für {created} Benutzer*innen vorgemerkt.",
            messages.SUCCESS,
        )

        return super().form_valid(form)


@admin.register(models.Teilnahme)
class TeilnahmeAdmin(admin.ModelAdmin):
    list_filter = ("unterweisung", "teilnehmer", ("abgeschlossen_at", admin.EmptyFieldListFilter))

    def get_urls(self):
        urls = super().get_urls()
        urls = [
            path("import/",
                 self.admin_site.admin_view(ImportTeilnahmeView.as_view(model_admin=self)),
                 name="unterweisung_teilnahme_import"),
            path("export/",
                 self.admin_site.admin_view(TeilnahmeExportView.as_view()),
                 name="unterweisung_teilnahme_export"),
        ] + urls
        return urls


def get_gruppen_link(gruppe):
    token = views.GruppenUebersichtView.get_token(gruppe)
    path = reverse("unterweisung:ansicht_gruppe", kwargs={"token": token})
    try:
        return find_login_url(path)
    except ValueError:
        return path


class GruppenLinkView(TemplateView):
    template_name = "admin/unterweisung/teilnehmer/gruppen_links.html"
    admin_site = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(self.admin_site.each_context(self.request))
        context["title"] = "Links für Unterführer*innen"

        context["gruppen"] = [
            (("Alle Teilnehmenden", get_gruppen_link(None)))
        ]
        gruppen = models.Teilnehmer.objects.all().values("gruppe").annotate(count=db_models.Count("username")).order_by("gruppe").values_list("gruppe")
        for gruppe, in gruppen:
            prefix, _, suffix = gruppe.partition(" ")
            gruppe_display = suffix if prefix.isnumeric() else gruppe

            context["gruppen"].append((gruppe_display, get_gruppen_link(gruppe)))

        return context


@admin.register(models.Teilnehmer)
class TeilnehmerAdmin(admin.ModelAdmin):
    list_filter = ("gruppe",)

    def get_urls(self):
        urls = super().get_urls()
        urls = [
            path("gruppen_links/",
                 self.admin_site.admin_view(GruppenLinkView.as_view(admin_site=self.admin_site)),
                 name="unterweisung_teilnehmer_gruppen_links"),
        ] + urls
        return urls


class FuehrerscheinInfoView(TemplateView):
    template_name = "admin/unterweisung/fuehrerschein/info.html"
    admin_site = None

    def get_context_data(self, thwin=None, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(self.admin_site.each_context(self.request))
        context["title"] = "Eingegebene Führerscheindaten"

        context["error"] = kwargs.get("error", None)

        context["klassen"] = list(models.Fahrerlaubnis.KLASSEN.keys())

        fuehrerscheine = {}
        abweichungen = []
        for fuehrerschein in models.Fuehrerschein.objects.all():
            thwin_eintrag = thwin.get((fuehrerschein.teilnehmer.surname,
                                       fuehrerschein.teilnehmer.firstname)) if thwin else None
            abweichungen_eintrag = []

            fahrerlaubnisse = [(None, None) for klasse in context["klassen"]]
            for fahrerlaubnis in fuehrerschein.fahrerlaubnisse.all():
                thwin_fahrerlaubnis = (thwin_eintrag["klassen"][fahrerlaubnis.klasse]
                                       if thwin_eintrag else None)
                if thwin_fahrerlaubnis:
                    thwin_gueltig_ab, thwin_gueltig_bis = thwin_fahrerlaubnis
                    if thwin_gueltig_ab < fahrerlaubnis.gueltig_ab:
                        abweichungen_eintrag.append(
                            f"Erteilungsdatum für Klasse {fahrerlaubnis.klasse} in THWin auf "
                            f"{fahrerlaubnis.gueltig_ab:%d.%m.%Y} korrigieren")

                    if thwin_gueltig_bis == fahrerlaubnis.gueltig_bis:
                        pass  # everything is fine
                    elif fahrerlaubnis.gueltig_bis is not None:
                        abweichungen_eintrag.append(
                            f"Gültigkeitsdatum für Klasse {fahrerlaubnis.klasse} in THWin auf "
                            f"{fahrerlaubnis.gueltig_bis:%d.%m.%Y} korrigieren")
                    else:
                        abweichungen_eintrag.append(
                            f"Gültigkeitsdatum für Klasse {fahrerlaubnis.klasse} aus THWin entfernen")

                fahrerlaubnisse[context["klassen"].index(fahrerlaubnis.klasse)] = \
                    (fahrerlaubnis.gueltig_ab, fahrerlaubnis.gueltig_bis)

            for nummer in thwin_eintrag["nummern"] if thwin_eintrag else []:
                if nummer[:10] != fuehrerschein.nummer[:10]:
                    abweichungen_eintrag.append(
                        f"Führerschein-Nummer abweichend: {nummer} != {fuehrerschein.nummer}")

            fuehrerscheine[fuehrerschein.teilnehmer] = (fuehrerschein.nummer, fahrerlaubnisse)
            if abweichungen_eintrag:
                abweichungen.append((fuehrerschein.teilnehmer, abweichungen_eintrag))

        context["fuehrerscheine"] = [
            (teilnehmer, nummer, fahrerlaubnisse)
            for teilnehmer, (nummer, fahrerlaubnisse) in fuehrerscheine.items()]
        context["abweichungen"] = abweichungen

        return context

    def post(self, *args, **kwargs):
        thwin = None
        error = None
        if "thwin_export" in self.request.FILES:
            try:
                export = self._read_thwin_export(self.request.FILES["thwin_export"])
                thwin = {}
                for name, vorname, klasse, nummer, gueltig_ab, gueltig_bis in export:
                    thwin.setdefault(
                        (name, vorname),
                        {"nummern": set(),
                         "klassen": {_klasse: None for _klasse in models.Fahrerlaubnis.KLASSEN}})
                    thwin[(name, vorname)]["nummern"].add(nummer)
                    thwin[(name, vorname)]["klassen"][klasse] = (gueltig_ab, gueltig_bis)

                if not thwin:
                    raise ValueError("Keine Daten für Import gefunden - falschen Export gewählt?")
            except ValueError as exception:
                error = str(exception)
        return self.get(*args, thwin=thwin, error=error, **kwargs)

    def _read_thwin_export(self, file):
        for row in csv.DictReader((line.decode("iso-8859-1")
                                   for line in self.request.FILES["thwin_export"]),
                                  delimiter=";"):
            if not row:
                continue

            if any(field not in row for field in ["Name", "Vorname", "Qualifikation",
                                                  "Nr. / Bem.", "Gültig ab", "Gültig bis"]):
                msg = "Export enthält nicht die benötigten Spalten - wurde der richtige Export gewählt?"
                raise ValueError(msg)

            _, _, klasse = row["Qualifikation"].partition("KFZ-Fahrerlaubnis Klasse ")
            if klasse not in models.Fahrerlaubnis.KLASSEN:
                continue

            gueltig_ab = datetime.strptime(row["Gültig ab"], "%d.%m.%Y").date()
            gueltig_bis = None
            if row["Gültig bis"]:
                gueltig_bis = datetime.strptime(row["Gültig bis"], "%d.%m.%Y").date()
                if gueltig_bis < datetime.now().date():
                    continue

            yield row["Name"], row["Vorname"], klasse, row["Nr. / Bem."], gueltig_ab, gueltig_bis


class FahrerlaubnisInline(admin.StackedInline):
    model = models.Fahrerlaubnis
    extra = 3


@admin.register(models.Fuehrerschein)
class FuehrerscheinAdmin(admin.ModelAdmin):
    inlines = (FahrerlaubnisInline,)

    def get_urls(self):
        urls = super().get_urls()
        urls = [
            path("info/",
                 self.admin_site.admin_view(FuehrerscheinInfoView.as_view(admin_site=self.admin_site)),
                 name="unterweisung_fuehrerschein_info"),
        ] + urls
        return urls
