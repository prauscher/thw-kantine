from datetime import timedelta

import requests

from .models import CacheItem


@CacheItem.cache(expiration=timedelta(minutes=2))
def query_announce(announce_url):
    return requests.get(announce_url).json()
