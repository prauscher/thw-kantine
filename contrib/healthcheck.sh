#!/bin/sh

# use empty Host-header to hide message in access log
curl -H "Host: " -s http://localhost:${PORT}/healthcheck/ > /dev/null || exit 1

# run housekeeping only once a day
if [ ! -f /tmp/_housekeeping ] || [ $(( $(date +%s) - $(stat -c "%Y" /tmp/_housekeeping) )) -gt 86400 ]; then
	/housekeeping.sh
	touch /tmp/_housekeeping
elif [ ! -f /tmp/_background ]; then
	touch /tmp/_background

	# avoid timeout, so only run housekeeping or these jobs
	python3 /opt/app/manage.py send_hermine

	rm /tmp/_background
fi

