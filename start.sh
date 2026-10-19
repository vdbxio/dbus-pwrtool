#!/bin/bash
# Run from /data/rc.local at every boot. /service is a tmpfs, so the service is recreated each time.
# Add this line to /data/rc.local:
#   bash /data/apps/dbus-pwrtool/start.sh >> /data/apps/dbus-pwrtool/start.log 2>&1 &
S=/service/dbus-pwrtool
if [ ! -d "$S" ]; then
    T=$(mktemp -d /tmp/pwrtool.XXXXXX)
    cp -r /data/apps/dbus-pwrtool/service/. "$T"
    mv "$T" "$S"
fi
