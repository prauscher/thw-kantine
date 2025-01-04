import os
from typing import Any
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver
from django.http import HttpRequest
from django.contrib.auth.models import User
from kantine.hermine import get_hermine_client


def _send_msg(message: str) -> None:
    hermine_channel = os.environ.get("LOGIN_HERMINE_CHANNEL")
    if not hermine_channel:
        return

    hermine_client = get_hermine_client()
    if not hermine_client:
        return

    channel = next(channel
                   for company in hermine_client.get_companies()
                   for channel in hermine_client.get_channels(company["id"])
                   if channel["name"] == hermine_channel)
    hermine_client.send_msg(("channel", channel["id"]), message)


@receiver(user_logged_in)
def handle_successful_login(request: HttpRequest, user: User,
                            **_kwargs: Any) -> None:
    _send_msg(f"User {user} logged in from {request.META.get('REMOTE_ADDR')}")


@receiver(user_login_failed)
def handle_failed_login(request: HttpRequest, credentials: dict,
                        **_kwargs: Any) -> None:
    _send_msg(f"Login from {request.META.get('REMOTE_ADDR')} failed: {credentials}")


@receiver(user_logged_out)
def handle_logout(request: HttpRequest, user: User,
                  **_kwargs: Any) -> None:
    _send_msg(f"User {user} logged out from {request.META.get('REMOTE_ADDR')}")
