import os
from collections import defaultdict
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.views.generic import DetailView, ListView, TemplateView
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from kantine.decorators import require_jwt_login
from kantine.hermine import get_hermine_client
from . import models


@method_decorator(require_jwt_login, name="dispatch")
class UnterweisungListView(ListView):
    model = models.Unterweisung

    def get_context_data(self, *args, **kwargs):
        username = _get_userdata(self.request)["uid"]
        unterweisungen = [
            (unterweisung,
             unterweisung.get_teilnahme(username))
            for unterweisung in self.get_queryset()
        ]

        return {**super().get_context_data(*args, **kwargs),
                "unterweisungen": unterweisungen,
                "userdata": _get_userdata(self.request)}

    def get_queryset(self):
        return super().get_queryset().filter(active=True)


@method_decorator(require_jwt_login, name="dispatch")
class UnterweisungDetailView(DetailView):
    model = models.Unterweisung

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        userdata = _get_userdata(self.request)
        context["userdata"] = userdata
        context["teilnahme"] = self.object.get_teilnahme(userdata["uid"])
        if self.object.seiten.count() > 0:
            context["erste_seite"] = self.object.seiten.all()[0]

        return context


@method_decorator(require_jwt_login, name="dispatch")
class SeiteDetailView(DetailView):
    model = models.Seite
    template_name = "unterweisung/seite_detail.html"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errors = None

    def _get_seiten(self) -> list[tuple[int, models.Seite, bool, bool]]:
        return [
            (i + 1,
             seite,
             *self.request.session.get(f"seite_{seite.pk}", (False, None)))  # done, comment
            for i, seite in enumerate(self.get_object().unterweisung.seiten.all())
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        userdata = _get_userdata(self.request)
        context["userdata"] = userdata
        context["seiten"] = self._get_seiten()
        context["errors"] = self.errors

        seite_template_name, seite_context = self.object.get_template_context(self.request)
        context["inhalt"] = mark_safe(render_to_string(seite_template_name, seite_context))

        return context

    def post(self, request, *args, **kwargs):
        userdata = _get_userdata(request)
        seite = self.get_object()

        data = request.POST.copy()
        redirect_seite = data.pop("_redirect", "next")[0]

        try:
            result = seite.parse_result(data)
        except ValidationError as error:
            # retry for user
            if redirect_seite == "next":
                self.errors = error.messages
                return self.get(request, *args, **kwargs)
        else:
            # store success in session
            self.request.session[f"seite_{seite.pk}"] = (True, result)

        seiten = self._get_seiten()

        if redirect_seite == "next":
            unterweisung_result = []
            prev_seite = None
            for i, (_, seite_loop, seite_success, seite_result) in enumerate(seiten):
                # Go to the next "waiting" seite, or the next in line
                # Note that if we hit the last seite, no break will occur
                if not seite_success or prev_seite == seite:
                    redirect_seite = str(i)
                    break

                if seite_result is not None:
                    unterweisung_result.append(seite_result)

                prev_seite = seite_loop
            else:
                # All Seiten are successful and we are at the end!
                # store results and redirect to overview
                models.Teilnahme.objects.update_or_create(
                    username=userdata["uid"],
                    unterweisung=seite.unterweisung,
                    defaults={
                        "fullname": userdata["displayName"],
                        "abgeschlossen_at": timezone.now(),
                        "ergebnis": "\n".join(unterweisung_result),
                    },
                )
                return redirect(seite.unterweisung.get_absolute_url())

        # go to explicitly asked seite
        if redirect_seite.isnumeric():
            seite = self._get_seiten()[int(redirect_seite)][1]
            return redirect(seite.get_absolute_url())

        else:
            # Unknown _redirect parameter
            self.errors = ["Ungültiger Redirect-Parameter"]
            return self.get(request, *args, **kwargs)


@method_decorator(require_jwt_login, name="dispatch")
class UnterweisungExportView(TemplateView):
    template_name = "unterweisung/export.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        unterweisungen = list(models.Unterweisung.objects.filter(active=True))
        personen = defaultdict(lambda: {"namen": set(),
                                        "teilnahmen": [(unterweisung, None)
                                                       for unterweisung in unterweisungen]})

        for teilnahme in models.Teilnahme.objects.filter(unterweisung__in=unterweisungen):
            if teilnahme.fullname:
                personen[teilnahme.username]["namen"].add(teilnahme.fullname)

            unterweisung_index = unterweisungen.index(teilnahme.unterweisung)
            personen[teilnahme.username]["teilnahmen"][unterweisung_index] = (
                teilnahme.unterweisung,
                False if teilnahme.abgeschlossen_at is None else teilnahme.ergebnis)

        context["unterweisungen"] = unterweisungen
        context["personen"] = personen.items()

        return context


def _get_userdata(request):
    userdata = request.session.get("jwt_userdata", {})
    return userdata
