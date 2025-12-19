from datetime import datetime, timedelta

from caldav.davclient import DAVClient
import icalendar

from .models import CacheItem


@CacheItem.cache(expiration=timedelta(minutes=5))
def query_calendar(caldav_url, count):
    with DAVClient() as client:
        cal = client.calendar(url=caldav_url)
        cal_events = cal.search(
            start=datetime.now(),
            end=datetime.now() + timedelta(days=90),  # will use only first count items
            event=True,
            expand=True,
            sort_keys=("dtstart",)
        )

    events = []
    for cal_event in cal_events:
        event = icalendar.Calendar.from_ical(cal_event.data).events[0]

        events.append({
            "summary": str(event.get("SUMMARY") or ""),
            "start": event.start.isoformat(),
            "end": event.end.isoformat(),
            "location": str(event.get("LOCATION") or ""),
            "categories": list(event.get("CATEGORIES") or []),
            "comment": str(event.get("DESCRIPTION") or ""),
        })

        count -= 1
        if count <= 0:
            break

    return events
