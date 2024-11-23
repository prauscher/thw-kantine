from django.urls import path

from . import views

app_name = "unterweisung"
urlpatterns = [
    path("", views.UnterweisungListView.as_view(), name="start"),
    path("unterweisung/<int:pk>", views.UnterweisungDetailView.as_view(), name="unterweisung_detail"),
    path("seite/<int:pk>", views.SeiteDetailView.as_view(), name="seite_detail"),
    path("export", views.UnterweisungExportView.as_view(), name="export"),
]
