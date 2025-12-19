from datetime import timedelta

import requests

from .models import CacheItem


@CacheItem.cache(expiration=timedelta(minutes=5))
def query_polls(polls_url):
    return requests.get(polls_url, headers={"Accept": "application/json"}).json()["ocs"]["data"]["polls"]
