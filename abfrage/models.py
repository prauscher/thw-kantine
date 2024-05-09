from django.db import models


class Menu(models.Model):
    label = models.CharField(max_length=100)
    owner = models.CharField(max_length=50)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.label} von {self.owner}"


class Serving(models.Model):
    menu = models.ForeignKey("Menu", on_delete=models.CASCADE, related_name="servings")
    label = models.CharField(max_length=200)
    icon = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.menu}: {self.label}"


class Reservation(models.Model):
    customer = models.CharField(max_length=70)
    serving = models.ForeignKey("Serving", on_delete=models.CASCADE)
    count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.serving}: {self.count}x {self.customer}"
