from django.urls import path, re_path

from . import views, stein_app

app_name = "monitor"
urlpatterns = [
    path("show/<uuid:monitor_uuid>",
         views.InfoMonitorView.as_view()),
    path("data/<uuid:monitor_uuid>",
         views.infomonitor_data,
         name="data"),
    path("hook/stein.app",
         stein_app.view_webhook),
]
