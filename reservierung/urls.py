from django.urls import path, re_path

from . import views

app_name = "reservierung"
urlpatterns = [
    path("",
         views.UebersichtView.as_view(),
         name="start"),

    path("usages.json",
         views.fetch_usages,
         name="usages_json"),

    path("resource",
         views.ResourceListView.as_view(),
         name="resource_list"),
    path("resource/<slug:slug>",
         views.ResourceDetailView.as_view(),
         name="resource_detail"),

    path("calendar",
         views.CalendarView.as_view(),
         name="calendar"),

    path("create",
         views.TerminFormView.as_view(),
         name="termin_create"),

    path("all",
         views.AllTerminListView.as_view(),
         name="termin_list"),

    path("termin/<int:pk>_<str:date>_<str:slug>",
         views.TerminDetailView.as_view(),
         name="termin_detail"),
    path("termin/<int:pk>_<str:date>_<str:slug>/edit",
         views.TerminFormView.as_view(),
         name="termin_edit"),
    path("termin/<int:pk>_<str:date>_<str:slug>/delete",
         views.TerminDeleteView.as_view(),
         name="termin_delete"),
    path("termin/<int:termin_id>_<str:termin_date>_<str:termin_slug>/_/<slug:resource_slug>",
         views.ResourceUsageDetailView.as_view(),
         name="resourceusage_detail"),
    path("termin/<int:termin_id>_<str:termin_date>_<str:termin_slug>/_/<slug:resource_slug>/vote",
         views.ResourceUsageVoteView.as_view(),
         name="resourceusage_vote"),
    path("termin/<int:termin_id>_<str:termin_date>_<str:termin_slug>/_/<slug:resource_slug>/revoke_vote",
         views.ResourceUsageRevokeVoteView.as_view(),
         name="resourceusage_vote_revoke"),
    path("termin/<int:termin_id>_<str:termin_date>_<str:termin_slug>/_/<slug:resource_slug>/reject",
         views.ResourceUsageRejectView.as_view(),
         name="resourceusage_reject"),
    path("termin/<int:termin_id>_<str:termin_date>_<str:termin_slug>/_/<slug:resource_slug>/revert_reject",
         views.ResourceUsageRevertRejectView.as_view(),
         name="resourceusage_reject_revert"),
]
