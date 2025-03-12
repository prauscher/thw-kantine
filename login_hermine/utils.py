from . import models


def send_hermine_channel(channel_name: str, message: str) -> None:
    models.HermineChannelMessage.objects.create(
        channel=channel_name, message=message)
