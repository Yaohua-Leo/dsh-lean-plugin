#!/usr/bin/env python3
"""leandag.py — the statement DAG, its derived work queue, and its pruning.

Why this exists (SHEAF's central observation): the number of `sorry`s is not a
measure of progress. Splitting one proof into five raises it, and a file with no
`sorry` may rest on a wrong definition. What is left to do is the set of nodes a
target still needs and that are not proved. This script computes exactly that,
from a file you keep in the repository, and cross-checks it against the gate's own
evidence — never against a guess.

State object: `coord/nodes.jsonl`, one JSON object per line.

    {"id": "lem:flat",
     "kind": "lemma",                    # target | def | lemma | other
     "statement": "flattening for coherent sheaves",
     "mathlib": "Flat.someTheorem",      # set when Mathlib already has it (leaf)
     "stmtDeps": ["def:coherent"],       # to STATE it
     "proofDeps": ["lem:x"],             # to PROVE it
     "lean": "MyPkg.Flat.flat",          # the Lean declaration, once stated
     "status": "open"}                   # open | stated | proved | pruned

`statement_deps`/`deps`/`proof_deps`/`lean_name` are accepted as aliases.

Derived, never stored: reachability from the targets (everything unreachable is a
pruning candidate — SHEAF found 62.5% of a full DAG was never needed), readiness,
and the distance to the nearest target, which orders the queue.

Cross-check with the gate: the newest `evidence/lean/runs/*/report.json` gives the
statement-lock state and the declarations still resting on `sorryAx`. A node whose
`lean` name appears there is downgraded from `proved` to `hollow` — the gate is
the authority, not the status field.

Outputs: `coord/queue.tsv` (machine), `coord/queue.md` (human), and with --state a
`coord/DAG.md` summary. Exit 1 on a structurally broken DAG (cycle, unknown
dependency, duplicate id, no target) so it cannot silently look fine.
"""
import argparse
import json
import os
import sys
from collections import deque

ALIASES = {
    "statement_deps": "stmtDeps",
    "deps": "stmtDeps",
    "proof_deps": "proofDeps",
    "lean_name": "lean",
    "module": "module",
}
KINDS = ("target", "def", "lemma", "other")
STATUSES = ("open", "stated", "proved", "pruned")


def load_nodes(path):
    nodes = {}
    problems = []
    if not os.path.exists(path):
        return None, [f"no node file at {path}"]
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{path}:{lineno}: not JSON: {exc}")
                continue
            node = {}
            for key, value in raw.items():
                node[ALIASES.get(key, key)] = value
            nid = node.get("id")
            if not nid:
                problems.append(f"{path}:{lineno}: no id")
                continue
            if nid in nodes:
                problems.append(f"{path}:{lineno}: duplicate id {nid}")
                continue
            node.setdefault("kind", "lemma")
            node.setdefault("status", "open")
            node.setdefault("stmtDeps", [])
            node.setdefault("proofDeps", [])
            if node["kind"] not in KINDS:
                problems.append(f"{nid}: unknown kind {node['kind']!r}")
            if node["status"] not in STATUSES:
                problems.append(f"{nid}: unknown status {node['status']!r}")
            for field in ("stmtDeps", "proofDeps"):
                if not isinstance(node[field], list):
                    problems.append(f"{nid}: {field} must be a list")
                    node[field] = []
            nodes[nid] = node

    for nid, node in nodes.items():
        for field in ("stmtDeps", "proofDeps"):
            for dep in node[field]:
                if dep not in nodes:
                    problems.append(f"{nid}: {field} references unknown node {dep}")

    targets = [nid for nid, n in nodes.items() if n["kind"] == "target"]
    if not targets:
        problems.append("no node has kind \"target\": a DAG without a target cannot be pruned")
    return (nodes, targets), problems


def reachable(nodes, targets):
    """Nodes needed by a target, transitively through both dependency kinds."""
    seen = set()
    queue = deque(targets)
    while queue:
        nid = queue.popleft()
        if nid in seen or nid not in nodes:
            continue
        seen.add(nid)
        node = nodes[nid]
        if node.get("mathlib"):
            continue  # a Mathlib leaf needs nothing further
        for dep in list(node["stmtDeps"]) + list(node["proofDeps"]):
            if dep not in seen:
                queue.append(dep)
    return seen


def cycles(nodes):
    """Return one cycle as a list of ids, or None. Detects proofDeps cycles too."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {nid: WHITE for nid in nodes}
    stack = []

    def visit(nid):
        colour[nid] = GREY
        stack.append(nid)
        node = nodes[nid]
        for dep in list(node["stmtDeps"]) + list(node["proofDeps"]):
            if dep not in nodes:
                continue
            if colour[dep] == GREY:
                return stack[stack.index(dep):] + [dep]
            if colour[dep] == WHITE:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        colour[nid] = BLACK
        return None

    for nid in nodes:
        if colour[nid] == WHITE:
            found = visit(nid)
            if found:
                return found
    return None


def distances(nodes, targets):
    """Shortest distance to a target by undirected dependency adjacency (BFS)."""
    adj = {nid: set() for nid in nodes}
    for nid, node in nodes.items():
        for dep in list(node["stmtDeps"]) + list(node["proofDeps"]):
            if dep in nodes:
                adj[nid].add(dep)
                adj[dep].add(nid)
    dist = {}
    queue = deque()
    for t in targets:
        dist[t] = 0
        queue.append(t)
    while queue:
        nid = queue.popleft()
        for nb in adj[nid]:
            if nb not in dist:
                dist[nb] = dist[nid] + 1
                queue.append(nb)
    return dist


def latest_report(project_root, evidence_dir):
    runs = os.path.join(project_root, evidence_dir, "runs")
    if not os.path.isdir(runs):
        return None
    names = sorted(d for d in os.listdir(runs) if os.path.isdir(os.path.join(runs, d)))
    for name in reversed(names):
        path = os.path.join(runs, name, "report.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
    return None


def classify(nodes, targets, reach, dist, report):
    """One status per node: satisfied | proved | hollow | ready | waiting | pruned."""
    sorry_names = set()
    if report:
        for entry in report.get("sorryDependents") or []:
            if isinstance(entry, dict) and entry.get("name"):
                sorry_names.add(entry["name"])
            elif isinstance(entry, str):
                sorry_names.add(entry)

    def satisfied(nid):
        node = nodes[nid]
        if node.get("mathlib"):
            return True
        return classify.cache.get(nid) in ("proved", "satisfied")

    classify.cache = {}
    # Fixed point: a node is proved when its status says so and the gate does not
    # contradict it; satisfied adds Mathlib leaves.
    for nid, node in nodes.items():
        if nid not in reach:
            classify.cache[nid] = "pruned"
        elif node["status"] == "pruned":
            classify.cache[nid] = "pruned"
        elif node.get("mathlib"):
            classify.cache[nid] = "satisfied"
        elif node["status"] == "proved":
            lean = node.get("lean")
            classify.cache[nid] = "hollow" if lean and lean in sorry_names else "proved"
        else:
            classify.cache[nid] = "open"

    changed = True
    while changed:
        changed = False
        for nid, node in nodes.items():
            if classify.cache[nid] in ("pruned", "satisfied", "proved", "hollow"):
                continue
            deps = [d for d in node["stmtDeps"] if d in nodes]
            if all(classify.cache[d] in ("satisfied", "proved") for d in deps):
                if classify.cache[nid] != "ready":
                    classify.cache[nid] = "ready"
                    changed = True
    for nid in nodes:
        if classify.cache[nid] == "open":
            classify.cache[nid] = "waiting"
    return classify.cache


def order_key(nid, nodes, cache, dist):
    rank = {"hollow": 0, "ready": 1, "waiting": 2, "proved": 3, "satisfied": 4, "pruned": 5}
    return (rank.get(cache[nid], 9), dist.get(nid, 10 ** 6), nid)


def main(argv=None):
    parser = argparse.ArgumentParser(description="derive the work queue from the statement DAG")
    parser.add_argument("--project", default=os.getcwd())
    parser.add_argument("--nodes", default=None)
    parser.add_argument("--json", action="store_true", help="also print the queue as JSON")
    parser.add_argument("--state", action="store_true", help="write coord/DAG.md")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.project)
    config_path = os.path.join(root, "lean-formalization.json")
    evidence_dir = "evidence/lean"
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as fh:
                evidence_dir = json.load(fh).get("evidenceDir") or evidence_dir
        except (OSError, json.JSONDecodeError):
            pass

    nodes_path = args.nodes or os.path.join(root, "coord", "nodes.jsonl")
    loaded, problems = load_nodes(nodes_path)
    if loaded is None:
        print("leandag: %s" % problems[0], file=sys.stderr)
        print("leandag: create coord/nodes.jsonl; see the module docstring for the format",
              file=sys.stderr)
        return 2
    nodes, targets = loaded

    found_cycle = cycles(nodes)
    if found_cycle:
        problems.append("dependency cycle: %s" % " -> ".join(found_cycle))

    report = latest_report(root, evidence_dir)
    if problems:
        print("leandag: the DAG is structurally broken; refusing to derive a queue",
              file=sys.stderr)
        for p in problems:
            print(" - %s" % p, file=sys.stderr)
        return 1

    reach = reachable(nodes, targets)
    dist = distances(nodes, targets)
    cache = classify(nodes, targets, reach, dist, report)
    ordered = sorted(nodes, key=lambda nid: order_key(nid, nodes, cache, dist))

    counts = {}
    for nid in nodes:
        counts[cache[nid]] = counts.get(cache[nid], 0) + 1
    pruned_unreachable = [nid for nid in nodes if nid not in reach]

    queue_path = os.path.join(root, "coord", "queue.tsv")
    md_path = os.path.join(root, "coord", "queue.md")
    os.makedirs(os.path.dirname(queue_path), exist_ok=True)
    with open(queue_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# item\tkind\tdistance\tstatus\tlean\tstmtDeps\tstatement\n")
        for nid in ordered:
            node = nodes[nid]
            fh.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\n" % (
                nid, node["kind"], dist.get(nid, ""), cache[nid], node.get("lean") or "",
                ",".join(node["stmtDeps"]), (node.get("statement") or "").replace("\t", " ")))
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Work queue\n\n")
        fh.write("Derived from `coord/nodes.jsonl`; do not edit by hand.\n\n")
        fh.write("| item | kind | distance | status | lean | statement |\n|---|---|---|---|---|---|\n")
        for nid in ordered:
            node = nodes[nid]
            fh.write("| %s | %s | %s | %s | %s | %s |\n" % (
                nid, node["kind"], dist.get(nid, ""), cache[nid], node.get("lean") or "",
                (node.get("statement") or "").replace("|", "\\|")))

    print("leandag: %d node(s), %d target(s)" % (len(nodes), len(targets)))
    print("  reachable from a target : %d" % len(reach))
    print("  pruning candidates      : %d (never needed by a target)"
          % len(pruned_unreachable))
    for key in ("hollow", "ready", "waiting", "proved", "satisfied", "pruned"):
        if counts.get(key):
            print("  %-8s: %d" % (key, counts[key]))
    if report:
        print("  gate: %s at %s (lock: %s)" % (
            "PASS" if report.get("ok") else "FAIL", report.get("runId"),
            report.get("lockState")))
    else:
        print("  gate: no run yet — statuses come from the file alone")
    print("wrote %s" % queue_path)
    print("wrote %s" % md_path)

    if args.json:
        print(json.dumps([{"id": nid, "status": cache[nid], "distance": dist.get(nid),
                           "kind": nodes[nid]["kind"], "lean": nodes[nid].get("lean")}
                          for nid in ordered], indent=2))

    if args.state:
        state_path = os.path.join(root, "coord", "DAG.md")
        with open(state_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# DAG\n\n")
            fh.write("Derived by `leandag.py`; rewritten, never appended.\n\n")
            fh.write("- nodes: %d, targets: %d\n" % (len(nodes), len(targets)))
            fh.write("- reachable from a target: %d\n" % len(reach))
            fh.write("- pruning candidates: %d\n" % len(pruned_unreachable))
            fh.write("- statuses: %s\n" % ", ".join(
                "%s=%d" % (k, counts[k]) for k in sorted(counts)))
            if report:
                fh.write("- gate: **%s** at `%s` (lock: %s)\n" % (
                    "PASS" if report.get("ok") else "FAIL", report.get("runId"),
                    report.get("lockState")))
            fh.write("\n## Next (distance to a target, then status)\n\n")
            for nid in ordered:
                if cache[nid] in ("hollow", "ready", "waiting"):
                    fh.write("- `%s` (%s, d=%s) — %s\n" % (
                        nid, cache[nid], dist.get(nid, "?"), nodes[nid].get("statement") or ""))
        print("wrote %s" % state_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
