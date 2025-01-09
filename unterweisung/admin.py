import statistics
from collections import defaultdict
from contextlib import suppress
from datetime import datetime
from django import forms
from django.contrib import admin, messages
from django.db import models as db_models
from django.urls import path, reverse_lazy
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
from . import models


class MultipleChoiceOptionInline(admin.StackedInline):
    model = models.MultipleChoiceOption
    extra = 3

    formfield_overrides = {
        db_models.TextField: {'widget': forms.Textarea(attrs={"rows": 1, "cols": 60})},
    }


@admin.register(models.MultipleChoiceFrage)
class MultipleChoiceFrageAdmin(admin.ModelAdmin):
    inlines = (MultipleChoiceOptionInline,)

    formfield_overrides = {
        db_models.TextField: {'widget': forms.Textarea(attrs={"rows": 2, "cols": 60})},
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
                     "teilnahmen": [(unterweisung, None, None)
                                    for unterweisung in unterweisungen]})

        for teilnahme in models.Teilnahme.objects.filter(unterweisung__in=unterweisungen):
            personen_teilnahmen[teilnahme.teilnehmer]["last_abgeschlossen"] = max(
                filter(lambda i: i is not None,
                       [personen_teilnahmen[teilnahme.teilnehmer]["last_abgeschlossen"],
                        teilnahme.abgeschlossen_at]),
                default=None)

            unterweisung_index = unterweisungen.index(teilnahme.unterweisung)

            personen_teilnahmen[teilnahme.teilnehmer]["teilnahmen"][unterweisung_index] = (
                teilnahme.unterweisung,
                False if teilnahme.abgeschlossen_at is None else teilnahme.ergebnis,
                teilnahme.duration)

        personen_output = personen_teilnahmen.items()

        if "gruppe" in self.request.GET:
            personen_output = filter(lambda item: item[0].gruppe == self.request.GET["gruppe"],
                                     personen_output)

        if "only_open" in self.request.GET:
            # ergebnis can be
            # - None (no Teilnahme-object)
            # - False (incomplete Teilnahme-object)
            # - a str (complete Teilnahme-object)
            # We only want rows where at least one Teilnahme-object is incomplete
            personen_output = filter(lambda item: any(ergebnis is False
                                                      for _, ergebnis, _ in item[1]["teilnahmen"]),
                                     personen_output)

        with suppress(ValueError):
            filter_after = timezone.make_aware(
                datetime.strptime(self.request.GET.get("after", ""), "%Y-%m-%d"))
            personen_output = filter(lambda item: item[1]["last_abgeschlossen"] is not None and
                                                  item[1]["last_abgeschlossen"] >= filter_after,
                                     personen_output)

        personen_output = sorted(
            personen_output,
            key=lambda item: (1, item[0].fullname) if item[0].fullname else (2, item[0].username))

        gruppen_output = defaultdict(list)
        for teilnehmer, data in personen_output:
            gruppen_output[teilnehmer.gruppe].append((teilnehmer, data))

        context["unterweisungen"] = unterweisungen

        teilnahmen_open = 0
        teilnahmen_done = 0

        durations_combined = [[] for _ in unterweisungen]

        gruppen = []
        for gruppe, personen in gruppen_output.items():
            quantiles = None

            if "include_stats" in self.request.GET:
                quantiles = []

                for i, unterweisung in enumerate(unterweisungen):
                    durations = []
                    for teilnehmer, data in personen:
                        if data["teilnahmen"][i][2] is not None:
                            durations.append(data["teilnahmen"][i][2])
                            durations_combined[i].append(data["teilnahmen"][i][2])

                        if data["teilnahmen"][i][1] is False:
                            teilnahmen_open += 1
                        else:
                            teilnahmen_done += 1

                    if len(durations) == 1:
                        # avoid StatisticsWarning
                        durations.append(durations[0])

                    if durations:
                        _quantiles = statistics.quantiles(durations, n=2)
                        quantiles.append({"median": _quantiles[0]})
                    else:
                        quantiles.append(None)

                context["teilnahmen_total"] = teilnahmen_open + teilnahmen_done

            gruppen.append((gruppe, personen, quantiles))

        context["gruppen"] = sorted(gruppen, key=lambda item: item[0])

        if "include_stats" in self.request.GET:
            context["teilnahmen_open"] = teilnahmen_open
            context["teilnahmen_done"] = teilnahmen_done

            quantiles = []
            for i, _ in enumerate(unterweisungen):
                if len(durations_combined[i]) == 1:
                    durations_combined[i].append(durations_combined[i][0])

                if durations_combined:
                    _quantiles = statistics.quantiles(durations_combined[i])
                    quantiles.append({"median": _quantiles[0]})
                else:
                    quantiles.append(None)

            context["total_quantiles"] = quantiles

        return context


@admin.register(models.Unterweisung)
class UnterweisungAdmin(PolymorphicInlineSupportMixin, DjangoObjectActions, admin.ModelAdmin):
    inlines = (SeiteInline,)
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


@admin.register(models.Teilnehmer)
class TeilnehmerAdmin(admin.ModelAdmin):
    list_filter = ("gruppe",)
