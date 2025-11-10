from . import models


def send_hermine_channel(channel_name: str, message: str) -> None:
    models.HermineChannelMessage.objects.create(
        channel=channel_name, message=message)


def send_hermine_user(user_name: str, message: str) -> None:
    models.HermineUserMessage.objects.create(
        user=user_name, message=message)
