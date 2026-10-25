#!/usr/bin/env python3
"""Independent re-check of skills/PROVENANCE.md against the files on disk.

Deliberately does not reuse verify/validate_repo.mjs: this is a second,
independent implementation, so a bug in the validator cannot hide a mismatch.
It parses every `| `path` | `sha256` |` row of the ledger and recomputes the
hash of the file it names.

Usage: python verify/provenance_recheck.py   (exit 0 ok, 1 a row failed)
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "skills" / "PROVENANCE.md"
ROW = re.compile(r"\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|")


def main() -> int:
    rows = ROW.findall(LEDGER.read_text(encoding="utf-8"))
    bad: list[str] = []
    for path, digest in rows:
        target = REPO / path
        if not target.is_file():
            bad.append("%s: missing" % path)
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual == digest:
            print("  OK   %s" % path)
        else:
            bad.append("%s: recorded %s, actual %s" % (path, digest, actual))
            print("  DIFF %s" % path)
    print("  ledger rows: %d, mismatches: %d" % (len(rows), len(bad)))
    for line in bad:
        print("  BAD  %s" % line)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
