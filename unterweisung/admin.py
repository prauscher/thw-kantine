from django import forms
from django.contrib import admin, messages
from django.db import models as db_models
from django.urls import path, reverse_lazy
from django.views.generic.edit import FormView
from polymorphic.admin import (
    PolymorphicChildModelAdmin,
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


@admin.register(models.Unterweisung)
class UnterweisungAdmin(PolymorphicInlineSupportMixin, DjangoObjectActions, admin.ModelAdmin):
    inlines = (SeiteInline,)
    change_actions = ["copy_recursive"]

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
    pass
