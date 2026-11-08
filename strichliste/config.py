"""Einstellungen der Strichliste, alle per Umgebungsvariable."""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Config:
    tablet_pin: str
    transfers_enabled: bool
    paypal_link: str
    warn_below: int
    hard_limit: int
    undo_minutes: int
    tablet_idle_seconds: int
    stale_days: int
    deposit_list: list[int]


def get() -> Config:
    return Config(
        tablet_pin=os.environ.get("STRICHLISTE_TABLET_PIN", ""),
        transfers_enabled=os.environ.get("STRICHLISTE_TRANSFERS", "0")[:1].lower() in ("y", "t", "1"),
        paypal_link=os.environ.get("STRICHLISTE_PAYPAL_LINK", ""),
        warn_below=_int("STRICHLISTE_WARN_BELOW", -4000),
        hard_limit=_int("STRICHLISTE_HARD_LIMIT", -20000),
        undo_minutes=_int("STRICHLISTE_UNDO_MINUTES", 5),
        tablet_idle_seconds=_int("STRICHLISTE_TABLET_IDLE_SECONDS", 30),
        stale_days=_int("STRICHLISTE_STALE_DAYS", 100),
        deposit_list=[int(step) for step in os.environ.get("STRICHLISTE_DEPOSIT_STEPS", "10,50,100,200,500,1000").split(",") if step.strip()],
    )
