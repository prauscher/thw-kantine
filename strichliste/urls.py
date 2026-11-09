from django.urls import path

from . import views

app_name = "strichliste"
urlpatterns = [
    path("paypal",
         views.PaypalView.as_view(),
         name="paypal"),

    # Nextcloud-Login, gebucht wird immer auf das eigene Konto
    path("",
         views.StartView.as_view(),
         name="start"),
    path("assign",
         views.AssignUserView.as_view(),
         name="assign_user"),
    path("anlegen",
         views.CreateUserView.as_view(),
         name="create_user"),
    path("ausgabe",
         views.OwnSpendView.as_view(),
         name="spend"),
    path("ueberweisen",
         views.OwnTransferView.as_view(),
         name="transfer"),
    path("buchung/<int:tx>/storno",
         views.OwnRevertView.as_view(),
         name="revert"),

    # Theken-Tablet
    path("tablet/<str:pin>/",
         views.TabletAccountListView.as_view(),
         name="tablet_accounts"),
    path("tablet/<str:pin>/extern",
         views.TabletCreateExternView.as_view(),
         name="tablet_create_extern"),
    path("tablet/<str:pin>/konto/<int:pk>",
         views.TabletAccountView.as_view(),
         name="tablet_account"),
    path("tablet/<str:pin>/konto/<int:pk>/einzahlen",
         views.TabletCreditView.as_view(),
         name="tablet_credit"),
    path("tablet/<str:pin>/konto/<int:pk>/ausgabe",
         views.TabletSpendView.as_view(),
         name="tablet_spend"),
    path("tablet/<str:pin>/konto/<int:pk>/ueberweisen",
         views.TabletTransferView.as_view(),
         name="tablet_transfer"),
    path("tablet/<str:pin>/konto/<int:pk>/buchung/<int:tx>/storno",
         views.TabletRevertView.as_view(),
         name="tablet_revert"),
]
