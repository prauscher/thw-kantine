"""Zugang zur Strichliste: Nextcloud-Login (JWT) oder Theken-Tablet.

Das Tablet ruft /strichliste/tablet/<PIN>/ auf, die PIN steht in
STRICHLISTE_TABLET_PIN. Ist sie nicht gesetzt, gibt es keinen Tablet-Zugang.
"""
import secrets
from functools import wraps

from django.http import Http404

from kantine.decorators import require_jwt_login

from . import config as conf
from .booking import Actor, own_account


def require_actor(view):
    """Setzt request.actor für Nextcloud-Benutzer und das Theken-Tablet.

    Views unter tablet/<pin>/ bekommen das Tablet, alle anderen den
    angemeldeten Nextcloud-Benutzer."""

    @wraps(view)
    def _view(request, *args, pin=None, **kwargs):
        if pin is None:
            return _jwt_view(request, *args, **kwargs)

        expected = conf.get().tablet_pin
        if not expected or not secrets.compare_digest(pin, expected):
            raise Http404

        request.actor = Actor(name="Theken-Tablet", is_tablet=True)
        request.tablet_pin = pin
        return view(request, *args, **kwargs)

    @require_jwt_login
    def _jwt_view(request, *args, **kwargs):
        request.actor = Actor(
            name=request.jwt_user_display,
            uid=request.jwt_user_id,
            account=own_account(request.jwt_user_id, request.jwt_user_display),
        )
        request.tablet_pin = None
        return view(request, *args, **kwargs)

    return _view
