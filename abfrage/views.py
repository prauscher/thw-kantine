from collections import defaultdict
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import render, redirect
from django.views.generic import ListView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView
from django.urls import reverse_lazy
from django.utils import timezone
from . import models


class MenuListView(ListView):
    model = models.Menu

    def get_queryset(self):
        return super().get_queryset().filter(Q(closed_at__isnull=True) | Q(closed_at__gte=timezone.now()))


class MenuModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["closed_at"].widget.input_type = "datetime-local"

    class Meta:
        model = models.Menu
        fields = ["label", "closed_at"]


class MenuCreateView(CreateView):
    form_class = MenuModelForm
    template_name = "abfrage/menu_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "icons": models.Serving.ICONS}

    def form_valid(self, form):
        form.save(commit=False)
        form.instance.owner = _get_userdata(self.request)["uid"]
        form.save(commit=True)

        servings = defaultdict(dict)
        for field, value in self.request.POST.items():
            if field.startswith("serving-") and "-" in field[8:]:
                serving_no, _, option = field[8:].partition("-")
                servings[serving_no][option] = value

        for serving_data in servings.values():
            if not serving_data.get("label"):
                continue

            models.Serving.objects.create(
                menu=form.instance, icon=serving_data.get("icon"), label=serving_data.get("label")
            )

        return super().form_valid(form)


class MenuDeleteView(DeleteView):
    model = models.Menu
    success_url = reverse_lazy("abfrage:start")


class MenuDetailView(DetailView):
    model = models.Menu

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changed = False

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
        context["is_admin"] = (userdata["uid"] == self.object.owner)

        return context

    def post(self, request, *args, **kwargs):
        userdata = _get_userdata(request)

        if not userdata:
            raise PermissionDenied

        _object = self.get_object()
        servings = {str(serving.pk): serving for serving in _object.servings.all()}

        for field, value in request.POST.items():  # type: (str, str)
            if field not in servings:
                continue

            if not value:
                value = "0"

            if not value.isnumeric():
                raise ValidationError(f"Wert muss eine Ganzzahl sein nicht: {value!r}")

            models.Reservation.objects.update_or_create(
                customer_uid=userdata["uid"],
                serving=servings[field],
                defaults={"count": int(value), "customer": userdata["displayName"]},
            )

        self.changed = True

        return self.get(request, *args, **kwargs)


def _get_userdata(request):
    userdata = request.session.get("jwt_userdata", {})
    return userdata
