#!/bin/ash
# see https://www.shellcheck.net/wiki/SC2187
# shellcheck shell=dash

# This script is taken from the docker netbox project

# Stop when an error occurs
set -e

echo "⚙️ Starting nginx unit"

UNIT_SOCKET="/tmp/unitd/socket"
UNIT_CONFIG="/tmp/unitd/config.json"
UNIT_PIDFILE="/tmp/unitd/pid"

mkdir -p "$(dirname "${UNIT_SOCKET}")" "$(dirname "${UNIT_CONFIG}")" "$(dirname "${UNIT_PIDFILE}")"

# Generate unitd-configuration
cat >"${UNIT_CONFIG}" <<EOT
{
  "listeners": {
    "0.0.0.0:$PORT": {
      "pass": "routes/main",
      "forwarded": {
        "source": ["172.16.0.0/12"],
        "client_ip": "X-Forwarded-For",
        "protocol": "X-Forwarded-Proto"
      }
    }
  },
  "routes": {
    "main": [
      {
        "match": {
          "uri": ["/static/*", "/favicon.ico"]
        },
        "action": {
          "share": "/opt/static\$uri",
        }
      },
      {
        "action": {
          "pass": "applications/app",
        }
      }
    ]
  },
  "applications": {
    "app": {
      "type": "python 3",
      "path": "/opt/app",
      "module": "kantine.wsgi",
      "home": "/opt/venv",
      "prefix": "/",
      "processes": {
        "max": 10,
        "spare": 3,
        "idle_timeout": 20
      }
    }
  },
  "settings": {
    "http": {
      "server_version": false
    }
  },
  "access_log": "/dev/stdout"
}
EOT

load_configuration() {
	MAX_WAIT=10
	WAIT_COUNT=0
	while [ ! -S $UNIT_SOCKET ]; do
		if [ $WAIT_COUNT -ge $MAX_WAIT ]; then
			echo "⚠️ No control socket found; configuration will not be loaded."
			return 1
		fi

		WAIT_COUNT=$((WAIT_COUNT + 1))
		echo "⏳ Waiting for control socket to be created... (${WAIT_COUNT}/${MAX_WAIT})"

		sleep 1
	done

	# even when the control socket exists, it does not mean unit has finished initialization
	# this curl call will get a reply once unit is fully launched
	curl --silent --output /dev/null --request GET --unix-socket $UNIT_SOCKET http://localhost/

	echo "⚙️ Applying configuration to nginx unit"

	RESP_CODE=$(
		curl \
			--silent \
			--output /tmp/unitd/unitd_config_error \
			--write-out '%{http_code}' \
			--request PUT \
			--data-binary "@${UNIT_CONFIG}" \
			--unix-socket "${UNIT_SOCKET}" \
			http://localhost/config
	)
	if [ "$RESP_CODE" != "200" ]; then
		echo "⚠️ Could no load Unit configuration (code $RESP_CODE)"
		cat /tmp/unitd/unitd_config_error
		kill "$(cat ${UNIT_PIDFILE})"
		return 1
	fi
	rm "${UNIT_CONFIG}"
	echo "✅ Unit configuration loaded successfully"
	echo "🏁 System is ready for connections"
}

load_configuration &

mkdir -p "/tmp/unitd/tmp" "/tmp/unitd/state"

# Start unitd
exec unitd \
	--no-daemon \
	--control "unix:${UNIT_SOCKET}" \
	--pid "${UNIT_PIDFILE}" \
	--log /dev/stdout \
	--statedir /tmp/unitd/state/ \
	--tmpdir /tmp/unitd/tmp/
