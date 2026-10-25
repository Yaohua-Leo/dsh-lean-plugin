#!/usr/bin/env bash
# leancheck.sh — the project gate (POSIX twin of leancheck.ps1).
#
# Reads lean-formalization.json from the project root and runs, in order:
#
#   1.  lake --no-cache build <buildTargets...> <entryModules...>
#   2.  lake env lean --run <leanAuditScript> <library> -- <targets...>
#   3.  an axiom-whitelist check over every reported declaration
#   4.  a locked-statement check: each target's printed type must equal the type
#       recorded in <lockFile> (default locked-targets.json)
#   5.  an optional library scan (scanScript, ownModulePrefixes): every library
#       declaration that still rests on sorryAx fails, and duplicate statements
#       are reported (a failure when a target is one of them)
#
# Evidence lands in <evidenceDir>/runs/<UTC stamp>-<short id>/ (report.md,
# report.json, command-*.log) and LATEST.md becomes a navigation copy.
# Exit 0 only when every command exited 0, every target was reported, every axiom
# is in the whitelist, and every locked statement still means what it meant.
#
# Step 4 fails closed: with no lock file the run FAILS, because an unverified
# statement must never look verified. Lock deliberately with --lock after
# reviewing that the targets are the statements you want.
#
# python3 is required for config parsing and the JSON checks; `python` is accepted
# as a fallback (Git Bash on Windows ships no `python3`).
#
# Usage:
#   bash scripts/leancheck.sh
#   bash scripts/leancheck.sh --lock             # (re)write the statement lock
#   bash scripts/leancheck.sh --no-build         # audit only
#   bash scripts/leancheck.sh --config other.json
set -uo pipefail

CONFIG=lean-formalization.json
NOBUILD=0
DOLOCK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --no-build) NOBUILD=1; shift ;;
    --lock) DOLOCK=1; shift ;;
    -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
    *) echo "leancheck: unknown argument: $1" >&2; exit 2 ;;
  esac
done

PROJECT_ROOT="$PWD"
case "$CONFIG" in /*) CONFIG_PATH="$CONFIG" ;; *) CONFIG_PATH="$PROJECT_ROOT/$CONFIG" ;; esac
if [ ! -f "$CONFIG_PATH" ]; then echo "leancheck: config not found: $CONFIG_PATH" >&2; exit 2; fi

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then
  echo "leancheck: python3 (or python) is required to read $CONFIG and check JSON" >&2
  exit 2
fi

eval "$("$PYTHON" - "$CONFIG_PATH" <<'PY'
import json, shlex, sys
# Lean types carry unicode (∀, ⊢, …); a Windows console default (GBK) would crash
# the checks while printing a failure.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
cfg = json.load(open(sys.argv[1], encoding='utf-8'))
if not cfg.get('library'):
    sys.exit('leancheck: config has no "library"')
def q(v):
    return shlex.quote(str(v))
print('LIBRARY=%s' % q(cfg['library']))
for key, var in (('targets', 'TARGETS'), ('entryModules', 'ENTRY'), ('buildTargets', 'BUILD'),
                 ('allowedAxioms', 'ALLOWED'), ('gitSafeDirectories', 'SAFEDIRS'),
                 ('ownModulePrefixes', 'OWN')):
    vals = cfg.get(key) or []
    if key == 'buildTargets' and not vals:
        vals = [cfg['library']]
    print('%s=(%s)' % (var, ' '.join(q(v) for v in vals)))
print('EVIDENCE_DIR=%s' % q(cfg.get('evidenceDir') or 'evidence/lean'))
print('LAKE=%s' % q(cfg.get('lakeCommand') or 'lake'))
print('AUDIT_SCRIPT=%s' % q(cfg.get('leanAuditScript') or 'LeanAudit.lean'))
print('SCAN_SCRIPT=%s' % q(cfg.get('scanScript') or 'LeanScan.lean'))
print('LOCK_FILE=%s' % q(cfg.get('lockFile') or 'locked-targets.json'))
print('MIN_DUP=%s' % q(cfg.get('minDuplicateTypeChars') or 40))
PY
)" || { echo "leancheck: could not read config" >&2; exit 2; }

if [ "${#TARGETS[@]}" -eq 0 ]; then
  echo "leancheck: config lists no targets; refusing to report an empty audit as success" >&2
  exit 2
fi

# `.lake/packages/*` may belong to another account than the one running the build;
# git then fails with "dubious ownership" and exits 128 before Lake builds
# anything. Grant safe.directory for THIS INVOCATION only (never in the user's
# global git config). List the directories in lean-formalization.json.
if [ "${#SAFEDIRS[@]}" -gt 0 ]; then
  export GIT_CONFIG_COUNT="${#SAFEDIRS[@]}"
  i=0
  for d in "${SAFEDIRS[@]}"; do
    export "GIT_CONFIG_KEY_$i=safe.directory"
    export "GIT_CONFIG_VALUE_$i=$d"
    i=$((i + 1))
  done
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SHORT="$("$PYTHON" -c 'import secrets;print(secrets.token_hex(3))')"
RUN_DIR="$PROJECT_ROOT/${EVIDENCE_DIR%/}/runs/$STAMP-$SHORT"
mkdir -p "$RUN_DIR"

STATUSES=()
STEP_NAMES=()
STEP_SECONDS=()

run_step() {
  name="$1"; shift
  echo "==> $name"
  start=$(date +%s)
  "$@" > "$RUN_DIR/command-$name.log" 2>&1
  code=$?
  end=$(date +%s)
  echo "    exit $code in $((end - start))s"
  STATUSES+=("$code")
  STEP_NAMES+=("$name")
  STEP_SECONDS+=("$((end - start))")
  return $code
}

if [ "$NOBUILD" -eq 0 ]; then
  run_step build "$LAKE" --no-cache build "${BUILD[@]}" "${ENTRY[@]}"
fi
run_step axiom-audit "$LAKE" env lean --run "$AUDIT_SCRIPT" "$LIBRARY" -- "${TARGETS[@]}"

SCAN_ARGS=()
SCAN_RAN=0
if [ "${#OWN[@]}" -gt 0 ] && [ -f "$PROJECT_ROOT/$SCAN_SCRIPT" ]; then
  for prefix in "${OWN[@]}"; do SCAN_ARGS+=(--own "$prefix"); done
  SCAN_ARGS+=(--min-type-chars "$MIN_DUP")
  run_step library-scan "$LAKE" env lean --run "$SCAN_SCRIPT" "$LIBRARY" -- "${SCAN_ARGS[@]}"
  SCAN_RAN=1
elif [ "${#OWN[@]}" -eq 0 ]; then
  echo "    library-scan skipped: ownModulePrefixes is empty in the config"
else
  echo "    library-scan skipped: $SCAN_SCRIPT is missing from the project"
fi

"$PYTHON" - "$RUN_DIR" "$LIBRARY" "$STAMP" "$LOCK_FILE" "$MIN_DUP" "$SCAN_RAN" "$DOLOCK" \
    "$PROJECT_ROOT" "$NOBUILD" \
    "${STEP_NAMES[@]:-}" -- "${STATUSES[@]:-}" -- "${STEP_SECONDS[@]:-}" -- \
    "${ALLOWED[@]}" -- "${TARGETS[@]}" <<'PY'
import hashlib, json, os, sys
# See the config block: failure messages quote Lean types, which are not ASCII.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

run_dir, library, stamp, lock_file, min_dup, scan_ran, do_lock, project_root, no_build = sys.argv[1:10]
rest = sys.argv[10:]
sep1 = rest.index('--')
step_names = rest[:sep1]
rest = rest[sep1 + 1:]
sep2 = rest.index('--')
step_codes = rest[:sep2]
rest = rest[sep2 + 1:]
sep3 = rest.index('--')
step_seconds = rest[:sep3]
rest = rest[sep3 + 1:]
sep4 = rest.index('--')
allowed = rest[:sep4]
targets = rest[sep4 + 1:]

min_dup = int(min_dup)
scan_ran = scan_ran == '1'
do_lock = do_lock == '1'


def read_log(name):
    path = os.path.join(run_dir, 'command-%s.log' % name)
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8', errors='replace') as fh:
        return fh.read().splitlines()


def records(marker):
    out = []
    for line in read_log(marker[0]):
        idx = line.find(marker[1])
        if idx < 0:
            continue
        try:
            out.append(json.loads(line[idx + len(marker[1]):]))
        except json.JSONDecodeError:
            continue
    return out


def type_hash(text):
    return hashlib.sha256(' '.join(str(text).split()).encode('utf-8')).hexdigest()


reported = {r.get('name', ''): r for r in records(('axiom-audit', 'LEANCHECK_JSON:'))}
failures = []
warnings = []

for target in targets:
    rec = reported.get(target)
    if rec is None:
        failures.append('target not reported: %s' % target)
        continue
    extra = [a for a in rec.get('axioms', []) if a not in allowed]
    if extra:
        failures.append('%s depends on axioms outside the whitelist: %s' % (target, ', '.join(extra)))

scanned = records(('library-scan', 'LEANSCAN_JSON:')) if scan_ran else []

for rec in sorted(scanned, key=lambda r: r.get('name', '')):
    if rec.get('sorryAx') and rec.get('name') not in targets:
        failures.append('declaration depends on sorryAx: %s (%s)' % (rec.get('name'), rec.get('module')))

groups = {}
for rec in scanned:
    if rec.get('kind') == 'theorem' and int(rec.get('typeChars', 0)) >= min_dup:
        groups.setdefault(rec.get('type'), []).append(rec.get('name'))
for _ty, names in sorted(groups.items()):
    if len(names) < 2:
        continue
    names = sorted(names)
    if any(n in targets for n in names):
        failures.append('duplicate statement involves a target: %s' % ', '.join(names))
    else:
        warnings.append('duplicate statement: %s' % ', '.join(names))

lock_path = lock_file if os.path.isabs(lock_file) else os.path.join(project_root, lock_file)
if do_lock:
    entries = {}
    for target in targets:
        rec = reported.get(target)
        if rec is None:
            continue
        entries[target] = {
            'kind': rec.get('kind'),
            'module': rec.get('module'),
            'typeHash': type_hash(rec.get('type')),
            'type': rec.get('type'),
        }
    with open(lock_path, 'w', encoding='utf-8') as fh:
        json.dump({
            'schemaVersion': 1,
            'note': ('Locked statements. Changing one is a change of the target, not a proof '
                     'step: review it and re-lock deliberately.'),
            'library': library,
            'lockedUtc': stamp,
            'targets': entries,
        }, fh, indent=2)
    lock_state = 'written (%d targets)' % len(entries)
elif not os.path.exists(lock_path):
    lock_state = 'missing'
    failures.append('no statement lock at %s; run leancheck --lock once the targets are the '
                    'statements you want, then commit the file' % lock_path)
else:
    with open(lock_path, encoding='utf-8') as fh:
        locked = json.load(fh).get('targets', {})
    drift = 0
    for target in targets:
        rec = reported.get(target)
        if rec is None:
            continue
        entry = locked.get(target)
        if entry is None:
            failures.append('target not in the lock: %s' % target)
            drift += 1
            continue
        if type_hash(rec.get('type')) != entry.get('typeHash'):
            failures.append('locked statement changed: %s\n    locked: %s\n    now:    %s'
                            % (target, entry.get('type'), rec.get('type')))
            drift += 1
    lock_state = 'ok (%d targets)' % len(targets) if drift == 0 else 'DRIFT (%d)' % drift

steps = [{'step': n, 'exitCode': int(c), 'seconds': int(s)}
         for n, c, s in zip(step_names, step_codes, step_seconds)]
step_failed = any(s['exitCode'] != 0 for s in steps)
ok = (not step_failed) and not failures

report = {
    'gate': 'leancheck',
    'ok': ok,
    'runId': os.path.basename(run_dir),
    'timestampUtc': stamp,
    'projectRoot': project_root,
    'library': library,
    'targets': targets,
    'allowedAxioms': allowed,
    'lockFile': lock_path,
    'lockState': lock_state,
    'lockWritten': do_lock,
    'scanRan': scan_ran,
    'scannedDeclarations': len(scanned),
    'sorryDependents': [{'name': r.get('name'), 'module': r.get('module')}
                        for r in sorted(scanned, key=lambda r: r.get('name', '')) if r.get('sorryAx')],
    'warnings': warnings,
    'whitelistFailures': failures,
    'steps': steps,
}
with open(os.path.join(run_dir, 'report.json'), 'w', encoding='utf-8') as fh:
    json.dump(report, fh, indent=2)

lines = ['# leancheck report — %s' % os.path.basename(run_dir), '',
         '- project: `%s`' % project_root,
         '- library: `%s`' % library,
         '- targets: %d' % len(targets),
         '- allowed axioms: `%s`' % ', '.join(allowed),
         '- statement lock: %s' % lock_state,
         '- library scan: %s' % ('%d declarations' % len(scanned) if scan_ran else 'skipped'),
         '- result: **%s**' % ('PASS' if ok else 'FAIL'), '',
         '## steps', '', '| step | exit | seconds |', '|---|---|---|']
for s in steps:
    lines.append('| %s | %s | %s |' % (s['step'], s['exitCode'], s['seconds']))
lines += ['', '## axioms per target', '', '| target | kind | axioms |', '|---|---|---|']
for target in targets:
    rec = reported.get(target)
    if rec:
        lines.append('| %s | %s | %s |' % (target, rec.get('kind'), ', '.join(rec.get('axioms', []))))
    else:
        lines.append('| %s | (missing) | |' % target)
if failures:
    lines += ['', '## failures', ''] + ['- %s' % f for f in failures]
if warnings:
    lines += ['', '## warnings', ''] + ['- %s' % w for w in warnings]
with open(os.path.join(run_dir, 'report.md'), 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(lines) + '\n')

latest = os.path.join(os.path.dirname(os.path.dirname(run_dir)), 'LATEST.md')
with open(latest, 'w', encoding='utf-8') as fh:
    fh.write('# leancheck — latest run\n\nLatest run: `%s` -> `runs/%s/report.md`\n\n'
             'Result: %s\n\nHistory is appended, never erased: every run keeps its own '
             'directory.\n' % (os.path.basename(run_dir), os.path.basename(run_dir),
                               'PASS' if ok else 'FAIL'))

for w in warnings:
    print(' - warning: %s' % w)
if not ok:
    for f in failures:
        print(' - %s' % f)
    sys.exit(1)
PY
CHECK_CODE=$?

FAILED=0
for code in "${STATUSES[@]:-}"; do [ "$code" != "0" ] && [ -n "$code" ] && FAILED=1; done
echo ""
echo "evidence: $RUN_DIR"
if [ "$FAILED" -ne 0 ]; then echo "FAILED steps: ${STEP_NAMES[*]}" >&2; exit 1; fi
if [ "$CHECK_CODE" -ne 0 ]; then echo "leancheck: FAIL" >&2; exit 1; fi
echo "leancheck: PASS"
exit 0
