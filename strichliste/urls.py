from django.urls import path

from . import views

# Diese Seiten gibt es für Nextcloud-Benutzer und als Tablet-Variante unter tablet/<token>/
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
    path("verwaltung/", views.admin_accounts, name="admin_konten"),
    path("verwaltung/konto/<int:pk>/verknuepfen", views.admin_link, name="admin_verknuepfen"),
    path("verwaltung/konto/<int:pk>/aktion", views.admin_account_action, name="admin_konto_aktion"),
    path("verwaltung/buttons", views.admin_buttons, name="admin_buttons"),
    path("verwaltung/tags", views.admin_tags, name="admin_tags"),
    path("verwaltung/einstellungen", views.admin_config, name="admin_einstellungen"),
    path("verwaltung/tablets", views.admin_tablets, name="admin_tablets"),
    path("tablet/<str:token>/", views.start, name="tablet_start"),
    path("tablet/<str:token>/pin", views.tablet_pin, name="tablet_pin"),
    *(path(route, view, name=name) for route, view, name in SHARED),
    *(path(f"tablet/<str:token>/{route}", view, name=f"tablet_{name}") for route, view, name in SHARED),
]
