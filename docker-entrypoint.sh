#!/bin/sh
# Adopt the data volume, then run the application as an unprivileged user.
#
# The image used to run everything as root. Dropping to a normal user with a plain USER
# directive would break every existing installation on upgrade: the data volume was created
# by root and the application would no longer be able to write to it, so the operator would
# have to chown it by hand before the container would start again. Starting as root,
# adopting the volume, and only then dropping privileges keeps the upgrade transparent.
#
# Nothing here is fatal. A read-only mount, NFS without no_root_squash, CIFS with a fixed
# uid/gid, and userns-remapping all legitimately refuse chown, and a permissions failure
# must not turn an upgrade into an outage. If the ownership cannot be changed the container
# still starts and the application reports the real error itself.
set -u

APP_USER="${IPMIDECK_USER:-ipmideck}"
DATA_DIR="${IPMIDECK_DATA_DIR:-/data}"

# Only root can hand the volume over and drop privileges. When the container is started
# with `docker run --user` or a compose `user:` key we are already unprivileged: the setpriv
# call would fail with EPERM and the container would never start, so exec straight through.
if [ "$(id -u)" = "0" ]; then
    if [ -d "$DATA_DIR" ]; then
        chown -R "$APP_USER:$APP_USER" "$DATA_DIR" 2>/dev/null ||
            echo "ipmideck: could not take ownership of $DATA_DIR — continuing" >&2
        chmod 700 "$DATA_DIR" 2>/dev/null || :
    fi
    # --init-groups so the process gets the user's supplementary groups; exec so uvicorn
    # replaces this shell as PID 1 and keeps receiving SIGTERM for a graceful shutdown.
    exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups "$@"
fi

exec "$@"
