from django import forms
from django.db import models
from django.urls import reverse


class Menu(models.Model):
    label = models.CharField(
        max_length=100,
        verbose_name="Bezeichnung",
        help_text="Eindeutiger Name des Essensmenüs, z.B. \"Dienst 7. Mai 2024\"")
    owner = models.CharField(max_length=50)
    closed_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Anmeldeschluss",
        help_text="Zeitpunkt bis zu dem Anmeldungen entgegen genommen werden. Kann leer gelassen werden, wenn die Anmeldung später von Hand geschlossen werden soll.")

    def __str__(self):
        return f"{self.label} von {self.owner}"

    def get_absolute_url(self):
        return reverse("abfrage:menu_detail", kwargs={"pk": self.pk})


class Serving(models.Model):
    ICONS = [
        ("beef", "Rind"),
        ("pork", "Schwein"),
        ("chicken", "Hähnchen"),
        ("piscine", "Fisch"),
        ("vegetarian", "Vegetarisch"),
        ("vegan", "Vegan"),
    ]

    menu = models.ForeignKey("Menu", on_delete=models.CASCADE, related_name="servings")
    label = models.CharField(max_length=200)
    icon = models.CharField(max_length=20, choices=ICONS)

    def __str__(self):
        return f"{self.menu}: {self.label}"


class Reservation(models.Model):
    customer_uid = models.CharField(max_length=50)
    customer = models.CharField(max_length=70)
    serving = models.ForeignKey("Serving", on_delete=models.CASCADE)
    count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    served_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.serving}: {self.count}x {self.customer}"
