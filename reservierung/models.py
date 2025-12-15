from collections import defaultdict
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
import uuid

from django import forms
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.template.defaultfilters import slugify

from kantine.utils import find_login_url
from login_hermine.utils import send_hermine_user

from .templatetags.timerange import timerange_filter

# Messages are formated using str.format and may use the following kwargs:
# - firstname: Firstname of the receiving user
# - surname: Surname of the receiving user
# - termin_owner: __str__ of the user who created the termin
# - termin_label: label of the termin associated with the usage
# - resource_label: label of the ressource associated with the usage
# - timerange: timerange (see timerange_filter) of the termin associated with the usage
# - usage_link: Full URL to reach resourceusage_detail (not useful for MESSAGE_DELETED)
MESSAGE_INFORM = "Hallo {firstname}, für {resource_label} wurde durch {termin_owner} eine neue Buchung für {termin_label} ({timerange}) erstellt: {usage_link}"
MESSAGE_VOTE = "Hallo {firstname}, {termin_owner} hat {resource_label} für {termin_label} ({timerange}) angefragt. Du kannst unter {usage_link} zustimmen."
MESSAGE_CONFIRM = "Hallo {firstname}, die Buchung von {resource_label} für {termin_label} ({timerange}) durch {termin_owner} wurde bestätigt: {usage_link}"
MESSAGE_UNCONFIRM = "Hallo {firstname}, die Bestätigung der Buchung von {resource_label} für {termin_label} ({timerange}) wurde zurückgezogen: {usage_link}"
MESSAGE_REJECTED = "Hallo {firstname}, die Buchung von {resource_label} für {termin_label} ({timerange}) wurde storniert: {usage_link}"
MESSAGE_UNREJECTED = "Hallo {firstname}, die Stornierung der Buchung von {resource_label} für {termin_label} ({timerange}) wurde zurückgezogen: {usage_link}"
MESSAGE_DELETED = "Hallo {firstname}, die Buchung von {resource_label} for {termin_label} ({timerange}) wurde gelöscht."


class User(models.Model):
    # Any field may be empty to be filled on first login
    username = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Benutzername",
        help_text="Benutzername in NextCloud zur Anmeldung.",
    )
    firstname = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="Vorname",
        help_text="Vorname wie in THWin",
    )
    surname = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="Nachname",
        help_text="Nachname wie in THWin",
    )

    def send_hermine(self, message):
        if not self.firstname or not self.surname:
            raise ValueError
        send_hermine_user(f"{self.firstname} {self.surname}", message)

    @classmethod
    def send_multiple(cls, users, message, **kwargs) -> None:
        for user in users:
            with suppress(ValueError):
                user.send_hermine(message.format(firstname=user.firstname,
                                                 surname=user.surname,
                                                 **kwargs))

    @classmethod
    def get(cls, request):
        # format from nextcloud
        firstname, _, surname = request.jwt_user_display.rpartition(" ")
        surname = surname.replace("_", " ")

        try:
            user = cls.objects.get(username=request.jwt_user_id)
            if user.firstname != firstname or user.surname != surname:
                user.firstname = firstname
                user.surname = surname
                user.save(update_fields=["surname", "firstname"])
        except cls.DoesNotExist:
            user, _ = cls.objects.update_or_create(
                firstname=firstname, surname=surname,
                defaults={"username": request.jwt_user_id},
            )
        return user

    def __str__(self):
        if self.surname and self.firstname:
            return f"{self.firstname} {self.surname}"
        return f"({self.username})"

    class Meta:
        verbose_name = "Benutzer"
        verbose_name_plural = "Benutzer"
        ordering = ("surname", "firstname", "username")
        indexes = [
            models.Index(fields=("username",)),
            models.Index(fields=("firstname", "surname")),
        ]
        constraints = [
            models.UniqueConstraint("username", "firstname", "surname",
                                    name="unique_user"),
        ]


class Termin(models.Model):
    repeat_uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        verbose_name="Serien-UUID",
        help_text="UUID zur Identifikation von Terminwiederholungen.",
    )
    label = models.CharField(
        max_length=150,
        verbose_name="Bezeichner",
        help_text='Terminbeschreibung, z.B. "Bergung Theorie Gesteinsbearbeitu'
                  'ng".',
    )
    description = models.TextField(
        verbose_name="Beschreibung",
        help_text="Eigene Notizen zum Termin.",
        blank=True,
    )
    owner = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="termine",
        verbose_name="Eigentümer",
        help_text="Ersteller des Termins, kann ohne Wert sein, wenn der ursprü"
                  "ngliche Eigentümer gelöscht wurde.",
    )
    start = models.DateTimeField(
        verbose_name="Start",
        help_text="Beginn des Termins, sollte im Regelfall in der Zukunft lieg"
                  "en.",
    )
    end = models.DateTimeField(
        verbose_name="Ende",
        help_text="Ende des Termins, muss nach dem Beginn des Termins liegen.",
    )

    @property
    def state(self):
        states = [usage.state for usage in self.usages.all()]
        if "rejected" in states:
            return "rejected"
        if "requested" in states:
            return "requested"
        return "approved"

    @property
    def is_repeated(self):
        return Termin.objects.filter(repeat_uuid=self.repeat_uuid).count() > 1

    def get_overlap(self, other: "Termin") -> tuple[datetime, datetime]:
        """Find overlapping time with other Termin.

        Return a tuple with start and end datetime of the overlap or raise
        ValueError if other does not overlap with this Termin.
        """
        _, (start, start_marker), (end, end_marker), _ = sorted([
            (self.start, "start"),
            (self.end, "end"),
            (other.start, "start"),
            (other.end, "end"),
        ])
        if start_marker != "start" or end_marker != "end":
            raise ValueError

        return start, end

    def get_absolute_url(self):
        return reverse("reservierung:termin_detail",
                       kwargs={"pk": self.pk,
                               "date": f"{self.start:%Y%m%d}",
                               "slug": slugify(self.label)})

    def get_absolute_edit_url(self):
        return reverse("reservierung:termin_edit",
                       kwargs={"pk": self.pk,
                               "date": f"{self.start:%Y%m%d}",
                               "slug": slugify(self.label)})

    def get_absolute_delete_url(self):
        return reverse("reservierung:termin_delete",
                       kwargs={"pk": self.pk,
                               "date": f"{self.start:%Y%m%d}",
                               "slug": slugify(self.label)})

    def __str__(self):
        return f"{self.label} {self.start:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Termin"
        verbose_name_plural = "Termine"
        ordering = ("start", "label")
        indexes = [
            models.Index(fields=("start", "end")),
        ]

    def create_usage(self, resource, user):
        usage = ResourceUsage.objects.create(termin=self, resource=resource)
        usage.log(ResourceUsageLogMessage.META, user,
                  f"Anfrage für {timerange_filter(self.start, self.end)} erstellt.")

        missing_voting_groups = set()
        voting_groups = defaultdict(list)
        for voting_group, manager_users in usage.get_voting_groups().items():
            if voting_group:
                missing_voting_groups.add(voting_group)

            voting_groups[voting_groups].extend(manager_user for _, manager_user in manager_users)

        inform_users = set(voting_groups.pop("", []))
        vote_users = set()

        for voting_group, manager_users in voting_groups.items():
            if user in manager_users:
                ResourceUsageConfirmation.objects.update_or_create(
                    resource_usage=usage,
                    approver=user,
                    defaults={"comment": ""},
                )
                usage.log(ResourceUsageLogMessage.VOTES, user,
                          "Zustimmung bei Erstellung der Anfrage.")
                missing_voting_groups.discard(voting_group)
                inform_users.update(manager_users)
            else:
                vote_users.update(manager_users)

        if missing_voting_groups:
            usage.send_inform(inform_users - vote_users)
            usage.send_vote(vote_users)
        else:
            # update_state will inform users
            usage.update_state()

    def remove_usage(self, resource, user):
        try:
            usage = ResourceUsage.objects.filter(termin=self, resource=resource).get()
        except ResourceUsage.DoesNotExist:
            return

        usage.send_delete()
        usage.delete()


class Resource(models.Model):
    part_of = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="consists_of",
        verbose_name="Übergeordnete Ressource",
        help_text="Ressource von der diese Ressource ein Teil ist. Wird eine ü"
                  "bergeordnete Ressource gebucht, werden die Verwalter dieser"
                  " Ressource lediglich informiert.",
    )
    selectable = models.BooleanField(
        default=True,
        verbose_name="Auswählbar?",
        help_text="Ressourcen die nicht auswählbar sind, stehen nicht direkt f"
                  "ür Termine zur Verfügung, sondern dienen der Strukturierung"
                  " von untergeordneten Ressourcen.",
    )
    label = models.CharField(
        max_length=70,
        unique=True,
        verbose_name="Bezeichner",
        help_text="Eindeutige Bezeichnung der Ressource, die auch ohne den Kon"
                  "text der übergeordneten Ressource verständlich ist.",
    )
    slug = models.SlugField(
        unique=True,
        verbose_name="URL-Bezeichner",
        help_text="Kurzbezeichner der in URLs verwendet werden kann. Sollte ni"
                  "cht geändert werden, um ggf. bestehende URLs nicht zu besch"
                  "ädigen.",
    )

    @property
    def related_resources(self):
        """List all related resources (superordinated and subordnated)."""
        return set(self.traverse_up()) | set(self.traverse_down())

    def traverse_up(self):
        """Iterate over all superordinated `Resource`s.

        Include own object. Useful when looking for conflicts.
        """
        yield self
        if self.part_of:
            yield from self.part_of.traverse_up()

    def traverse_down(self):
        """Iterate over all subordinate `Resource`s.

        Include own object as first item. Useful to find all `ResourceManager`s
        who should be informed when a `ResourceUsage` gets approved.
        """
        yield self
        for child in self.consists_of.all():
            yield from child.traverse_down()

    def get_voting_groups(self) -> dict[str, list[tuple[str, "User"]]]:
        """Get voting groups of this Resource.

        Returns a dict with str containing the voting group as key and a list
        of tuples consisting of the funktion_label and User for each eligble
        user.
        Note that one voting group may be the empty string for users not
        actually voting, but being informed.

        str (voting group) => list of (str (funktion_label), User)
        """
        voting_groups = {}
        for manager in self.managers.all():
            voting_group = manager.voting_group
            voting_groups.setdefault(voting_group, [])
            voting_groups[voting_group].extend(
                (manager.funktion, user) for user in manager.funktion.user.all())
        return voting_groups

    def _get_admin_query(self):
        return ResourceManager.objects.filter(admin=True, resource__in=self.traverse_up())

    def is_admin(self, user):
        return self._get_admin_query().filter(funktion__user=user).exists()

    def get_admins(self):
        for admin in self._get_admin_query():
            users = admin.funktion.user.all()
            for user in users:
                yield (user, admin)
            if not users:
                yield (None, admin)

    def get_absolute_url(self):
        return reverse("reservierung:resource_detail",
                       kwargs={"slug": self.slug})

    def __str__(self):
        return f"{self.label}"

    class Meta:
        verbose_name = "Ressource"
        verbose_name_plural = "Ressourcen"
        ordering = ("label",)


class Funktion(models.Model):
    user = models.ManyToManyField(
        User,
        related_name="funktionen",
        blank=True,
    )
    funktion_label = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="Funktion",
        help_text="Optionale Funktionsbezeichnung wie in THWin (z.B. Gruppenfü"
                  "hrer/in Elektroversorgung).",
    )

    def __str__(self):
        return f"{self.funktion_label}"

    class Meta:
        verbose_name = "Funktion"
        verbose_name_plural = "Funktionen"
        ordering = ("funktion_label",)
        indexes = [
            models.Index(fields=("funktion_label",)),
        ]


class ResourceManager(models.Model):
    resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name="managers",
    )
    funktion = models.ForeignKey(
        Funktion,
        on_delete=models.CASCADE,
        related_name="managers",
    )
    voting_group = models.CharField(
        max_length=15,
        blank=True,
        verbose_name="Abstimmungsgruppe",
        help_text="Je Ressource können mehrere Abstimmungsgruppen gebildet wer"
                  "den: Aus jeder Abstimmungsgruppe muss dann mindestens eine "
                  "Person der Buchung zustimmen. Eine leere Abstimmungsgruppe "
                  "wird für Personen verwendet, die nicht abstimmen müssen, ab"
                  "er über erfolgreiche Buchungen informiert werden sollen.",
    )
    admin = models.BooleanField(
        verbose_name="Administrator",
        help_text="Erlaube diesen Benutzern Belegungen (auch für untergeordnet"
                  "e Ressourcen) zu stornieren.",
    )

    def __str__(self):
        return f"{self.resource}: {self.voting_group} {self.funktion}"

    class Meta:
        verbose_name = "Ressourcenverwalter"
        verbose_name_plural = "Ressourcenverwalter"
        ordering = ("resource", "voting_group", "funktion")


class ResourceUsage(models.Model):
    termin = models.ForeignKey(
        Termin,
        on_delete=models.CASCADE,
        related_name="usages",
    )
    resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name="usages",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    rejected_by = models.ForeignKey(
        User,
        blank=True,
        null=True,
        related_name="usages_rejected",
        on_delete=models.SET_NULL,
    )

    @property
    def state(self):
        if self.rejected_at is not None:
            return "rejected"

        if self.approved_at is not None:
            return "approved"

        return "requested"

    @property
    def approved(self):
        return self.approved_at is not None and self.rejected_at is None

    @classmethod
    def find_related(cls, /, start: datetime, end: datetime, resources: Iterable[Resource]) -> models.QuerySet["ResourceUsage"]:
        related_resources = set()
        for resource in resources:
            related_resources.update(resource.related_resources)

        return cls.objects.filter(
            termin__start__lte=end,
            termin__end__gte=start,
            resource__in=related_resources,
            rejected_at__isnull=True,
        )

    def get_voting_groups(self) -> dict[str, list[tuple[str, "User"]]]:
        """Get voting groups eligble for this Usage.

        Mostly the same as voting groups for the Resource of this Usage, but
        may contain an additional voting group to resolve conflicts.
        """
        return self.resource.get_voting_groups()

    def get_conflicts(self) -> tuple[list[tuple["ResourceUsage", datetime, datetime]], bool]:
        """Find conflicting ResourceUsage with this ResourceUsage.

        Returns a tuple with a list of conflicting usages and a boolean if any
        conflicting usage is already confirmed. The list of conflicting usages
        consists of three-tuples with the conflicting ResourceUsage and two
        timestamps, representing the start and end of overlap in usage.
        """
        related_usages = list(ResourceUsage.find_related(
            self.termin.start,
            self.termin.end,
            [self.resource],
        ).exclude(termin=self.termin))

        conflict_confirmed = False
        conflicts = []
        for usage in related_usages:
            conflict_start, conflict_end = self.termin.get_overlap(usage.termin)
            conflicts.append((usage, conflict_start, conflict_end))
            if usage.state == "approved":
                conflict_confirmed = True

        return conflicts, conflict_confirmed

    def log(self, kind, user, message):
        ResourceUsageLogMessage.objects.create(
            usage=self,
            kind=kind,
            user=user,
            message=message,
        )

    def update_state(self):
        all_voting_groups = set()
        approved_voting_groups = set()
        matching_voting_groups = defaultdict(set)

        for voting_group, manager_users in self.get_voting_groups().items():
            if not voting_group:
                continue

            all_voting_groups.add(voting_group)
            for _, manager_user in manager_users:
                matching_voting_groups[manager_user].add(voting_group)

        for vote in self.confirmations.filter(revoked_at__isnull=True):
            approved_voting_groups.update(matching_voting_groups[vote.approver])

        # approve once no voting group is left without approval
        should_approved = not (all_voting_groups - approved_voting_groups)

        # special case for self regulating resources: only approve if no
        # conflict exists
        if not all_voting_groups:
            conflicts = ResourceUsage.find_related(
                self.termin.start, self.termin.end, [self.resource],
            ).exclude(termin=self.termin)

            if conflicts.exists():
                should_approved = False

        # approved_at should be None iff missing_voting_groups is not empty
        if should_approved != (self.approved_at is not None):
            self.approved_at = timezone.now() if should_approved else None
            self.save(update_fields=["approved_at"])

            if self.approved_at is not None:
                self.log(ResourceUsageLogMessage.STATE, None,
                         "Buchung bestätigt.")
                self.send_confirm()
            else:
                self.log(ResourceUsageLogMessage.STATE, None,
                         "Bestätigung der Buchung entfällt.")
                self.send_unconfirm()

    def get_absolute_url(self):
        return reverse("reservierung:resourceusage_detail",
                       kwargs={"termin_id": self.termin.id,
                               "termin_date": f"{self.termin.start:%Y%m%d}",
                               "termin_slug": slugify(self.termin.label),
                               "resource_slug": self.resource.slug})

    def get_absolute_vote_url(self):
        return reverse("reservierung:resourceusage_vote",
                       kwargs={"termin_id": self.termin.id,
                               "termin_date": f"{self.termin.start:%Y%m%d}",
                               "termin_slug": slugify(self.termin.label),
                               "resource_slug": self.resource.slug})

    def get_absolute_vote_revoke_url(self):
        return reverse("reservierung:resourceusage_vote_revoke",
                       kwargs={"termin_id": self.termin.id,
                               "termin_date": f"{self.termin.start:%Y%m%d}",
                               "termin_slug": slugify(self.termin.label),
                               "resource_slug": self.resource.slug})

    def get_absolute_reject_url(self):
        return reverse("reservierung:resourceusage_reject",
                       kwargs={"termin_id": self.termin.id,
                               "termin_date": f"{self.termin.start:%Y%m%d}",
                               "termin_slug": slugify(self.termin.label),
                               "resource_slug": self.resource.slug})

    def get_absolute_reject_revert_url(self):
        return reverse("reservierung:resourceusage_reject_revert",
                       kwargs={"termin_id": self.termin.id,
                               "termin_date": f"{self.termin.start:%Y%m%d}",
                               "termin_slug": slugify(self.termin.label),
                               "resource_slug": self.resource.slug})

    def __str__(self):
        return f"{self.resource} für {self.termin}"

    class Meta:
        verbose_name = "Buchung"
        verbose_name_plural = "Buchungen"
        ordering = ("termin", "created_at")
        indexes = [
            models.Index(fields=("termin", "resource")),
        ]
        constraints = [
            models.UniqueConstraint(name="termin_resource",
                                    fields=("termin", "resource")),
        ]

    def send_inform(self, users):
        User.send_multiple(users, MESSAGE_INFORM,
                           **self._message_kwargs())

    def send_vote(self, users):
        User.send_multiple(users, MESSAGE_VOTE,
                           **self._message_kwargs())

    def get_audience(self):
        resources = set(self.resource.traverse_up()) | set(self.resource.traverse_down())

        users = set()
        if self.termin.owner:
            users.add(self.termin.owner)

        for manager in ResourceManager.objects.filter(resource__in=resources):
            users.update(manager.funktion.user.all())

        # add users of conflicting usages
        conflicts, _ = self.get_conflicts()
        for conflict_usage, _, _ in conflicts:
            conflict_owner = conflict_usage.termin.owner
            if conflict_owner:
                users.add(conflict_owner)

        return users

    def send_confirm(self):
        User.send_multiple(self.get_audience(), MESSAGE_CONFIRM,
                           **self._message_kwargs())

    def send_unconfirm(self):
        User.send_multiple(self.get_audience(), MESSAGE_UNCONFIRM,
                           **self._message_kwargs())

    def send_reject(self):
        User.send_multiple(self.get_audience(), MESSAGE_REJECTED,
                           **self._message_kwargs())

    def send_unreject(self):
        User.send_multiple(self.get_audience(), MESSAGE_UNREJECTED,
                           **self._message_kwargs())

    def send_delete(self):
        User.send_multiple(self.get_audience(), MESSAGE_DELETED,
                           **self._message_kwargs())

    def _message_kwargs(self):
        return {"termin_owner": str(self.termin.owner),
                "termin_label": self.termin.label,
                "resource_label": self.resource.label,
                "timerange": timerange_filter(self.termin.start, self.termin.end),
                "usage_link": find_login_url(self.get_absolute_url())}


class ResourceUsageLogMessage(models.Model):
    META = "meta"
    VOTES = "votes"
    REJECTS = "rejects"
    STATE = "state"
    USER = "user"

    MESSAGE_TYPES = {
        META: "Anforderung erstellt oder geändert",
        VOTES: "Zustimmungen",
        REJECTS: "Ablehnungen",
        STATE: "Statusänderungen",
        USER: "Benutzerkommentare",
    }

    usage = models.ForeignKey(
        ResourceUsage,
        on_delete=models.CASCADE,
        related_name="log_messages",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="log_messages",
    )
    kind = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPES,
        blank=True,
    )
    message = models.TextField()

    class Meta:
        verbose_name = "Lognachricht"
        verbose_name_plural = "Lognachrichten"
        ordering = ("timestamp",)


class ResourceUsageConfirmation(models.Model):
    REVOKE_TERMIN_CHANGE = "termin_change"
    REVOKE_APPROVER = "approver"
    REVOKE_REASONS = {
        REVOKE_TERMIN_CHANGE: "Änderung an Termin",
        REVOKE_APPROVER: "Durch Genehmiger zurückgezogen",
    }

    resource_usage = models.ForeignKey(
        ResourceUsage,
        on_delete=models.CASCADE,
        related_name="confirmations",
        verbose_name="Verwendung",
    )
    approver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="approvals",
        verbose_name="Genehmiger",
    )
    comment = models.TextField(
        blank=True,
        verbose_name="Verwendungshinweis",
        help_text="Freitext durch den Genehmiger an Anfragenden zur Klarstellu"
                  "ng von Details.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        verbose_name="Genehmigungsdatum",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Zurückgezogen",
        help_text="Datum zu dem die Genehmigung zurückgezogen wurde (leer wenn"
                  " die Genehmigung gültig ist)",
    )
    revoke_reason = models.CharField(
        max_length=20,
        choices=REVOKE_REASONS,
        blank=True,
        verbose_name="Rückzugsgrund",
        help_text="Grund für den Rückzug der Genehmigung.",
    )

    def __str__(self):
        text = f"{self.resource_usage} durch {self.approver}"
        if self.revoked_at is not None:
            text = f"{text} (Zurückgezogen)"
        return text

    class Meta:
        verbose_name = "Buchungsbestätigung"
        verbose_name_plural = "Buchungsbestätigungen"
        ordering = ("resource_usage", "created_at")
        indexes = [
            models.Index(fields=("resource_usage", "approver")),
        ]
