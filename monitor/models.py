from datetime import timedelta
from functools import wraps
from contextlib import suppress
import hashlib

from django.db import models
from django.utils import timezone


class CacheItem(models.Model):
    key = models.CharField(max_length=64, unique=True)
    expires = models.DateTimeField()
    value = models.JSONField(default=None, null=True)

    # Note that receiving a TemporaryFailure with error_value None is different from receiving no error
    has_error = models.BooleanField(default=False)
    error_value = models.JSONField(default=None, null=True)

    class TemporaryFailure(Exception):
        def __init__(self, error_value, retry_after) -> None:
            self.error_value = error_value
            self.retry_after = retry_after

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
                    try:
                        result = func(*args, **kwargs)
                    except cls.TemporaryFailure as error:
                        update_kwargs = {
                            "has_error": True,
                            "error_value": error.error_value,
                            "expires": timezone.now() + error.retry_after,
                        }
                    else:
                        update_kwargs = {
                            "value": result,
                            "has_error": False,
                            "expires": timezone.now() + expiration,
                        }

                    item, _ = cls.objects.update_or_create(
                        key=key,
                        defaults=update_kwargs,
                    )

                if item.has_error:
                    return item.error_value

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
