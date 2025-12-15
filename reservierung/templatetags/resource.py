from collections import defaultdict

from django import template
from django.utils.safestring import SafeText, mark_safe
from django.template import loader

from reservierung import models

register = template.Library()


@register.filter("resource_approval_scheme")
def resource_approval_scheme(resource_or_usage: models.Resource | models.ResourceUsage,
                             ) -> SafeText:
    if isinstance(resource_or_usage, models.Resource):
        resource = resource_or_usage
        usage = None
        raw_voting_groups = resource.get_voting_groups()
    elif isinstance(resource_or_usage, models.ResourceUsage):
        resource = resource_or_usage.resource
        usage = resource_or_usage
        raw_voting_groups = usage.get_voting_groups()
    else:
        message = f"{resource_or_usage} ({type(resource_or_usage)} is not supported."
        raise TypeError(message)

    votes = {}
    if usage:
        votes = {vote.approver: vote
                 for vote in usage.confirmations.filter(
                     revoked_at__isnull=True,
                     approver__isnull=False,
                 )}

    voting_groups = {voting_group: [(manager_user, votes.get(manager_user), funktion.funktion_label)
                                    for funktion, manager_user in manager_users]
                     for voting_group, manager_users in raw_voting_groups.items()}

    context = {}
    context["resource"] = resource
    context["informed"] = voting_groups.pop("", [])
    context["voting_groups"] = sorted(voting_groups.items())
    context["admins"] = list(resource.get_admins())

    return mark_safe(loader.render_to_string(
        "reservierung/_resource_approval_scheme.html", context))
