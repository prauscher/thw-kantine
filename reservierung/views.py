from collections import defaultdict
from contextlib import suppress
from datetime import datetime, time, timedelta
from functools import lru_cache
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import slugify
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import FormView, TemplateView, ListView, DetailView, DeleteView

from kantine.decorators import require_jwt_login
from . import models, utils
from .templatetags.timerange import timerange_filter

@require_POST
@require_jwt_login
def fetch_usages(request):
    try:
        start = timezone.make_aware(datetime.strptime(request.POST["start"], "%Y-%m-%dT%H:%M"), None)
        end = timezone.make_aware(datetime.strptime(request.POST["end"], "%Y-%m-%dT%H:%M"), None)
    except (KeyError, ValueError):
        return JsonResponse({"error": "unexpected arguments"})

    parents = {resource.pk: None if resource.part_of is None else resource.part_of.pk
               for resource in models.Resource.objects.all()}

    @lru_cache(maxsize=None)
    def _get_upper_resources(resource_id):
        if parents[resource_id] is None:
            return []
        return _get_upper_resources(parents[resource_id]) + [parents[resource_id]]

    @lru_cache(maxsize=None)
    def _get_lower_resources(resource):
        resources = []
        for child in resource.consists_of.all():
            resources.append(child.pk)
            resources.extend(_get_lower_resources(child))
        return resources

    # resource pk => list of tuples (timestamp, "start" / "end", kind)
    # note that "end" < "start" is crucial for sorting here
    # kind is one of "3-direct", "2-super", "1-part" for sorting
    usages = defaultdict(list)
    all_usages = {}

    for usage in models.ResourceUsage.objects.filter(termin__end__gte=start, termin__start__lte=end, rejected_at__isnull=True).order_by("termin__start"):
        all_usages[usage.pk] = {
            "termin_id": usage.termin.id,
            "resource_id": usage.resource.pk,
            "termin_label": usage.termin.label,
            "approved": usage.approved,
        }

        usages[usage.resource.pk].append((usage.termin.start, "start", "3-direct", usage.pk))
        usages[usage.resource.pk].append((usage.termin.end, "end", "3-direct", usage.pk))
        for upper in _get_upper_resources(usage.resource.pk):
            usages[upper].append((usage.termin.start, "start", "1-part", usage.pk))
            usages[upper].append((usage.termin.end, "end", "1-part", usage.pk))

        for lower in _get_lower_resources(usage.resource):
            usages[lower].append((usage.termin.start, "start", "2-super", usage.pk))
            usages[lower].append((usage.termin.end, "end", "2-super", usage.pk))

    # build usage bars
    # resource pk => list of (continous) tuples (duration, kind, ResourceUsage)
    usage_bars = {}

    for resource_id in parents.keys():
        pos = start
        resource_usages = usages[resource_id]
        # make sure usage bars always stretch till end
        resource_usages.append((end, "exit", "0-free", None))

        usage_bar = []
        # set of tuples (kind, ResourceUsage)
        current_usages = set()
        for timestamp, kind, prio, usage in sorted(resource_usages):
            # make sure next_pos will always stay in range of (start, end)
            next_pos = max(pos, min(timestamp, end))
            if next_pos > pos:
                usage_bar.append(((next_pos - pos).total_seconds(),
                                  max(current_usages | {("0-free",)})[0][2:],
                                  [usage for _, usage in current_usages]))

            if timestamp >= end:
                break

            if kind == "start":
                current_usages.add((prio, usage))
            elif kind == "end":
                current_usages.remove((prio, usage))

            pos = next_pos

        usage_bars[resource_id] = usage_bar

    return JsonResponse({
        "total": (end - start).total_seconds(),
        "usages": all_usages,
        "usage_bars": usage_bars,
    })


@method_decorator(require_jwt_login, name="dispatch")
class UebersichtView(TemplateView):
    template_name = "reservierung/start.html"

    def get_context_data(self):
        context = super().get_context_data()
        user = models.User.get(self.request)

        context["next_own_termine"] = self.get_next_own_termine(user, limit=5)
        context["admin_missing_approval"] = self.get_admin_missing_approval(user)
        context["missing_approval"] = self.get_missing_approval(user, limit=5)
        context["next_managed_resource_termine"] = self.get_next_managed_resource_termine(user, limit=5)
        context["next_usages"] = self.get_next_usages()

        return context

    def get_next_own_termine(self, user, *, limit):
        next_own_termine = models.Termin.objects.filter(
            owner=user,
            end__gte=timezone.now(),
        ).order_by("start")[:limit]
        return [(termin, termin.state) for termin in next_own_termine]

    def get_admin_missing_approval(self, user):
        admin_resources = set()
        for manager in models.ResourceManager.objects.filter(admin=True, funktion__user=user):
            admin_resources.update(manager.resource.traverse_down())
        # remove resources with managers (we only want to show self managed)
        for manager in models.ResourceManager.objects.exclude(voting_group=""):
            admin_resources.discard(manager.resource)

        return models.ResourceUsage.objects.filter(
            termin__end__gte=timezone.now(),
            resource__in=admin_resources,
            approved_at__isnull=True,
            rejected_at__isnull=True,
        )

    def get_missing_approval(self, user, *, limit: int):
        # find ResourceUsage with pending approval where we are manager and have not voted yet
        all_missing_approval = models.ResourceUsage.objects.filter(
            approved_at__isnull=True,
            rejected_at__isnull=True,
            termin__end__gte=timezone.now(),
        ).filter(
            ~Q(resource__managers__voting_group="") &
            Q(resource__managers__funktion__user=models.User.get(self.request))
        ).order_by("termin__start")

        missing_approval = []
        for usage in all_missing_approval:
            votes = {}
            for vote in usage.confirmations.filter(revoked_at__isnull=True, approver__isnull=False):
                votes[vote.approver] = vote

            voting_groups = defaultdict(list)
            all_voting_groups = set()
            our_voting_groups = set()
            approved_voting_groups = set()

            for voting_group, manager_users in usage.get_voting_groups().items():
                if not voting_group:
                    continue

                all_voting_groups.add(voting_group)
                for _, manager_user in manager_users:
                    if manager_user in votes:
                        approved_voting_groups.add(voting_group)
                    if manager_user == user:
                        our_voting_groups.add(voting_group)

            our_missing_voting_groups = (all_voting_groups - approved_voting_groups) & our_voting_groups
            if not our_missing_voting_groups:
                continue

            missing_approval.append(usage)

            if len(missing_approval) >= limit:
                break

        return missing_approval

    def get_next_managed_resource_termine(self, user, *, limit: int):
        my_resources = models.ResourceManager.objects.filter(funktion__user=user).values("resource")
        return models.ResourceUsage.objects.filter(
            rejected_at__isnull=True,
            termin__end__gte=timezone.now(),
            resource__in=my_resources,
        )[:limit]

    def get_next_usages(self):
        yield from utils.get_next_usages()


def update_url(request, params):
    get = request.GET.copy()
    for k, v in params.items():
        get[k] = v
    return "?" + get.urlencode()


class FilteredListView(ListView):
    search_fields = None
    timerange_fields = None
    base_filter = None
    filters = tuple()

    def get_search_fields(self):
        return self.search_fields

    def get_timerange_fields(self):
        return self.timerange_fields

    def get_filters(self):
        return self.filters

    def get_base_filter(self):
        if self.base_filter is None:
            return ~Q(pk=None)
        return self.base_filter

    def dispatch(self, request, *args, **kwargs):
        # do not use setup here to allow get_filters to use jwt-data
        # list of (filter_id, filter_name, filter_query, active)
        self._filters = []
        for filter_name, filter_query, default_active in self.get_filters():
            filter_id = slugify(filter_name)
            is_active = {"-1": False, "0": None, "1": True,
                         }.get(self.request.GET.get(f"filter_{filter_id}", None), default_active)
            self._filters.append((filter_id, filter_name, filter_query, is_active))

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data()
        context["timerange_available"] = bool(self.get_timerange_fields())
        context["timerange_start"], context["timerange_end"] = self.get_timerange()
        context["search_available"] = bool(self.get_search_fields())
        context["search_term"] = self.get_search_term()
        context["search_words"] = self.get_search_terms()
        context["filter_values"] = [(f"filter_{filter_id}", {True: "1", False: "-1", None: "0"}[filter_active])
                                    for filter_id, _, _, filter_active in self._filters]
        context["filters"] = [(filter_name,
                               update_url(self.request, {f"filter_{filter_id}": {True: "-1", False: "0", None: "1",
                                                                                 }[filter_active]}),
                               filter_active)
                              for filter_id, filter_name, _, filter_active in self._filters]
        return context

    def get_search_term(self):
        return self.request.GET.get("search", "")

    def get_search_terms(self):
        return [term for term in self.get_search_term().split(" ") if term]

    def get_search_filter(self):
        # Q(pk=None) is always False
        search_filter = ~Q(pk=None)
        for term in self.get_search_terms():
            term_filter = Q(pk=None)
            for field in self.get_search_fields():
                term_filter |= Q(**{f"{field}__icontains": term})
            search_filter &= term_filter
        return search_filter

    def get_default_timerange(self):
        return timezone.now(), None

    def get_timerange(self):
        start, end = self.get_default_timerange()

        with suppress(ValueError):
            start = timezone.make_aware(datetime.strptime(self.request.GET.get("start", ""), "%Y-%m-%dT%H:%M"), None)

        with suppress(ValueError):
            end = timezone.make_aware(datetime.strptime(self.request.GET.get("end", ""), "%Y-%m-%dT%H:%M"), None)

        return start, end

    def get_timerange_filter(self):
        filter = ~Q(pk=None)
        timerange_fields = self.get_timerange_fields()
        if not timerange_fields:
            return filter

        start, end = self.get_timerange()
        start_field, end_field = timerange_fields

        if start:
            filter &= Q(**{f"{end_field}__gte": start})
        if end:
            filter &= Q(**{f"{start_field}__lte": end})

        return filter

    def get_queryset(self):
        queryset = super().get_queryset()

        queryset = queryset.filter(self.get_base_filter())

        for _, _, filter_query, filter_active in self._filters:
            if filter_active is True:
                queryset = queryset.filter(filter_query)
            elif filter_active is False:
                queryset = queryset.exclude(filter_query)

        queryset = queryset.filter(self.get_search_filter())
        queryset = queryset.filter(self.get_timerange_filter())
        queryset = queryset.distinct()
        return queryset


class TitledMixin:
    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data()
        context["title"] = self.title
        return context


@method_decorator(require_jwt_login, name="dispatch")
class TerminListView(FilteredListView):
    model = models.Termin
    timerange_fields = ("start", "end")
    search_fields = ("label", "usages__resource__label")
    ordering = ("start",)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["object_list"] = [
            {
                "termin": object,
                "usages": object.usages.all().order_by("resource__label"),
            } for object in context["object_list"]
        ]
        return context


@method_decorator(require_jwt_login, name="dispatch")
class ResourceUsageListView(TitledMixin, FilteredListView):
    model = models.ResourceUsage
    timerange_fields = ("termin__start", "termin__end")
    ordering = ("termin__start",)
    search_fields = ("termin__label", "resource__label")


class AllTerminListView(TerminListView):
    filters = (
        ("Mit Abgelehnten Buchungen", Q(usages__rejected_at__isnull=False), None),
        ("Mit offenen Bestätigungen", Q(usages__approved_at__isnull=True), None),
    )

    def get_filters(self):
        filters = super().get_filters()
        filters = filters + (("Eigene Termine", Q(owner=models.User.get(self.request)), None),)
        return filters


@method_decorator(require_jwt_login, name="dispatch")
class CalendarView(TemplateView):
    template_name = "reservierung/calendar.html"

    def get_start_date(self):
        with suppress(KeyError, ValueError):
            return datetime.strptime(self.request.GET["date"], "%Y-%m-%d").date()
        return timezone.now().date()

    def get_timeranges(self):
        date = self.get_start_date()

        start_date = date + timedelta(days=-date.weekday())
        start = timezone.make_aware(datetime.combine(start_date, time()))

        WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        for _ in range(7):
            end = start + timezone.timedelta(days=1)
            yield f"{WEEKDAYS[start.weekday()]}, {start:%d.%m.%Y}", start, end
            start = end

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        context["date"] = self.get_start_date()

        context["items"] = []
        for label, start, end in self.get_timeranges():
            termine = models.Termin.objects.filter(
                start__lte=end,
                end__gte=start,
            ).order_by("start")
            context["items"].append((label, start, end, termine))

        return context


class TerminForm(forms.ModelForm):
    confirm_warnings = forms.BooleanField(
        label="Ich weiß was ich tue und möchte die angezeigten Warnungen ignorieren.",
        widget=forms.HiddenInput(),
        required=False,
    )
    resources = forms.MultipleChoiceField(
        required=False,
        choices=lambda: [(resource.pk, resource.label)
                         for resource in models.Resource.objects.all()],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["description"].widget.attrs.update({"rows": 4, "cols": 15})
        for field in ("start", "end"):
            self.fields[field].widget.input_type = "datetime-local"
            self.fields[field].widget.format = "%Y-%m-%dT%H:%M"

    class Meta:
        model = models.Termin
        fields = ("label", "description", "start", "end")

    def clean(self):
        data = super().clean()
        warnings = []

        if data["start"] > timezone.now() + timedelta(days=60):
            warnings.append(("start", "Der Termin liegt mehr als 60 Tage in der Zukunft."))

        if data["start"] < timezone.now() - timedelta(days=1):
            warnings.append(("start", "Der Termin liegt in der Vergangenheit."))

        if data["end"] - data["start"] > timedelta(days=30):
            warnings.append(("end", "Der Termin dauert länger als 30 Tage an."))

        if not data.get("resources"):
            warnings.append(("resources", "Keine Resourcen angegeben"))

        for resource_id in data.get("resources"):
            resource = models.Resource.objects.get(pk=resource_id)
            usages = models.ResourceUsage.find_related(
                data["start"],
                data["end"],
                [resource],
            )

            if self.instance.pk:
                usages = usages.exclude(termin=self.instance)

            if usages.exists():
                warnings.append(("resources", f"Die Ressource {resource.label} ist in dem Zeitraum bereits blockiert."))

        if warnings and not self.cleaned_data.get("confirm_warnings", False):
            self.fields["confirm_warnings"].widget = forms.CheckboxInput()
            for field, description in warnings:
                self.add_error(field, description)

        return data

    def clean_end(self):
        if self.cleaned_data["end"] <= self.cleaned_data["start"]:
            raise ValidationError("Ende liegt vor angegebener Startzeit.")

        return self.cleaned_data["end"]


@method_decorator(require_jwt_login, name="dispatch")
class TerminFormView(FormView):
    template_name = "reservierung/termin_form.html"
    form_class = TerminForm

    def dispatch(self, *args, **kwargs):
        # use dispatch here, as setup does not have jwt-data populated in request
        if "pk" in kwargs:
            self.object = self._get_object()
        else:
            self.object = None

        return super().dispatch(*args, **kwargs)

    def _get_object(self):
        return get_object_or_404(models.Termin, pk=self.kwargs["pk"],
                                 owner=models.User.get(self.request))

    def get_form_kwargs(self):
        return {"instance": self.object, **super().get_form_kwargs()}

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        context["object"] = self.object
        context["resources"] = list(_build_resources(part_of__isnull=True))

        context["selected_resources"] = []
        if self.request.POST:
            context["selected_resources"] = \
                [int(resource_pk) for resource_pk in self.request.POST.getlist("resources", [])]
        elif self.object:
            context["selected_resources"] = \
                [usage.resource.pk for usage in self.object.usages.all()]
        else:
            context["selected_resources"] = \
                [int(resource_pk) for resource_pk in self.request.GET.getlist("resources", [])]

        return context

    def form_valid(self, form):
        user = models.User.get(self.request)

        # as form is a ModelForm, its instance attribute already contains changed values

        if self.object:
            # refetch current values for comparision
            termin = self._get_object()

            if termin.start > form.instance.start or termin.end < form.instance.end:
                # renew confirmations (later) when time range is exceeded
                termin.usages.all().delete()
            elif termin.start < form.instance.start or termin.end > form.instance.end:
                # shortened, maybe this resolved conflicts?
                for usage in form.instance.usages.all():
                    usage.log(models.ResourceUsageLogMessage.META, user,
                              f"Anfragezeitraum auf {timerange_filter(form.instance.start, form.instance.end)} verkürzt.")

                    for conflict, _, _ in usage.get_conflicts()[0]:
                        conflict.update_state()

            # fields have already been updated during form clean
        else:
            form.instance.owner = user

        form.instance.save()
        self.success_url = form.instance.get_absolute_url()

        current_resource_ids = {int(usage.resource.pk) for usage in form.instance.usages.all()}
        target_resource_ids = {int(pk) for pk in form.cleaned_data.get("resources", [])}

        for resource_id in current_resource_ids - target_resource_ids:
            resource = models.Resource.objects.get(pk=resource_id)
            form.instance.remove_usage(resource, user)

        # create new resources
        for resource_id in target_resource_ids - current_resource_ids:
            resource = models.Resource.objects.get(pk=resource_id)
            form.instance.create_usage(resource, user)

        return super().form_valid(form)


@method_decorator(require_jwt_login, name="dispatch")
class TerminDeleteView(DeleteView):
    model = models.Termin
    success_url = reverse_lazy("reservierung:start")

    def get_queryset(self):
        return super().get_queryset().filter(owner=models.User.get(self.request))

    def form_valid(self, form):
        # check if conflicting usages may now be resolved
        for usage in self.object.usages.all():
            for conflict, _, _ in usage.get_conflicts()[0]:
                conflict.update_state()

        return super().form_valid(form)


@method_decorator(require_jwt_login, name="dispatch")
class TerminDetailView(DetailView):
    model = models.Termin

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["may_edit"] = self.object.owner == models.User.get(self.request)

        context["usages"] = []

        resources = set()
        for usage in self.object.usages.all():
            resources.add(usage.resource)
            context["usages"].append(usage)

        related_usages = models.ResourceUsage.find_related(
            self.object.start, self.object.end, resources
        ).exclude(termin=self.object)

        context["conflicts"] = []
        for usage in related_usages:
            conflict_start, conflict_end = self.object.get_overlap(usage.termin)
            context["conflicts"].append((usage, conflict_start, conflict_end))

        context["comments"] = models.ResourceUsageConfirmation.objects.filter(
            Q(resource_usage__termin=self.object) &
            Q(revoked_at__isnull=True) &
            ~Q(comment="")).order_by("created_at")

        context["log_messages"] = models.ResourceUsageLogMessage.objects.filter(usage__termin=self.object).order_by("timestamp")

        return context


@method_decorator(require_jwt_login, name="dispatch")
class ResourceUsageDetailView(DetailView):
    model = models.ResourceUsage

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return get_object_or_404(queryset,
                                 termin__pk=self.kwargs["termin_id"],
                                 resource__slug=self.kwargs["resource_slug"])

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        user = models.User.get(self.request)
        voting_groups = self.object.get_voting_groups()

        context["voting_groups"] = voting_groups
        context["may_reject"] = self.object.rejected_at is None and self.object.resource.is_admin(user)
        context["may_revert_reject"] = self.object.rejected_by == user
        context["may_revoke"] = self.object.confirmations.filter(
            revoked_at__isnull=True, approver=user).exists()
        context["may_vote"] = not context["may_revoke"] and voting_groups.may_vote(user)
        context["has_voting_groups"] = not voting_groups.is_open()

        context["conflicts"], context["conflict_confirmed"] = self.object.get_conflicts()

        context["comments"] = self.object.confirmations.filter(
            Q(revoked_at__isnull=True) & ~Q(comment=""),
        ).order_by("created_at")

        context["log_messages"] = self.object.log_messages.order_by("timestamp")

        return context


class ResourceUsageConfirmView(FormView):
    form_class = forms.Form

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.object = self.get_object()

    def get_object(self):
        return get_object_or_404(models.ResourceUsage,
                                 termin__pk=self.kwargs["termin_id"],
                                 resource__slug=self.kwargs["resource_slug"])

    def get_context_data(self):
        context = super().get_context_data()
        context["object"] = self.object
        return context

    def get_confirmation_queryset(self, user):
        return self.object.confirmations.filter(
            revoked_at__isnull=True,
            approver=user,
        )

    def get_success_url(self):
        return self.object.get_absolute_url()


class ResourceUsageVoteForm(forms.Form):
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"cols": 30, "rows": 3}),
        required=False,
        label="Kommentar",
        help_text="Ein Kommentar hilft bei Konflikten die Verwendungen aufeina"
                  "nder abzustimmen.",
    )


@method_decorator(require_jwt_login, name="dispatch")
class ResourceUsageVoteView(ResourceUsageConfirmView):
    template_name = "reservierung/resourceusage_vote.html"
    form_class = ResourceUsageVoteForm

    def get_context_data(self):
        context = super().get_context_data()

        context["conflicts"], context["conflict_confirmed"] = self.object.get_conflicts()

        return context

    def form_valid(self, form):
        user = models.User.get(self.request)

        # prevent double confirmation
        if self.get_confirmation_queryset(user).exists():
            raise Http404

        voting_groups = self.object.get_voting_groups()

        # check if we may vote after all
        if not voting_groups.may_vote(user):
            raise Http404

        # store vote
        models.ResourceUsageConfirmation.objects.create(
            resource_usage=self.object,
            approver=user,
            comment=form.cleaned_data["comment"],
        )

        comment_note = (f'mit Kommentar "{form.cleaned_data["comment"]}'
                        if form.cleaned_data["comment"] else "ohne Kommentar")
        self.object.log(models.ResourceUsageLogMessage.VOTES, user,
                        f"Manuell {comment_note} zugestimmt.")

        # possibly confirm usage
        self.object.update_state()

        return super().form_valid(form)


@method_decorator(require_jwt_login, name="dispatch")
class ResourceUsageRevokeVoteView(ResourceUsageConfirmView):
    template_name = "reservierung/resourceusage_vote_revoke.html"

    def form_valid(self, form):
        user = models.User.get(self.request)

        # Revoke Confirmation
        confirmation = get_object_or_404(self.get_confirmation_queryset(user))
        confirmation.revoked_at = timezone.now()
        confirmation.save(update_fields=["revoked_at"])

        self.object.log(models.ResourceUsageLogMessage.VOTES, user,
                        "Zustimmung manuell zurückgezogen.")

        # possibly remove confirmation of usage
        self.object.update_state()

        return super().form_valid(form)


@method_decorator(require_jwt_login, name="dispatch")
class ResourceUsageRejectView(ResourceUsageConfirmView):
    template_name = "reservierung/resourceusage_reject.html"

    def form_valid(self, form):
        user = models.User.get(self.request)

        # check if we may vote after all
        if not self.object.resource.is_admin(user):
            raise Http404

        self.object.rejected_at = timezone.now()
        self.object.rejected_by = user
        self.object.save(update_fields=["rejected_at", "rejected_by"])
        self.object.send_reject()

        self.object.log(models.ResourceUsageLogMessage.REJECTS, user,
                        "Abgelehnt.")

        # check related usages waiting for confirmation (which could maybe be
        # auto-accepted now)
        related_usages = models.ResourceUsage.find_related(
            self.object.termin.start,
            self.object.termin.end,
            [self.object.resource],
        )
        for related_usage in related_usages.filter(approved_at__isnull=True):
            related_usage.update_state()

        return super().form_valid(form)


@method_decorator(require_jwt_login, name="dispatch")
class ResourceUsageRevertRejectView(ResourceUsageConfirmView):
    template_name = "reservierung/resourceusage_reject_revert.html"

    def form_valid(self, form):
        user = models.User.get(self.request)

        if user != self.object.rejected_by:
            raise Http404

        self.object.rejected_at = None
        self.object.rejected_by = None
        self.object.save(update_fields=["rejected_at", "rejected_by"])
        self.object.send_unreject()

        self.object.log(models.ResourceUsageLogMessage.REJECTS, user,
                        "Ablehnung zurückgezogen.")

        # reset state
        self.object.update_state()

        return super().form_valid(form)


def _build_resources(**kwargs):
    for resource in models.Resource.objects.filter(**kwargs).order_by("label"):
        children = [(child, depth + 1, child_count)
                    for child, depth, child_count in _build_resources(part_of=resource)]

        yield (resource, 0, len(children))
        yield from children


@method_decorator(require_jwt_login, name="dispatch")
class ResourceListView(ListView):
    model = models.Resource

    def get_context_data(self, *args, **kwargs):
        user = models.User.get(self.request)

        managed_resources = set()
        admin_resources = set()
        for manager in models.ResourceManager.objects.filter(funktion__user=user):
            if manager.admin:
                for resource in manager.resource.traverse_down():
                    admin_resources.add(resource)
            if manager.voting_group:
                managed_resources.add(manager.resource)

        context = super().get_context_data(*args, **kwargs)
        context["resources"] = [(resource,
                                 resource in managed_resources,
                                 resource in admin_resources,
                                 depth,
                                 children)
                                for resource, depth, children in _build_resources(part_of__isnull=True)]
        return context


@method_decorator(require_jwt_login, name="dispatch")
class ResourceDetailView(DetailView):
    model = models.Resource

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        context["usages"] = models.ResourceUsage.find_related(
            timezone.now(),
            None,
            [self.object],
        ).order_by("termin__start")[:3]

        return context
