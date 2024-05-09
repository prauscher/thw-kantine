from django.urls import path

from . import views

app_name = "abfrage"
urlpatterns = [
    path("", views.start, name="start"),
]
