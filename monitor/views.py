from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.generic import TemplateView

from .monitor import query_infomonitor


MONITORS = {
    "e1d2c073-1833-4cd0-9c72-0222b122bac9": ("monitor/infomonitor.html", query_infomonitor),
}


class InfoMonitorView(TemplateView):
    def get_template_names(self):
        try:
            template_name, _ = MONITORS[str(self.kwargs.get("monitor_uuid"))]
            return [template_name]
        except KeyError as error:
            raise Http404 from error

    def get_context_data(self, monitor_uuid):
        context = super().get_context_data()
        context["data_url"] = reverse("monitor:data", args=(monitor_uuid,))
        return context


def infomonitor_data(request, monitor_uuid):
    try:
        _, datasource = MONITORS[str(monitor_uuid)]
    except KeyError as error:
        raise Http404 from error

    return JsonResponse(datasource())
