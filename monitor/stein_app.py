import json
import os
from collections import defaultdict
from datetime import timedelta

from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import requests

from login_hermine.utils import send_hermine_channel
from .models import CacheItem


STEIN_GROUPS = {
    1: "Fahrzeuge",
    2: "Geräte",
    3: "Sonderfunktionen",
    4: "(Teil-)Einheiten",
    5: "Anhänger",
}

STEIN_STATES = {
    "ready": "Einsatzbereit",
    "notready": "Nicht einsatzbereit",
    "semiready": "Bedingt einsatzbereit",
    "inuse": "Im Einsatz",
    "maint": "In der Werkstatt",
}


def _query_stein(url, **kwargs):
    return requests.get(
        url,
        **kwargs,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {os.environ['STEIN_API_KEY']}",
            "Accept": "application/json",
        },
    ).json()


# 60 minutes is valid as we have webhooks to invalidate between
@CacheItem.cache(expiration=timedelta(minutes=60))
def query_stein_assets(bu_id: int, /):
    return _query_stein(
        "https://stein.app/api/api/ext/assets/",
        params={"buIds": str(bu_id)},
    )


@query_stein_assets.on_update
def update_stein_assets(args, kwargs, old_data, new_data):
    if old_data is None:
        return

    hermine_gruppe = os.environ.get("LUK_HERMINE_CHANNEL")
    if not hermine_gruppe:
        return

    old_assets = {asset["id"]: asset for asset in old_data}
    new_assets = {asset["id"]: asset for asset in new_data}
    combined = {
        asset_id: (old_assets.get(asset_id), new_assets.get(asset_id))
        for asset_id in set().union(old_assets, new_assets)
    }

    changes = defaultdict(list)
    for asset_id, (old, new) in combined.items():
        if new is None:
            changes["Gelöscht"].append(f"{old['label']} ({old['category']}).")
            continue

        asset_label = f"{new['label']} ({new['category']})"

        if old is None:
            changes[f"Von {new['lastModifiedBy']} angelegt"].append(
                f"{asset_label} unter {STEIN_GROUPS[new['groupId']]} im Status"
                f" {STEIN_STATES[new['status']]}"
                f"{' (mit Einsatzvorbehalt)' if new.get('operationReservation', False) else ''}"
                f" neu angelegt"
                f"{'.' if not new['comment'] else f': {new['comment']}'}."
            )
            continue

        reservation = ""
        if not old.get("operationReservation", False) and new.get("operationReservation", False):
            reservation = "Neu unter Einsatvorbehalt gesetzt"
        elif old.get("operationReservation", False) and not new.get("operationReservation", False):
            reservation = "Einsatzvorbehalt entfernt"
        elif new.get("operationReservation", False):
            reservation = "Unter Einsatzvorbehalt"

        comment_note = "kein Kommentar angegeben" if not new["comment"] else f"Kommentar: {new['comment']}"

        if old["status"] != new["status"]:
            changes[f"Von {new['lastModifiedBy']} in Status {STEIN_STATES[new['status']]} versetzt"].append(
                f"{asset_label} (von {STEIN_STATES[old['status']]}, "
                f"{'kein Kommentar angegeben' if not new['comment'] else f'Kommentar: {new['comment']}'})"
                f"{f' - {reservation}' if reservation else ''}."
            )
        elif old.get("operationReservation", False) != new.get("operationReservation", False):
            changes[f"Von {new['lastModifiedBy']} {reservation}"].append(
                f"{asset_label} - {'kein Kommentar angegeben' if not new['comment'] else f'Kommentar: {new['comment']}'}"
            )
        elif old["comment"] != new["comment"]:
            changes[f"Kommentar von {new['lastModifiedBy']} geändert"].append(
                f"Für {asset_label} von {old['comment'] or '(ohne)'} zu "
                f"{new['comment'] or '(ohne)'}."
            )

    if not changes:
        return

    change_message = "\n".join(
        f"{change_type}:\n{'\n'.join(f' - {change_info}' for change_info in change_infos)}\n"
        for change_type, change_infos in changes.items()
    )
    send_hermine_channel(hermine_gruppe, f"[STEIN.APP] {change_message}")


@csrf_exempt
def view_webhook(request):
    if request.headers.get("X-Secret", "") != os.environ.get("STEIN_WEBHOOK_SECRET", ""):
        raise Http404

    data = json.load(request)
    print("rcvd stein webhook", data, flush=True)

    for item in data["items"]:
        bu_id = None

        if item["type"] == "bu" and item["action"] == "update":
            bu_id = item["id"]

        if item["type"] == "asset" and item["action"] == "update":
            bu_id = _query_stein(item["url"])["buId"]

        if bu_id:
            query_stein_assets.invalidate(bu_id)
            query_stein_assets(bu_id)

    return JsonResponse({})
