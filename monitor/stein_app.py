import json
import os
from datetime import timedelta

from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import requests

from .models import CacheItem


# 60 minutes is valid as we have webhooks to invalidate between
@CacheItem.cache(expiration=timedelta(minutes=60))
def query_stein_assets(bu_id: int, /):
    result = requests.get(
        "https://stein.app/api/api/ext/assets/",
        params={"buIds": str(bu_id)},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {os.environ['STEIN_API_KEY']}",
            "Accept": "application/json",
        },
    )
    return result.json()


@csrf_exempt
def view_webhook(request):
    if request.headers.get("X-Secret", "") != os.environ.get("STEIN_WEBHOOK_SECRET", ""):
        raise Http404

    data = json.load(request)

    for item in data["items"]:
        if item["type"] == "bu" and item["action"] == "update":
            query_stein_assets.invalidate(item["id"])
            query_stein_assets(item["id"])

    return JsonResponse({})
