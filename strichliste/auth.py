"""Zugang zur Strichliste: Nextcloud-Login (JWT) oder Theken-Tablet mit PIN.

Ein Tablet ruft /strichliste/tablet/<token>/ auf. Nach Eingabe der PIN wird ein
signiertes Cookie gesetzt, das jahrelang gültig bleibt. Damit kann das Tablet
dauerhaft angemeldet bleiben. Über die Verwaltung lässt sich der Zugang
sperren oder alle Geräte abmelden (session_version).
"""
from functools import wraps

from django.core import signing
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone

from kantine.decorators import require_jwt_login

from .booking import Actor, own_account
from .models import Tablet

COOKIE_SALT = "strichliste.tablet"
COOKIE_MAX_AGE = 5 * 365 * 24 * 3600


def cookie_name(tablet: Tablet) -> str:
    return f"strichliste_tablet_{tablet.pk}"


def cookie_value(tablet: Tablet) -> str:
    return f"{tablet.pk}:{tablet.session_version}"


def get_tablet(token: str) -> Tablet:
    try:
        return Tablet.objects.get(token=token, active=True)
    except Tablet.DoesNotExist as error:
        raise Http404 from error


def set_tablet_cookie(response, request, tablet: Tablet):
    response.set_signed_cookie(
        cookie_name(tablet), cookie_value(tablet), salt=COOKIE_SALT, max_age=COOKIE_MAX_AGE,
        httponly=True, secure=request.is_secure(), samesite="Lax",
    )


def tablet_unlocked(request, tablet: Tablet) -> bool:
    value = request.get_signed_cookie(cookie_name(tablet), default=None, salt=COOKIE_SALT, max_age=COOKIE_MAX_AGE)
    return value == cookie_value(tablet)


def require_actor(view):
    """Setzt request.actor für Nextcloud-Benutzer und freigeschaltete Tablets.

    Views unter tablet/<token>/ bekommen das Tablet, alle anderen den
    angemeldeten Nextcloud-Benutzer."""

    @wraps(view)
    def _view(request, *args, token=None, **kwargs):
        if token is None:
            return _jwt_view(request, *args, **kwargs)

        tablet = get_tablet(token)
        if not tablet_unlocked(request, tablet):
            return redirect("strichliste:tablet_pin", token=token)

        if tablet.last_seen_at is None or tablet.last_seen_at < timezone.now() - timezone.timedelta(minutes=5):
            Tablet.objects.filter(pk=tablet.pk).update(last_seen_at=timezone.now())

        request.actor = Actor(name=tablet.label, tablet=tablet)
        request.tablet_token = token
        return view(request, *args, **kwargs)

    @require_jwt_login
    def _jwt_view(request, *args, **kwargs):
        request.actor = Actor(
            name=request.jwt_user_display,
            uid=request.jwt_user_id,
            account=own_account(request.jwt_user_id, request.jwt_user_display),
        )
        request.tablet_token = None
        return view(request, *args, **kwargs)

    return _view


def require_admin(view):
    @wraps(view)
    @require_actor
    def _view(request, *args, **kwargs):
        if not request.actor.is_admin:
            raise Http404
        return view(request, *args, **kwargs)

    return _view
