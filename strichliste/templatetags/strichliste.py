from django import template
from django.urls import reverse

from ..booking import format_cents

register = template.Library()


@register.filter
def euro(cents):
    return format_cents(int(cents or 0))


@register.filter
def euro_signed(cents):
    return format_cents(int(cents or 0), signed=True)


@register.filter
def balance_class(cents):
    return "text-danger" if cents < 0 else "text-success" if cents > 0 else ""


@register.simple_tag(takes_context=True)
def sl_url(context, name, *args):
    """Wie {% url %}, zeigt auf dem Theken-Tablet aber auf die Tablet-Variante der Seite."""
    token = getattr(context["request"], "tablet_token", None)
    if token:
        return reverse(f"strichliste:tablet_{name}", args=[token, *args])
    return reverse(f"strichliste:{name}", args=args)
