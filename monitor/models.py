from datetime import timedelta
from functools import wraps
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

            @wraps(func)
            def wrapper(*args, **kwargs):
                key = _build_cache_key(args, kwargs)
                try:
                    item = cls.objects.get(
                        key=key,
                        expires__gte=timezone.now()
                    )
                except cls.DoesNotExist:
                    result = func(*args, **kwargs)
                    item, _ = cls.objects.update_or_create(
                        key=key,
                        defaults={
                            "expires": timezone.now() + expiration,
                            "value": result,
                        }
                    )

                return item.value

            def _invalidate(*args, **kwargs):
                key = _build_cache_key(args, kwargs)
                cls.objects.filter(key=key).delete()

            wrapper.invalidate = _invalidate
            return wrapper

        return decorator
