#!/usr/bin/env sh
# Launcher for the Lean formalization installer.
#
# All logic lives in install.py so the POSIX and PowerShell entry points cannot
# drift apart. This script only locates a Python 3 interpreter and forwards every
# argument, plus the exit code.
#
# Examples:
#   sh install/install.sh --dry-run
#   sh install/install.sh --project ~/lean-project --scope both
#   sh install/install.sh --uninstall
#   sh install/install.sh --doctor
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
script="$here/install.py"
[ -f "$script" ] || { echo "missing $script" >&2; exit 2; }

for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1; then
    exec "$candidate" "$script" "$@"
  fi
done

echo "no python interpreter found on PATH (tried: python3, python, py)" >&2
exit 2
