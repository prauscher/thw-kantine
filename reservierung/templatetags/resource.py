from collections import defaultdict

from django import template
from django.utils.safestring import SafeText, mark_safe
from django.template import loader

from reservierung import models

register = template.Library()


@register.filter("resource_approval_scheme")
def resource_approval_scheme(resource_or_usage: models.Resource | models.ResourceUsage,
                             ) -> SafeText:
    voting_groups = defaultdict(list)

    if isinstance(resource_or_usage, models.Resource):
        resource = resource_or_usage
        usage = None
    elif isinstance(resource_or_usage, models.ResourceUsage):
        resource = resource_or_usage.resource
        usage = resource_or_usage
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

    for manager_user, manager in resource.get_managers():
        voting_groups[manager.voting_group].append(
            (manager_user, votes.get(manager_user), manager))

    context = {}
    context["resource"] = resource
    context["informed"] = voting_groups.pop("", [])
    context["voting_groups"] = sorted(voting_groups.items())
    context["admins"] = resource.get_admins()

    return mark_safe(loader.render_to_string(
        "reservierung/_resource_approval_scheme.html", context))
