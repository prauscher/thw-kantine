"""
WSGI config for kantine project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application
from granian.utils.proxies import wrap_wsgi_with_proxy_headers

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kantine.settings')

application = get_wsgi_application()

application = wrap_wsgi_with_proxy_headers(
    application,
    trusted_hosts=os.environ.get("PROXY_SOURCE", "172.16.0.0/12").split(" "),
)
