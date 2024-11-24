from collections import defaultdict
from django import forms
from django.contrib import admin, messages
from django.db import models as db_models
from django.urls import path, reverse_lazy
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

    class MultipleChoiceInline(StackedPolymorphicInline.Child):
        model = models.MultipleChoiceSeite

    model = models.Seite
    child_inlines = (FuehrerscheinDatenInline,
                     InfoInline,
                     MultipleChoiceInline)


class UnterweisungExportView(TemplateView):
    template_name = "unterweisung/export_unterweisungen.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["unterweisungen"] = [
            (unterweisung,
             [(nr, seite, mark_safe(seite.render(self.request, export=True)))
              for nr, seite in enumerate(unterweisung.seiten.all(), 1)])
            for unterweisung in models.Unterweisung.objects.filter(active=True)]

        return context


class UnterweisungExportTeilnahmeView(TemplateView):
    template_name = "unterweisung/export_teilnahme.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        unterweisungen = list(models.Unterweisung.objects.filter(active=True))
        personen = defaultdict(lambda: {"namen": set(),
                                        "teilnahmen": [(unterweisung, None)
                                                       for unterweisung in unterweisungen]})

        for teilnahme in models.Teilnahme.objects.filter(unterweisung__in=unterweisungen):
            if teilnahme.fullname:
                personen[teilnahme.username]["namen"].add(teilnahme.fullname)

            unterweisung_index = unterweisungen.index(teilnahme.unterweisung)
            personen[teilnahme.username]["teilnahmen"][unterweisung_index] = (
                teilnahme.unterweisung,
                False if teilnahme.abgeschlossen_at is None else teilnahme.ergebnis)

        context["unterweisungen"] = unterweisungen
        context["personen"] = personen.items()

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
        i = 1
        while models.Unterweisung.objects.filter(label=obj.label).count() > 0:
            i += 1
            obj.label = f"Kopie({i}) von {orig_label}"
        obj.save()

        for seite in seiten:
            seite = seite.clone()
            seite.unterweisung = obj
            seite.save()
            print(obj.pk, seite.pk)

    def get_urls(self):
        urls = super().get_urls()
        urls = [
            path("export/unterweisung",
                 self.admin_site.admin_view(UnterweisungExportView.as_view()),
                 name="unterweisung_export"),
            path("export/teilnahme",
                 self.admin_site.admin_view(UnterweisungExportTeilnahmeView.as_view()),
                 name="unterweisung_teilnahme_export"),
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
            models.Teilnahme.objects.create(
                unterweisung=unterweisung,
                username=username,
                abgeschlossen_at=None,
            )
            created += 1

        self.model_admin.message_user(
            self.request,
            f"Teilnahme für {created} Benutzer*innen vorgemerkt.",
            messages.SUCCESS,
        )

        return super().form_valid(form)


@admin.register(models.Teilnahme)
class TeilnahmeAdmin(admin.ModelAdmin):
    def get_urls(self):
        urls = super().get_urls()
        urls = [
            path("import/",
                 self.admin_site.admin_view(ImportTeilnahmeView.as_view(model_admin=self)),
                 name="unterweisung_teilnahme_import"),
        ] + urls
        return urls
