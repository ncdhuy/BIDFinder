#!/usr/bin/env bash
set -Eeuo pipefail

# User journals are the only persistent service log sink. Keep the whole user
# journal bounded; service output never contains credentials.
journalctl --user --vacuum-time=14d --vacuum-size=250M >/dev/null
