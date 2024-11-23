from django import template
from django.utils.safestring import SafeText, mark_safe
from markdownx.utils import markdownify

register = template.Library()


@register.filter("markdownify")
def markdownify_filter(value: str) -> SafeText:
    return mark_safe(markdownify(value))
