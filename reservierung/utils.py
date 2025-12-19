from django.utils import timezone

from . import models


def get_next_usages(**kwargs):
    # "open" resources are those which are selectable and have no manager with a voting group
    open_resources = models.Resource.objects.filter(selectable=True, **kwargs).exclude(
        managers__voting_group__regex=".+",
    ).order_by("label")

    for resource in open_resources:
        next_usage = resource.get_next_usage()
        if next_usage is None:
            yield (
                resource,
                False,  # blocked
                None,  # until
            )
        else:
            blocked = next_usage.termin.start <= timezone.now()
            yield (
                resource,
                blocked,
                next_usage.termin.end if blocked else next_usage.termin.start,  # until
            )
