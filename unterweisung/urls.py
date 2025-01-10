from django.urls import path, re_path

from . import views

app_name = "unterweisung"
urlpatterns = [
    path("",
         views.UnterweisungListView.as_view(),
         name="start"),
    path("unterweisung/<int:pk>",
         views.UnterweisungDetailView.as_view(),
         name="unterweisung_detail"),
    path("seite/<int:pk>",
         views.SeiteDetailView.as_view(),
         name="seite_detail"),
    re_path(r'^gruppe/(?P<token>[a-zA-Z0-9\+/]+={0,3})$',
         views.GruppenUebersichtView.as_view(),
         name="ansicht_gruppe"),
]
