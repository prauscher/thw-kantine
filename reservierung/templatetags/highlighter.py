from django import template
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter("highlighter")
def highlighter_filter(value, words):
    value = str(value)

    matches = []
    haystack = _normalize(value)
    for word in words:
        needle = _normalize(word)
        try:
            match = -1
            while True:
                match = haystack.index(needle, match + 1)
                matches.append((match, match + len(needle)))
        except ValueError:
            pass

    # Find overlapping highlights
    matches.sort()
    new_matches = []
    current_start = -1
    current_end = 0
    for start, end in matches:
        # Iff we are in the same zone, extend selection
        if start < current_end:
            current_end = max(current_end, end)
        else:
            if current_start >= 0:
                new_matches.append((current_start, current_end))
            current_start = start
            current_end = end
    if current_start >= 0:
        new_matches.append((current_start, current_end))

    pos = 0
    result = mark_safe("")
    for start, end in new_matches:
        result += format_html("{}<mark>{}</mark>", value[pos:start], value[start:end])
        pos = end

    result += conditional_escape(value[pos:])

    return result


def _normalize(value):
    # May not alter the length of value
    value = value.lower()
    for search, replace in [("ä", "a"), ("ö", "o"), ("ü", "u")]:
        value = value.replace(search, replace)
    return value
