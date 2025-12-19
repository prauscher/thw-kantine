from django.utils import timezone

from . import models


def get_next_usages(**kwargs):
    # "open" resources are those which are selectable and have no manager with a voting group
    open_resources = models.Resource.objects.filter(selectable=True, **kwargs).exclude(
        managers__voting_group__regex=".+",
    ).order_by("label")

    next_usages = []
    for resource in open_resources:
        sort_key = tuple(reversed([parent.label for parent in resource.traverse_up()]))
        next_usage = resource.get_next_usage()
        if next_usage is None:
            blocked = False
            until = None
        else:
            blocked = next_usage.termin.start <= timezone.now()
            until = next_usage.termin.end if blocked else next_usage.termin.start

        next_usages.append((sort_key, resource, blocked, until))

    next_usages.sort()

    indents = ()
    for usage_sort_key, *next_usage in next_usages:
        # find longest match
        for i, indent_sort_key in reversed(list(enumerate(indents, 1))):
            if usage_sort_key[:len(indent_sort_key)] == indent_sort_key:
                indent = i
                break
        else:
            indent = 0
        indents = indents[:indent] + (usage_sort_key,)

        yield indent, *next_usage
