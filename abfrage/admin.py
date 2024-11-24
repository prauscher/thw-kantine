from django.contrib import admin
from . import models


class ServingInline(admin.StackedInline):
    model = models.Serving
    min_num = 3
    extra = 1


@admin.register(models.Menu)
class MenuAdmin(admin.ModelAdmin):
    inlines = (ServingInline,)


admin.site.register(models.Reservation)
