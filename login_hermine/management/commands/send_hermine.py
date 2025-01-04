from typing import Any
from django.core.management.base import BaseCommand
from django.utils import timezone
from kantine.hermine import get_hermine_client
from login_hermine import models

class Command(BaseCommand):
    help = "Send Hermine Messages in Queue and cleanup done ones"

    def handle(self, **_kwargs: dict[str, Any]) -> None:
        client = None
        channels = None
        for message in models.HermineChannelMessage.objects.filter(sent__isnull=True):
            if client is None:
                client = get_hermine_client()
                channels = [channel
                            for company in client.get_companies()
                            for channel in client.get_channels(company["id"])]

            # send message
            if client is None:
                self.stderr.write("Hermine Login failed\n")
                break

            channel_attrs = next(channel
                                 for channel in channels
                                 if channel["name"] == message.channel)
            client.send_msg(("channel", channel_attrs["id"]), message.message)

            message.sent = timezone.now()
            message.save()

        models.HermineChannelMessage.objects.filter(sent__lt=timezone.now() - timezone.timedelta(days=1)).delete()
