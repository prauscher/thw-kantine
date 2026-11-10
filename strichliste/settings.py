"""Einstellungen der Strichliste, aus den Django-Settings oder per Umgebungsvariable."""
import os

from django.conf import settings


def _setting(name: str, default: str) -> str:
    return getattr(settings, name, os.environ.get(name, default))


# Theken-Tablet unter /strichliste/tablet/<PIN>/, ohne PIN gibt es keinen Tablet-Zugang
TABLET_PIN = _setting("STRILI_TABLET_PIN", "")
TRANSFERS_ENABLED = str(_setting("STRILI_TRANSFERS", "0"))[:1].lower() in ("y", "t", "1")
PAYPAL_LINK = _setting("STRILI_PAYPAL_LINK", "")
# Beträge in Cent
WARN_BELOW = int(_setting("STRILI_WARN_BELOW", "-4000"))
HARD_LIMIT = int(_setting("STRILI_HARD_LIMIT", "-20000"))
DEPOSIT_STEPS = [int(step) for step in str(_setting("STRILI_DEPOSIT_STEPS", "10,50,100,200,500,1000")).split(",") if step.strip()]
UNDO_MINUTES = int(_setting("STRILI_UNDO_MINUTES", "5"))
TABLET_IDLE_SECONDS = int(_setting("STRILI_TABLET_IDLE_SECONDS", "30"))
STALE_DAYS = int(_setting("STRILI_STALE_DAYS", "100"))
