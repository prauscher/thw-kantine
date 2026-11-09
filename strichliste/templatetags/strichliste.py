from django import template

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
