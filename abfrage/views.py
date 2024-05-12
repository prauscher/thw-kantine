from collections import defaultdict
from urllib.parse import urlencode
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect
from django.views.generic import ListView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView, UpdateView
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from kantine.decorators import require_jwt_login
from . import models


@method_decorator(require_jwt_login, name="dispatch")
class MenuListView(ListView):
    model = models.Menu

    def get_context_data(self, *args, **kwargs):
        return {**super().get_context_data(*args, **kwargs),
                "userdata": _get_userdata(self.request)}

    def get(self, *args, **kwargs):
        count = self.get_queryset().count()

        if count == 1:
            return redirect(self.get_queryset().get().get_absolute_url() + "?redirected=1")

        if count == 0:
            closed_at = timezone.now()
            # Go to next tuesday
            closed_at += timezone.timedelta(days=(1 - closed_at.weekday()) % 7)
            # use specific time of day
            closed_at = closed_at.replace(hour=10, minute=0)
            return redirect(reverse('abfrage:menu_create') + "?" + urlencode({
                "closed_at": closed_at.strftime("%Y-%m-%dT%H:%M"),
                "label": f"Dienst am {closed_at:%d.%m.%Y}, Essensausgabe ab 18:00 Uhr"}))

        return super().get(*args, **kwargs)

    def get_queryset(self):
        return super().get_queryset().filter(Q(closed_at__isnull=True) | Q(closed_at__gte=timezone.now() - timezone.timedelta(days=2)))


class MenuModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["closed_at"].widget.input_type = "datetime-local"
        self.fields["closed_at"].widget.format = "%Y-%m-%dT%H:%M"

    def process_servings(self, post_data):
        servings = defaultdict(dict)
        for field, value in post_data.items():
            if field.startswith("serving-") and "-" in field[8:]:
                serving_no, _, option = field[8:].partition("-")
                servings[serving_no][option] = value

        for serving_id, serving_data in servings.items():
            if serving_id.startswith("new"):
                if not serving_data.get("label"):
                    continue

                models.Serving.objects.create(
                    menu=self.instance, icon=serving_data.get("icon"), label=serving_data.get("label")
                )
            else:
                serving = self.instance.servings.get(pk=int(serving_id))
                if not serving_data.get("label"):
                    serving.delete()
                    continue

                serving.icon = serving_data.get("icon")
                serving.label = serving_data.get("label")
                serving.save()

    class Meta:
        model = models.Menu
        fields = ["label", "closed_at"]


@method_decorator(require_jwt_login, name="dispatch")
class MenuCreateView(CreateView):
    form_class = MenuModelForm
    template_name = "abfrage/menu_form.html"

    def get_initial(self):
        return {**super().get_initial(),
                "label": self.request.GET.get("label"),
                "closed_at": self.request.GET.get("closed_at")}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "icons": models.Serving.ICONS}

    def form_valid(self, form):
        form.save(commit=False)
        form.instance.owner = _get_userdata(self.request)["uid"]
        form.save(commit=True)
        form.process_servings(self.request.POST)
        return super().form_valid(form)


@method_decorator(require_jwt_login, name="dispatch")
class MenuUpdateView(UpdateView):
    model = models.Menu
    form_class = MenuModelForm
    template_name = "abfrage/menu_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs),
                "servings": [{"pk": serving.pk, "icon": serving.icon, "label": serving.label}
                             for serving in self.object.servings.all()],
                "icons": models.Serving.ICONS}

    def form_valid(self, form):
        form.process_servings(self.request.POST)
        return super().form_valid(form)


@method_decorator(require_jwt_login, name="dispatch")
class MenuDeleteView(DeleteView):
    model = models.Menu
    success_url = reverse_lazy("abfrage:start")


@method_decorator(require_jwt_login, name="dispatch")
class MenuDetailView(DetailView):
    model = models.Menu

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changed = False
        self.error_message = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        userdata = _get_userdata(self.request)
        context["userdata"] = userdata

        serving_objects = self.object.servings.all()
        servings = {serving.pk: {"obj": serving, "own": 0, "total": 0} for serving in serving_objects}
        others = defaultdict(lambda: {"displayName": "", "servings": {pk: 0 for pk in servings.keys()}})

        for reservation in models.Reservation.objects.filter(serving__menu=self.object):
            servings[reservation.serving.pk]["total"] += reservation.count

            if reservation.customer_uid == userdata["uid"]:
                servings[reservation.serving.pk]["own"] += reservation.count
            else:
                others[reservation.customer_uid]["displayName"] = reservation.customer
                others[reservation.customer_uid]["servings"][reservation.serving.pk] += reservation.count

        context["servings"] = servings.values()
        context["others"] = [
            {"displayName": other["displayName"], "servings": [other["servings"][pk] for pk in servings.keys()]}
            for other in others.values()
        ]

        context["changed"] = self.changed
        context["error_message"] = self.error_message
        context["is_redirected"] = (self.request.GET.get("redirected", "0") != "0")
        context["is_admin"] = (userdata["uid"] == self.object.owner)

        return context

    def post(self, request, *args, **kwargs):
        userdata = _get_userdata(request)

        try:
            with transaction.atomic():
                self._update(userdata, request.POST)
        except ValidationError as exception:
            self.error_message = exception.message
        else:
            self.changed = True

        return self.get(request, *args, **kwargs)

    def _update(self, userdata, post_data):
        _object = self.get_object()
        servings = {str(serving.pk): serving for serving in _object.servings.all()}

        if not _object.is_open:
            raise ValidationError("Die Anmeldung für das Menü ist bereits geschlossen")

        for field, value in post_data.items():  # type: (str, str)
            if field not in servings:
                continue

            try:
                value_num = int(value) if value else 0
            except ValueError:
                raise ValidationError(f"Bestellmenge für {servings[field].label} ist keine Ganzzahl")

            if value_num < 0:
                raise ValidationError(f"Negative Bestellung für {servings[field].label} sind nicht zulässig")

            if value_num > 20:
                raise ValidationError(f"Bestellmenge für {servings[field].label} zu hoch")

            models.Reservation.objects.update_or_create(
                customer_uid=userdata["uid"],
                serving=servings[field],
                defaults={"count": value_num, "customer": userdata["displayName"]},
            )


def _get_userdata(request):
    userdata = request.session.get("jwt_userdata", {})
    return userdata
