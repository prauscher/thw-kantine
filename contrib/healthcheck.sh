#!/bin/sh

# use empty Host-header to hide message in access log
curl -H "Host: " -s http://localhost:${PORT}/healthcheck/ > /dev/null || exit 1

# run housekeeping only once a day
if [ ! -f /tmp/_housekeeping ] || [ $(( $(date +%s) - $(stat -c "%Y" /tmp/_housekeeping) )) -gt 86400 ]; then
	touch /tmp/_housekeeping

	/housekeeping.sh
# run only one background job at once
elif [ ! -f /tmp/_background ] || [ $(( $(date +%s) - $(stat -c "%Y" /tmp/_background) )) -gt 3600 ]; then
	touch /tmp/_background

	# avoid timeout, so only run housekeeping or these jobs
	python3 /opt/app/manage.py send_hermine

	rm /tmp/_background
fi

