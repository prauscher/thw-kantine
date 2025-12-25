from datetime import timedelta
from functools import wraps
from contextlib import suppress
import hashlib

from django.db import models
from django.utils import timezone


class CacheItem(models.Model):
    key = models.CharField(max_length=64, unique=True)
    expires = models.DateTimeField()
    value = models.JSONField()

    @classmethod
    def cache(cls, expiration: timedelta):
        def decorator(func):
            def _build_cache_key(args, kwargs):
                key = f"{func.__qualname__}#{args}#{sorted(kwargs.items())}"
                return hashlib.sha256(key.encode()).hexdigest()

            func._update_handlers = []

            @wraps(func)
            def wrapper(*args, force_update = False, **kwargs):
                key = _build_cache_key(args, kwargs)
                item = None
                old_value = None
                with suppress(cls.DoesNotExist):
                    item = cls.objects.get(key=key)
                    old_value = item.value

                if force_update or item is None or item.expires < timezone.now():
                    result = func(*args, **kwargs)
                    item, _ = cls.objects.update_or_create(
                        key=key,
                        defaults={
                            "expires": timezone.now() + expiration,
                            "value": result,
                        }
                    )

                if old_value != item.value:
                    for update_handler in func._update_handlers:
                        update_handler(args, kwargs, old_value, item.value)

                return item.value

            def _add_update_handler(handler):
                func._update_handlers.append(handler)
                return handler

            wrapper.on_update = _add_update_handler
            return wrapper

        return decorator
