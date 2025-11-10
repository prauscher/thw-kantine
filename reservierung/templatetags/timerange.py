from datetime import datetime, timedelta

from django import template
from django.utils import timezone

register = template.Library()


@register.filter("timerange")
def timerange_filter(start: datetime, end: datetime) -> str:
    start = timezone.localtime(start)
    end = timezone.localtime(end)

    if end - start < timedelta(hours=12) or start.date() == end.date():
        return f"{start:%d.%m.%Y %H:%M} - {end:%H:%M}"
    if start.year == end.year and start.month == end.month:
        return f"{start:%d}. - {end:%m.%Y %H:%M}"
    return f"{start:%d.%m.Y} - {end:%d.%m.%Y}"


@register.simple_tag
def format_time_relative(relative: datetime, target: datetime) -> str:
    if relative.date() == target.date():
        return f"{target:%H:%M}"
    return f"{target:%d.%m.%Y %H:%M}"
