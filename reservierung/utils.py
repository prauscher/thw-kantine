from django.utils import timezone

from . import models


def get_next_usages(**kwargs):
    # "open" resources are those which are selectable and have no manager with a voting group
    open_resources = models.Resource.objects.filter(selectable=True, **kwargs).exclude(
        managers__voting_group__regex=".+",
    ).order_by("label")

    next_usages = []
    for resource in open_resources:
        next_usage = resource.get_next_usage()
        if next_usage is None:
            blocked = False
            until = None
        else:
            blocked = next_usage.termin.start <= timezone.now()
            until = next_usage.termin.end if blocked else next_usage.termin.start

        yield resource, next_usage, blocked, until
