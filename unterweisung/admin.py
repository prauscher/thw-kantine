from django import forms
from django.contrib import admin
from django.db import models as db_models
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
    min_num = 4
    extra = 1

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


admin.site.register(models.Teilnahme)
