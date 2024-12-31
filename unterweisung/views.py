import os
import time
from django.core.exceptions import ValidationError
from django.views.generic import DetailView, ListView
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from kantine.decorators import require_jwt_login
from . import models


@method_decorator(require_jwt_login, name="dispatch")
class UnterweisungListView(ListView):
    model = models.Unterweisung

    def get_context_data(self, *args, **kwargs):
        username = self.request.jwt_user_id
        unterweisungen = [
            (unterweisung,
             unterweisung.get_teilnahme(username))
            for unterweisung in self.get_queryset()
        ]

        return {**super().get_context_data(*args, **kwargs),
                "unterweisungen": unterweisungen,
                "user_id": self.request.jwt_user_id,
                "user_display": self.request.jwt_user_display}

    def get_queryset(self):
        return super().get_queryset().filter(active=True)


@method_decorator(require_jwt_login, name="dispatch")
class UnterweisungDetailView(DetailView):
    model = models.Unterweisung

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["user_id"] = self.request.jwt_user_id
        context["user_display"] = self.request.jwt_user_display

        teilnahme = self.object.get_teilnahme(self.request.jwt_user_id)
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

        self.request.session.setdefault(f"unterweisung_{self.object.unterweisung.pk}_start",
                                        time.time())

        context["user_id"] = self.request.jwt_user_id
        context["user_display"] = self.request.jwt_user_display
        context["seiten"] = self._get_seiten()
        context["errors"] = self.errors

        context["inhalt"] = mark_safe(self.object.render(self.request))

        return context

    def _check_teilnahme(self, request) -> models.Seite | None:
        current_seite = self.get_object()

        unterweisung_result = []
        prev_seite = None
        redirect_seite = None
        for _, seite_loop, seite_success, seite_result in self._get_seiten():
            # Go to the next "waiting" seite, or the next in line
            # Note that if we hit the last seite, no break will occur
            if redirect_seite is None and (not seite_success or prev_seite == current_seite):
                redirect_seite = seite_loop

            # do not create teilnahme yet
            if not seite_success and seite_loop.is_required:
                break

            if seite_result is not None:
                unterweisung_result.append(seite_result)

            prev_seite = seite_loop
        else:
            # All Seiten are successful and we are at the end!

            start = request.session.get(f"unterweisung_{current_seite.unterweisung.pk}_start")
            duration = None if start is None else time.time() - start

            # store results and redirect to overview
            models.Teilnahme.objects.update_or_create(
                username=request.jwt_user_id,
                unterweisung=current_seite.unterweisung,
                defaults={
                    "fullname": request.jwt_user_display,
                    "abgeschlossen_at": timezone.now(),
                    "duration": duration,
                    "ergebnis": "\n".join(unterweisung_result),
                },
            )

        return redirect_seite

    def post(self, request, *args, **kwargs):
        seite = self.get_object()

        teilnahme = seite.unterweisung.get_teilnahme(request.jwt_user_id)

        data = request.POST.copy()
        redirect_seite = data.pop("_redirect", "next")[0]
        next_seite = None

        try:
            result = seite.parse_result(request, data, teilnahme=teilnahme)
        except ValidationError as error:
            # retry for user, ignore validation errors during explicit page request
            if redirect_seite == "next":
                self.errors = error.messages
                return self.get(request, *args, **kwargs)
        else:
            if result is not None and result.startswith("confirm:"):
                redirect_seite = None
                result = result[8:]
            # store success in session
            self.request.session[f"seite_{seite.pk}"] = (True, result)

        # create Teilnahme object if possible
        next_seite = self._check_teilnahme(request)

        # Decide for next step
        if redirect_seite is None:
            # re-show page for confirmation
            return self.get(request, *args, **kwargs)
        elif redirect_seite == "next":
            # loop back to intro-page if all pages are done, else next_seite
            # already contains correct object
            if next_seite is None:
                return redirect(seite.unterweisung.get_absolute_url() + "?return=1")
        elif redirect_seite.isnumeric():
            try:
                next_seite = self._get_seiten()[int(redirect_seite)][1]
            except IndexError:
                self.errors = ["Ungültiger Redirect-Parameter"]
                return self.get(request, *args, **kwargs)
        else:
            # Unknown _redirect parameter
            self.errors = ["Ungültiger Redirect-Parameter"]
            return self.get(request, *args, **kwargs)

        return redirect(next_seite.get_absolute_url())
