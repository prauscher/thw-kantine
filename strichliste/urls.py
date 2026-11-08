from django.urls import path

from . import views

# Diese Seiten gibt es für Nextcloud-Benutzer und als Tablet-Variante unter tablet/<pin>/
SHARED = [
    ("konten", views.accounts, "konten"),
    ("konto/<int:pk>", views.account_detail, "konto"),
    ("konto/<int:pk>/ueberweisen", views.transfer, "ueberweisen"),
    ("buchung/<int:pk>/storno", views.revert, "storno"),
    ("extern/neu", views.extern_form, "extern_neu"),
    ("extern/<int:pk>", views.extern_form, "extern_bearbeiten"),
]

app_name = "strichliste"
urlpatterns = [
    path("", views.start, name="start"),
    path("paypal", views.paypal, name="paypal"),
    path("tablet/<str:pin>/", views.start, name="tablet_start"),
    *(path(route, view, name=name) for route, view, name in SHARED),
    *(path(f"tablet/<str:pin>/{route}", view, name=f"tablet_{name}") for route, view, name in SHARED),
]
