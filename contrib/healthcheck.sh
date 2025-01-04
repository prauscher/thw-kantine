#!/bin/sh

# use empty Host-header to hide message in access log
curl -H "Host: " -s http://localhost:${PORT}/healthcheck/ > /dev/null || exit 1

python3 /opt/app/manage.py send_hermine
