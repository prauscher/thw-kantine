#!/bin/sh

curl http://localhost:${PORT}/healthcheck/ || exit 1

python3 /opt/app/manage.py send_hermine
