from datetime import datetime, timedelta

from django import template
from django.utils import timezone
from django.template.defaultfilters import pluralize

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


TIMEDELTA_FORMATS = [
    (lambda delta: delta.days, timedelta(hours=36), "Tag,Tage"),
    (lambda delta: delta.seconds // 3600, timedelta(hours=2), "Stunde,Stunden"),
    (lambda delta: delta.seconds // 60, timedelta(minutes=2), "Minute,Minuten"),
    (lambda delta: delta.seconds, timedelta(seconds=10), "Sekunde,Sekunden"),
]

@register.simple_tag
def timedelta_until(end: datetime) -> str:
    delta = timezone.now() - end

    for formater, threshold, units in TIMEDELTA_FORMATS:
        if delta > threshold:
            result = formater(delta)
            return f"noch {result} {pluralize(result, units)}"
    return "bis gleich"
