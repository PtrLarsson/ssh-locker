#!/bin/sh
exec "${SSH_LOCKER_PYTHON:-python3}" "$(dirname "$0")/askpass.py" "$@"
