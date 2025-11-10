from django.contrib import admin

from . import models
from .templatetags.timerange import timerange_filter


@admin.register(models.User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "surname", "firstname")


class ResourceUsageInline(admin.StackedInline):
    model = models.ResourceUsage
    readonly_fields = ("created_at",)
    fields = ("approved_at", "rejected_at", "rejected_by")


@admin.register(models.Termin)
class TerminAdmin(admin.ModelAdmin):
    list_display = ("timerange", "label", "owner")
    inlines = (ResourceUsageInline,)

    @admin.display(description="Zeitraum", ordering="start")
    def timerange(self, obj):
        return timerange_filter(obj.start, obj.end)


class ResourceManagerInline(admin.TabularInline):
    model = models.ResourceManager
    fields = ("funktion", "voting_group", "admin")
    ordering = ("voting_group",)


@admin.register(models.Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("label",)
    list_filter = ("selectable",)
    prepopulated_fields = {"slug": ("label",)}
    inlines = (ResourceManagerInline,)


@admin.register(models.Funktion)
class FunktionAdmin(admin.ModelAdmin):
    pass
