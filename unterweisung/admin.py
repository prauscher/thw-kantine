from django.contrib import admin
from polymorphic.admin import (
    PolymorphicChildModelAdmin,
    PolymorphicInlineSupportMixin,
    PolymorphicParentModelAdmin,
    StackedPolymorphicInline,
)
from markdownx.admin import MarkdownxModelAdmin
from . import models


class MultipleChoiceOptionInline(admin.StackedInline):
    model = models.MultipleChoiceOption
    extra = 4


@admin.register(models.MultipleChoiceFrage)
class MultipleChoiceFrageAdmin(admin.ModelAdmin):
    inlines = (MultipleChoiceOptionInline,)


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
class UnterweisungAdmin(PolymorphicInlineSupportMixin, admin.ModelAdmin):
    inlines = (SeiteInline,)


admin.site.register(models.Teilnahme)
