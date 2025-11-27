from django import template
from django.utils.safestring import SafeText, mark_safe
from markdownx.utils import markdownify

register = template.Library()


@register.filter("markdownify")
def markdownify_filter(value: str) -> SafeText:
    return mark_safe(markdownify(value))


@register.filter("markdownify_inline")
def markdownify_inline_filter(value: str) -> SafeText:
    markdown = markdownify(value)

    # common case: python-markdown wraps everything in a single paragraph,
    # leading to strange line breaks
    if markdown.startswith("<p>") and "<p>" not in markdown[1:] and \
       markdown.endswith("</p>") and "</p>" not in markdown[:-1]:
        markdown = markdown[3:-4]

    return mark_safe(markdown)
