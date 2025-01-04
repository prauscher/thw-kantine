from . import models
from kantine.hermine import get_hermine_client


def send_hermine_channel(channel_name: str, message: str) -> None:
    models.HermineChannelMessage.objects.create(
        channel=channel_name, message=message)
