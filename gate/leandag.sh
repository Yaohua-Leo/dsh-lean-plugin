#!/usr/bin/env bash
# leandag.sh — thin launcher for leandag.py (the statement DAG and its queue).
#
# All logic lives in ../leandag.py so this wrapper and leandag.ps1 cannot drift.
# Reads coord/nodes.jsonl, derives reachability from the targets, the pruning
# candidates, readiness and the distance ordering, cross-checks the newest gate
# report, and writes coord/queue.tsv + coord/queue.md.
#
# Exit 1 means the DAG is structurally broken (cycle, unknown dependency,
# duplicate id, no target); exit 2 means there is no node file yet.
#
# Usage:
#   bash scripts/leandag.sh
#   bash scripts/leandag.sh --state
#   bash scripts/leandag.sh --nodes coord/other.jsonl
set -uo pipefail

PROJECT="$PWD"
NODES=""
EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --nodes) NODES="$2"; shift 2 ;;
    --state|--json) EXTRA+=("$1"); shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "leandag: unknown argument: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE="$SCRIPT_DIR/../leandag.py"
if [ ! -f "$CORE" ]; then echo "leandag: core not found: $CORE" >&2; exit 2; fi

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then echo "leandag: python3 (or python) is required" >&2; exit 2; fi

if [ -n "$NODES" ]; then
  "$PYTHON" "$CORE" --project "$PROJECT" --nodes "$NODES" ${EXTRA[@]+"${EXTRA[@]}"}
else
  "$PYTHON" "$CORE" --project "$PROJECT" ${EXTRA[@]+"${EXTRA[@]}"}
fi
