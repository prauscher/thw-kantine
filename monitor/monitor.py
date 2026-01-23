import os
from datetime import date, datetime, timedelta

from django.utils import timezone

from reservierung.models import Resource
from reservierung.templatetags.timerange import daterange_filter, timerange_filter, timedelta_until
from .announce import query_announce
from .calendar import query_calendar
from .polls import query_polls
from .stein_app import query_stein_assets

COLORS = ["#f29633", "#ef6a31", "#ec2b2e", "#a12e65", "#572d91", "#1370b6", "#02a6e3", "#00a056"]
KNOWN_CATEGORIES = ["Schulferien", "Feiertage", "Bereichsausbildung", "Grundausbildung", "Ortsverband", "Helferverein", "Unterführer", "Jugend", "Veranstaltung"]


def _generate_color_selector():
    selected_colors = {cat: COLORS[i % len(COLORS)] for i, cat in enumerate(KNOWN_CATEGORIES)}

    def _cat_color(cat: str) -> str:
        selected_colors.setdefault(cat, COLORS[len(selected_colors) % len(COLORS)])
        return selected_colors[cat]

    return _cat_color


def build_announce():
    announce_url = os.environ.get("NC_ANNOUNCE_URL", "")
    if not announce_url:
        return None

    announces = query_announce(announce_url)
    return [
        {"message": announce["message"], "style": announce["variant"]}
        for announce in announces["banners"]
        if announce["enabled"] and announce["message"]
    ]


def build_termine():
    caldav_url = os.environ.get("MONITOR_CALDAV_URL", "")
    if not caldav_url:
        return []

    _cat_color = _generate_color_selector()

    events = []
    for event in query_calendar(caldav_url, 6):
        if len(event["start"]) == 10:
            start = date.fromisoformat(event["start"])
            # ical always specifies the end as the day after the next day
            end = date.fromisoformat(event["end"]) - timedelta(days=1)
            event["timerange"] = daterange_filter(start, end)
        else:
            start = datetime.fromisoformat(event["start"])
            end = datetime.fromisoformat(event["end"])
            event["timerange"] = timerange_filter(start, end)

        event["categories"] = [{"label": category, "color": _cat_color(category)}
                               for category in event["categories"]]

        events.append(event)

    return events


def build_stein():
    buid = os.environ.get("STEIN_BUID", "")
    if not buid.isnumeric():
        return []

    STEIN_STATES = {
        "inuse": (-120, "Im Einsatz", "primary"),
        "notready": (-100, "Nicht einsatzbereit", "danger"),
        "maint": (-70, "In der Werkstatt", "secondary"),
        "semiready": (-30, "Bedingt einsatzbereit", "warning"),
        # hide ready entries
        # "ready": (-10, "Einsatzbereit", "success"),
    }

    assets = []
    for asset in query_stein_assets(int(buid)):
        if asset["status"] not in STEIN_STATES:
            continue
        status_prio, status_label, status_color = STEIN_STATES[asset["status"]]

        assets.append((status_prio, {
            "label": asset["label"],
            "category": asset["category"],
            "status_label": status_label,
            "status_color": status_color,
            "comment": asset["comment"] or "",
        }))

    return [data for _, data in sorted(assets, key=lambda item: item[0])]


def build_polls():
    polls_url = os.environ.get("NC_POLLS_URL", "")
    if not polls_url:
        return []

    polls = []
    for poll in query_polls(polls_url):
        if poll["status"]["isArchived"]:
            continue

        last_interaction_ts = timezone.make_aware(datetime.fromtimestamp(poll["status"]["lastInteraction"]))

        expire = None
        if poll["configuration"]["expire"] > 0:
            expire_ts = timezone.make_aware(datetime.fromtimestamp(poll["configuration"]["expire"]))
            if expire_ts < timezone.now():
                continue

            expire = {
                "seconds": (expire_ts - timezone.now()).total_seconds(),
                "label": timedelta_until(expire_ts),
            }
        elif last_interaction_ts + timedelta(days=7) < timezone.now():
            continue

        # nextcloud gives empty list, but entries are dicts?!
        groups = list(dict(poll["currentUserStatus"]["groupInvitations"]).values())
        if "Ortsverband" not in groups:
            continue

        polls.append({
            "title": poll["configuration"]["title"],
            "created": poll["status"]["created"],
            "owner": poll["owner"]["displayName"],
            "expire": expire,
        })

    polls.sort(key=lambda poll: poll["created"])

    return polls


def build_reservierung():
    clusters = [
        (8, 9, 10),  # hof
        (17, 16, 12, 14, 13),  # unterrichtsraeume
        (24, 25),  # pkw und mtw ov
    ]

    resources = Resource.objects.filter(id__in=set().union(*clusters))

    usages = {}
    for resource in Resource.objects.filter(id__in=set().union(*clusters)):
        next_usage = resource.get_next_usage()
        if next_usage and next_usage.termin.start > timezone.now() + timedelta(hours=8):
            next_usage = None

        blocked = False
        until = None
        usage_label = ""
        if next_usage:
            blocked = next_usage.termin.start <= timezone.now()
            until = next_usage.termin.end if blocked else next_usage.termin.start
            usage_label = next_usage.termin.label

        usages[resource.pk] = {
            "resource": resource.label,
            "blocked": blocked,
            "until": timezone.localtime(until).strftime("bis %H:%M") if until else "",
            "usage_label": usage_label,
        }

    return [
        [usages[resource_id] for resource_id in cluster]
        for cluster in clusters
    ]


def query_infomonitor():
    return {
        "announce": build_announce(),
        "termine": build_termine(),
        "stein": build_stein(),
        "polls": build_polls(),
        "reservierung": build_reservierung(),
    }
