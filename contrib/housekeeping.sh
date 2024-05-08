#!/bin/sh

# Check if database is available and schedule rerun later if not
if ! ./manage.py showmigrations >/dev/null 2>&1; then
        echo "⚠️ Database is unreachable, skip this housekeeping"
        exit 1
fi

if ./manage.py showmigrations --plan 2>/dev/null | grep -F "[ ]" >/dev/null; then
        echo "⚠️ Migrations are still open, skip this housekeeping"
        ./manage.py showmigrations --plane
        exit 2
fi

echo "$(date) | Starting Housekeeping"
./manage.py clearsessions
echo "$(date) | Finished Housekeeping"

