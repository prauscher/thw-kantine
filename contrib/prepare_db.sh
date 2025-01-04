#!/bin/ash
# see https://www.shellcheck.net/wiki/SC2187
# shellcheck shell=dash

# Runs on every start of the Docker container
# This script is taken from the docker netbox project

# Stop when an error occurs
set -e

# Allow to be run as non-root users
umask 002

# shellcheck disable=SC3036
echo "$(date +'%Y/%m/%d %H:%M:%S') 🖐 Starting Application"

# Try to connect to the DB
echo "$(date +'%Y/%m/%d %H:%M:%S') ⏳ Connecting to DB..."
DB_WAIT_TIMEOUT=${DB_WAIT_TIMEOUT-3}
MAX_DB_WAIT_TIME=${MAX_DB_WAIT_TIME-30}
CUR_DB_WAIT_TIME=0
while true; do
	if [ "${CUR_DB_WAIT_TIME}" -ge "${MAX_DB_WAIT_TIME}" ]; then
		echo "$(date +'%Y/%m/%d %H:%M:%S') ❌ Waited ${MAX_DB_WAIT_TIME}s or more for the DB to become ready."
		exit 1
	fi

	# Read and truncate connection error tracebacks to last line by default
	DB_ERR=$(./manage.py showmigrations 2>&1) && break
	echo "$(date +'%Y/%m/%d %H:%M:%S') ⏳ Waiting on DB... (${CUR_DB_WAIT_TIME}s / ${MAX_DB_WAIT_TIME}s), last error:"
	if [ -n "$DB_WAIT_DEBUG" ]; then
		echo "$DB_ERR"
	else
		tail -n 1 <<EOT
${DB_ERR}
EOT
		echo "[ Use DB_WAIT_DEBUG=1 to print full traceback for errors here ]"
	fi
	sleep "${DB_WAIT_TIMEOUT}"
	CUR_DB_WAIT_TIME=$((CUR_DB_WAIT_TIME + DB_WAIT_TIMEOUT))
done

# Check if update is needed
if ! ./manage.py migrate --check >/dev/null 2>&1; then
	echo "$(date +'%Y/%m/%d %H:%M:%S') ⚙️ Applying database migrations"
	./manage.py migrate --no-input
	echo "$(date +'%Y/%m/%d %H:%M:%S') ⚙️ Removing stale content types"
	./manage.py remove_stale_contenttypes --no-input
	echo "$(date +'%Y/%m/%d %H:%M:%S') ⚙️ Removing expired user sessions"
	./manage.py clearsessions
fi

# Create Superuser if required
if [ "$SKIP_SUPERUSER" = "true" ]; then
	echo "$(date +'%Y/%m/%d %H:%M:%S') ↩️ Skip creating the superuser"
else
	if [ -z ${SUPERUSER_PASSWORD+x} ] && [ -f "/run/secrets/superuser_password" ]; then
		echo "$(date +'%Y/%m/%d %H:%M:%S') ⚙️ Reading SUPERUSER_PASSWORD from Docker Secrets"
		SUPERUSER_PASSWORD="$(cat /run/secrets/superuser_password)"
	fi

	./manage.py shell --interface python <<END
import datetime
import os
from django.contrib.auth.models import User

superuser_name = os.environ.get("SUPERUSER_NAME", "admin")
superuser_email = os.environ.get("SUPERUSER_EMAIL", "admin@example.com")
superuser_password = os.environ.get("SUPERUSER_PASSWORD", "admin")

if User.objects.filter(username=superuser_name).exists():
    print(f'{datetime.now().format("%Y/%m/%d %H:%M:%S")} ↩️ Superuser \033[96m{superuser_name}\033[0m already exists, skip creation')
    exit()

if User.objects.exists():
    print(f'{datetime.now().format("%Y/%m/%d %H:%M:%S")} ↩️ Skip creating of superuser, as other users already exist')
    exit()

User.objects.create_superuser(superuser_name, superuser_email, superuser_password)
print(f'{datetime.now().format("%Y/%m/%d %H:%M:%S")} 💡 Superuser \033[96m{superuser_name}\033[0m created')
END
fi

echo "$(date +'%Y/%m/%d %H:%M:%S') ✅ Initialization is done."

exec "$@"
