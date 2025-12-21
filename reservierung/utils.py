from collections.abc import Iterator
from datetime import datetime

from django.db.models import QuerySet
from django.utils import timezone

from . import models


def get_next_usages(resources: QuerySet[models.Resource],
                    ) -> Iterator[tuple[models.Resource, models.ResourceUsage | None, bool, datetime | None]]:
    next_usages = []
    for resource in resources:
        next_usage = resource.get_next_usage()
        if next_usage is None:
            blocked = False
            until = None
        else:
            blocked = next_usage.termin.start <= timezone.now()
            until = next_usage.termin.end if blocked else next_usage.termin.start

        yield resource, next_usage, blocked, until
