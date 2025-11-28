import csv
import statistics
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, UTC
from django import forms
from django.contrib import admin, messages
from django.db import models as db_models
from django.shortcuts import redirect
from django.urls import path, reverse, reverse_lazy
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.generic import FormView, TemplateView
from polymorphic.admin import (
    PolymorphicInlineSupportMixin,
    PolymorphicParentModelAdmin,
    StackedPolymorphicInline,
)
from django_object_actions import DjangoObjectActions, action
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


class MultipleChoiceFragenWidget(forms.Widget):
    template_name = "admin/unterweisung/multiplechoicefrage/widget.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)

        context["markdownx_attrs"] = " ".join(
            f'{k}={v}'
            for k, v in MarkdownxWidget.add_markdownx_attrs({}).items()
        )

        context["fragen"] = []
        for i, (frage_pk, frage_data, antworten) in enumerate(value or []):
            context["fragen"].append({
                "num": i,
                "sort": (i + 1) * 10,
                "pk": frage_pk,
                **frage_data,
                "antworten": [{"num": i, "pk": antwort_pk, **antwort_data}
                              for i, (antwort_pk, antwort_data) in enumerate(antworten)],
            })

        # add empty and template frage
        context["fragen"].append({"num": len(context["fragen"]), "sort": (len(context["fragen"]) + 1) * 10, "antworten": []})
        context["fragen_count"] = len(context["fragen"])
        context["fragen"].append({"num": "__frage_template__", "antworten": []})

        # add empty and template antworten
        for i in range(len(context["fragen"])):
            context["fragen"][i]["antworten"].append({"num": len(context["fragen"][i]["antworten"])})
            context["fragen"][i]["antworten_count"] = len(context["fragen"][i]["antworten"])
            context["fragen"][i]["antworten"].append({"num": "__antwort_template__"})

        return context

    def _read_fragen(self, data, prefix):
        for i in range(int(data.get(f"{prefix}_count", "0"))):
            yield from self._read_frage(data, f"{prefix}_{i}")

    def _read_frage(self, data, prefix):
        pk = data.get(f"{prefix}_pk")
        text = data.get(f"{prefix}_text", "")
        optional = f"{prefix}_optional" in data
        sort = int(data.get(f"{prefix}_sort", "0"))

        if not text.strip():
            return

        yield (sort,
               int(pk) if pk else None,
               {"text": text, "optional": optional},
               list(self._read_antworten(data, prefix)))

    def _read_antworten(self, data, prefix):
        for i in range(int(data.get(f"{prefix}_count", "0"))):
            yield from self._read_antwort(data, f"{prefix}_{i}")

    def _read_antwort(self, data, prefix):
        pk = data.get(f"{prefix}_pk")
        text = data.get(f"{prefix}_text", "")
        richtig = f"{prefix}_richtig" in data

        if not text.strip():
            return

        yield (int(pk) if pk else None,
               {"text": text, "richtig": richtig})

    def value_from_datadict(self, data, files, name):
        return [(frage_pk, frage_data, antworten)
                for _, frage_pk, frage_data, antworten in sorted(self._read_fragen(data, name))]

    class Media:
        js = [
            "unterweisung/multiplechoicefrage_widget.js",
        ]


class MultipleChoiceInlineForm(forms.ModelForm):
    fragen = forms.Field(
        widget=MultipleChoiceFragenWidget(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "instance" in kwargs:
            self.initial["fragen"] = [
                (frage.pk,
                 {"text": frage.text, "optional": frage.optional},
                 [(antwort.pk, {"text": antwort.text, "richtig": antwort.richtig})
                  for antwort in frage.antworten.all()])
                for frage in kwargs["instance"].fragen.all()]

    def save(self, commit=True):
        instance = super().save(commit=commit)

        # store fragen
        if commit:
            old_fragen_pks = {frage.pk for frage in instance.fragen.all()}
            for i, (frage_pk, frage_data, antworten) in enumerate(self.cleaned_data["fragen"]):
                old_fragen_pks.discard(frage_pk)
                frage_data["sort"] = i

                # create new
                if frage_pk is None:
                    frage = instance.fragen.create(**frage_data)
                else:
                    queryset = instance.fragen.filter(pk=frage_pk)
                    queryset.update(**frage_data)
                    frage = queryset.get()

                old_antworten_pks = {antwort.pk for antwort in frage.antworten.all()}
                for antwort_pk, antwort_data in antworten:
                    old_antworten_pks.discard(antwort_pk)

                    if antwort_pk is None:
                        frage.antworten.create(**antwort_data)
                    else:
                        frage.antworten.filter(pk=antwort_pk).update(**antwort_data)

                for antwort_pk in old_antworten_pks:
                    frage.antworten.get(pk=antwort_pk).delete()

            # delete old
            for frage_pk in old_fragen_pks:
                instance.fragen.get(pk=frage_pk).delete()

        return instance


class SeiteInline(StackedPolymorphicInline):
    class FuehrerscheinDatenInline(StackedPolymorphicInline.Child):
        model = models.FuehrerscheinDatenSeite

    class InfoInline(StackedPolymorphicInline.Child):
        model = models.InfoSeite

    class HermineNachrichtInline(StackedPolymorphicInline.Child):
        model = models.HermineNachrichtSeite

    class MultipleChoiceInline(StackedPolymorphicInline.Child):
        model = models.MultipleChoiceSeite
        form = MultipleChoiceInlineForm

    model = models.Seite
    child_inlines = (FuehrerscheinDatenInline,
                     InfoInline,
                     HermineNachrichtInline,
                     MultipleChoiceInline)


class UnterweisungExportView(TemplateView):
    template_name = "admin/unterweisung/unterweisung/export.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if "unterweisung" in self.request.GET:
            unterweisung_filter = {"pk__in": self.request.GET["unterweisung"].split(",")}
        else:
            unterweisung_filter = {"active": True}

        context["unterweisungen"] = [
            (unterweisung,
             [(nr, seite, mark_safe(seite.render(self.request, export=True)))
              for nr, seite in enumerate(unterweisung.seiten.all(), 1)])
            for unterweisung in models.Unterweisung.objects.filter(**unterweisung_filter)]

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
    change_actions = ["goto_export", "copy_recursive"]
    changelist_actions = ["goto_export_list"]
    # change_{list,form}_template are overwritten by DjangoObjectActions, so need to specify default here
    change_form_template = "admin/unterweisung/unterweisung/change_form.html"

    @action(label="Export",
            description="Zeige Unterweisungen für Ausdruck an.")
    def goto_export_list(self, request, queryset):
        return redirect(reverse("admin:unterweisung_unterweisung_export"))

    @action(label="Export",
            description="Zeige diese Unterweisung einzeln an.")
    def goto_export(self, request, obj):
        return redirect(reverse("admin:unterweisung_unterweisung_export") +
                        f"?unterweisung={obj.pk}")

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

    # style up markdownx inputs
    class Media:
        css = {
            "all": [
                "unterweisung/markdownx-input.css",
            ]
        }


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
        context["abgleich"] = thwin is not None

        fuehrerscheine = {}
        for fuehrerschein in models.Fuehrerschein.objects.all():
            thwin_eintrag = thwin.get((fuehrerschein.teilnehmer.surname,
                                       fuehrerschein.teilnehmer.firstname)) if thwin else None
            thwin_klassen = thwin_eintrag["klassen"] if thwin_eintrag else None

            # initially mark all klassen written in thwin as error - valid ones will be overwritten
            # soon
            fahrerlaubnisse = [
                (None,
                 thwin_klassen[klasse][0] is not None if thwin_klassen else False,
                 None,
                 thwin_klassen[klasse][0] is not None if thwin_klassen else False,
                 ) for klasse in context["klassen"]]

            for fahrerlaubnis in fuehrerschein.fahrerlaubnisse.all():
                thwin_gueltig_ab, thwin_gueltig_bis = (
                    thwin_klassen[fahrerlaubnis.klasse]
                    if thwin_klassen else (None, None))

                fahrerlaubnisse[context["klassen"].index(fahrerlaubnis.klasse)] = (
                    fahrerlaubnis.gueltig_ab,
                    # mark as error if klasse is not in thwin or thwin has early date
                    # note that late dates are possible as thwin only accepts 01.01.2000 onwards
                    thwin and (thwin_gueltig_ab is None or thwin_gueltig_ab < fahrerlaubnis.gueltig_ab),
                    fahrerlaubnis.gueltig_bis,
                    # any deviation from gueltig_bis shall be marked as an error
                    thwin and (thwin_gueltig_bis != fahrerlaubnis.gueltig_bis))

            fuehrerscheine[fuehrerschein.teilnehmer] = (
                fuehrerschein.nummer,
                any(nummer[:10] != fuehrerschein.nummer[:10]
                    for nummer in (thwin_eintrag["nummern"] if thwin_eintrag else [])),
                fahrerlaubnisse)

        context["fuehrerscheine"] = [
            (teilnehmer, nummer, nummer_error, fahrerlaubnisse)
            for teilnehmer, (nummer, nummer_error, fahrerlaubnisse) in fuehrerscheine.items()]

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
                         "klassen": {_klasse: (None, None)
                                     for _klasse in models.Fahrerlaubnis.KLASSEN}})
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
