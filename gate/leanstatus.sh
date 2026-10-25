#!/usr/bin/env bash
# leanstatus.sh — what is left, without rebuilding anything (POSIX twin of leanstatus.ps1).
#
# Reads lean-formalization.json, the statement lock and the newest leancheck run
# under <evidenceDir>/runs/, then reports the state a human or an agent needs:
# whether the last gate run passed, which targets are locked, and which library
# declarations still rest on `sorryAx`.
#
# With --write-state it rewrites <project>/coord/STATE.md (current state, never
# appended) when the project has a coord/ directory, keeping any existing
# `## Plan` section. That file is the hand-off point for a human or the next
# session.
#
# python3 is required; `python` is accepted as a fallback (Git Bash on Windows
# ships no `python3`).
#
# Usage:
#   bash scripts/leanstatus.sh
#   bash scripts/leanstatus.sh --write-state
#   bash scripts/leanstatus.sh --config other.json
set -uo pipefail

CONFIG=lean-formalization.json
WRITE_STATE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --write-state) WRITE_STATE=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "leanstatus: unknown argument: $1" >&2; exit 2 ;;
  esac
done

PROJECT_ROOT="$PWD"
case "$CONFIG" in /*) CONFIG_PATH="$CONFIG" ;; *) CONFIG_PATH="$PROJECT_ROOT/$CONFIG" ;; esac
if [ ! -f "$CONFIG_PATH" ]; then echo "leanstatus: config not found: $CONFIG_PATH" >&2; exit 2; fi

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then
  echo "leanstatus: python3 (or python) is required" >&2
  exit 2
fi

"$PYTHON" - "$CONFIG_PATH" "$PROJECT_ROOT" "$WRITE_STATE" <<'PY'
import json, os, sys
from datetime import datetime, timezone

# Lean types carry unicode; a Windows console default would crash the report.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

config_path, project_root, write_state = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
cfg = json.load(open(config_path, encoding='utf-8'))
targets = cfg.get('targets') or []
evidence = cfg.get('evidenceDir') or 'evidence/lean'
lock_file = cfg.get('lockFile') or 'locked-targets.json'
lock_path = lock_file if os.path.isabs(lock_file) else os.path.join(project_root, lock_file)

runs_dir = os.path.join(project_root, evidence, 'runs')
run = None
report = None
if os.path.isdir(runs_dir):
    runs = sorted((d for d in os.listdir(runs_dir)
                   if os.path.isdir(os.path.join(runs_dir, d))), reverse=True)
    if runs:
        run = runs[0]
        report_file = os.path.join(runs_dir, run, 'report.json')
        if os.path.exists(report_file):
            report = json.load(open(report_file, encoding='utf-8'))

locked = None
if os.path.exists(lock_path):
    locked = json.load(open(lock_path, encoding='utf-8')).get('targets', {})

remaining = (report or {}).get('sorryDependents') or []
warnings = (report or {}).get('warnings') or []

print('lean status — %s' % project_root)
print('  mode      : %s' % (cfg.get('mode') or '(unset)'))
print('  targets   : %d configured, %d locked' % (len(targets), len(locked or {})))
if report:
    print('  last run  : %s  %s' % (report.get('runId', run),
                                    'PASS' if report.get('ok') else 'FAIL'))
    steps = report.get('steps')
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        print('  steps     : %s' % ', '.join('%s=%s' % (s.get('step'), s.get('exitCode')) for s in steps))
    else:
        print('  steps     : %s' % ', '.join(steps or []))
    scanned = report.get('scannedDeclarations', 0)
    print('  scan      : %s' % ('%d declarations' % scanned if report.get('scanRan')
                                else 'not run (ownModulePrefixes empty?)'))
else:
    print('  last run  : none yet — run scripts/leancheck.sh')
print('  remaining : %d declaration(s) depend on sorryAx' % len(remaining))
for r in remaining:
    if isinstance(r, dict):
        print('    - %s  [%s]' % (r.get('name'), r.get('module')))
    else:
        print('    - %s' % r)
if warnings:
    print('  warnings  : %d' % len(warnings))
    for w in warnings:
        print('    - %s' % w)

if not write_state:
    sys.exit(0)

coord = os.path.join(project_root, 'coord')
if not os.path.isdir(coord):
    print('leanstatus: no coord/ directory, STATE.md not written')
    sys.exit(1)

state_path = os.path.join(coord, 'STATE.md')
plan = ''
if os.path.exists(state_path):
    old = open(state_path, encoding='utf-8').read()
    idx = old.find('## Plan')
    if idx >= 0:
        plan = old[idx:]

stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
lines = ['# STATE', '',
         'Updated: %s by leanstatus.sh (rewritten, never appended).' % stamp, '',
         '## Stages open']
if report:
    lines.append('- gate: **%s** at `%s`' % ('PASS' if report.get('ok') else 'FAIL',
                                             report.get('runId', run)))
else:
    lines.append('- gate: no run yet')
lines.append('- statement lock: %s' % ('%d/%d targets locked' % (len(locked or {}), len(targets))
                                       if locked is not None else 'absent'))
lines.append('- remaining: %d declaration(s) depend on sorryAx' % len(remaining))
lines += ['', '## Targets', '', '| target | locked type |', '|---|---|']
for t in targets:
    entry = (locked or {}).get(t)
    lines.append('| %s | %s |' % (t, entry.get('type', '(not in lock)').replace('|', '\\|')
                                  if entry else '(not in lock)'))
lines += ['', '## Remaining work', '']
if not remaining:
    lines.append('- nothing: no library declaration depends on sorryAx')
else:
    for r in remaining:
        if isinstance(r, dict):
            lines.append('- `%s` [%s] — proof rests on sorryAx' % (r.get('name'), r.get('module')))
        else:
            lines.append('- `%s` — proof rests on sorryAx' % r)
lines.append('')
if not plan:
    plan = '## Plan\n\n- (human or agent: the next steps, each one checkable)\n'
with open(state_path, 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(lines) + '\n' + plan)
print('wrote %s' % state_path)
PY
