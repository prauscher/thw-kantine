import os
from django.core.exceptions import ValidationError
from django.views.generic import DetailView, ListView
from django.shortcuts import redirect
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

        teilnahme = self.object.get_teilnahme(userdata["uid"])
        context["teilnahme"] = teilnahme

        if self.object.seiten.count() > 0:
            context["erste_seite"] = self.object.seiten.all()[0]

        context["return"] = (
            (self.request.GET.get("return", None) is not None) and
            teilnahme is not None and
            teilnahme.abgeschlossen_at is not None)

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

        context["inhalt"] = mark_safe(self.object.render(self.request))

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
                return redirect(seite.unterweisung.get_absolute_url() + "?return=1")

        # go to explicitly asked seite
        if redirect_seite.isnumeric():
            seite = self._get_seiten()[int(redirect_seite)][1]
            return redirect(seite.get_absolute_url())

        else:
            # Unknown _redirect parameter
            self.errors = ["Ungültiger Redirect-Parameter"]
            return self.get(request, *args, **kwargs)


def _get_userdata(request):
    userdata = request.session.get("jwt_userdata", {})
    return userdata
