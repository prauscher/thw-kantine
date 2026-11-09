from django.contrib import admin
from . import models


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "username", "balance", "last_booking_at", "disabled")
    list_filter = ("disabled", "tags")
    search_fields = ("name", "username")
    # Saldo nur über Buchungen ändern, sonst stimmt er nicht mehr mit den Transaktionen überein
    readonly_fields = ("balance", "last_booking_at", "legacy_id")


@admin.register(models.Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "account", "amount", "label", "booked_by_name", "reverted_at")
    list_filter = ("kind", "via_tablet")
    search_fields = ("account__name", "label", "booked_by_name")

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(models.DispenseButton)
admin.site.register(models.Tag)
