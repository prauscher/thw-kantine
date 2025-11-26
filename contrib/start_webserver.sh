#!/bin/sh

BIND_HOST="${BIND_HOST:-"0.0.0.0"}"
export GRANIAN_WORKERS="${GRANIAN_WORKERS:-5}"

echo -e "Starting Granian on \033[96m${BIND_HOST}\033[0m:\033[96m${PORT}\033[0m"

export STATIC_URL="/static/"

exec granian \
	--host "${BIND_HOST}" \
	--port "${PORT}" \
	--static-path-route "${STATIC_URL%"/"}" \
	--static-path-mount "${STATIC_ROOT}" \
	--interface wsgi \
	--no-ws \
	kantine.wsgi:application
