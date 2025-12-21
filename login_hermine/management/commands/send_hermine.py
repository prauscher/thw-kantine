from functools import cached_property
from typing import Any
from django.core.management.base import BaseCommand
from django.utils import timezone
from kantine.hermine import get_hermine_client
from login_hermine import models


class ConnectionFailedError(ValueError):
    pass


class TargetNotFoundError(ValueError):
    pass


class HermineClient:
    def __init__(self):
        self.client = get_hermine_client()
        self.channels = [channel
                         for company in self.client.get_companies()
                         for channel in self.client.get_channels(company["id"])]

        if self.client is None:
            raise ConnectionFailedError

    def find_channel(self, channel_name):
        try:
            channel_attrs = next(channel
                                 for channel in self.channels
                                 if channel["name"] == channel_name)
        except StopIteration:
            raise TargetNotFoundError from None

        return ("channel", channel_attrs["id"])

    def find_user(self, name):
        results = self.client.search_user(name)
        if len(results) != 1:
            raise TargetNotFoundError
        conversation = self.client.open_conversation(results)
        return ("conversation", conversation["id"])

    def send(self, target, *args, **kwargs):
        return self.client.send_msg(target, *args, **kwargs)


class Command(BaseCommand):
    help = "Send Hermine Messages in Queue and cleanup done ones"

    @cached_property
    def hermine_client(self):
        return HermineClient()

    def handle(self, **_kwargs: dict[str, Any]) -> None:
        try:
            for message in models.HermineChannelMessage.objects.filter(sent__isnull=True, delay__lte=timezone.now()):
                try:
                    self.hermine_client.send(self.hermine_client.find_channel(message.channel),
                                             message.message)
                except TargetNotFoundError:
                    message.delay = timezone.now() + timedelta(minutes=15)
                    message.error = "Target not found"
                    message.save(update_fields=["delay", "error"])
                else:
                    message.sent = timezone.now()
                    message.save(update_fields=["sent"])

            for message in models.HermineUserMessage.objects.filter(sent__isnull=True, delay__lte=timezone.now()):
                try:
                    self.hermine_client.send(self.hermine_client.find_user(message.user),
                                             message.message)
                except TargetNotFoundError:
                    message.delay = timezone.now() + timedelta(minutes=15)
                    message.error = "Target not found"
                    message.save(update_fields=["delay", "error"])
                else:
                    message.sent = timezone.now()
                    message.save(update_fields=["sent"])

        except ConnectionFailedError:
            self.stderr.write("Hermine Login failed\n")

        models.HermineChannelMessage.objects.filter(sent__lt=timezone.now() - timezone.timedelta(days=1)).delete()
        models.HermineUserMessage.objects.filter(sent__lt=timezone.now() - timezone.timedelta(days=1)).delete()
