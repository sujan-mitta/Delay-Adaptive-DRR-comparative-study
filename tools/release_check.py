"""Check that the repository is fit for release, including the double-blind (anonymous mirror) case.

  python tools/release_check.py [--term STRING ...]

1. every promised piece is tracked (simulator, scripts, tests, run ledger, results of every experiment, protocol, licence);
2. nothing private is tracked (project plan, paper sources, downloaded papers, raw traces);
3. a scan of the tracked text files for identifying strings: the defaults come from `git config user.name` / the remote URL
   owner, plus any --term given. Hits are listed per file so they can be put in the Anonymous GitHub replacement list
   (anonymous.4open.science replaces terms in file contents and file names; it does not rewrite git history).
Exit code 1 if a promised piece is missing or a private file is tracked; identifying strings are reported, not an error.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["README.md", "LICENSE", "requirements.txt", "drrsim/engine.py", "drrsim/schedulers.py", "scripts/make_report.py",
            "scripts/reproduce.ps1", "scripts/make_paper_tables.py", "tools/run_ledger.py", "tools/claims_audit.py",
            "tools/regress_check.py", "tools/mutation_check.py", "docs/RUN_LEDGER.md", "docs/run_ledger.json",
            "docs/EXPERIMENT_PROTOCOL.md", "docs/PROPOSITION.md", "docs/TESTING.md", "docs/MUTATION_REPORT.md", "RESULTS.md",
            "tests/reference.py", "results/E1/runs.csv", "results/E17/runs.csv", "config/tuned_params.json"]
PRIVATE_PREFIXES = ("PROJECT_PLAN", "papers/", "paper_draft/", "VENUE", "scratchpad", "DRR_comparison")
RAW_TRACE = re.compile(r"\.(pcap|pcapng)(\.gz)?$|mawi_windows\.npz$")


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--term", action="append", default=[])
    args = ap.parse_args()
    tracked = git("ls-files").splitlines()
    bad = 0
    for r in REQUIRED:
        if r not in tracked:
            print("MISSING  ", r)
            bad += 1
    for f in tracked:
        if f.startswith(PRIVATE_PREFIXES) or RAW_TRACE.search(f):
            print("PRIVATE  ", f)
            bad += 1
    terms = set(args.term)
    for cmd in (["config", "user.name"], ["config", "user.email"], ["remote", "get-url", "origin"]):
        try:
            v = git(*cmd)
        except subprocess.CalledProcessError:
            continue
        m = re.search(r"github\.com[:/]([^/]+)/", v)
        terms.update([m.group(1)] if m else [v.split("@")[0], v] if "@" in v else [v])
    terms = {t for t in terms if len(t) >= 3}
    print("terms scanned:", sorted(terms))
    pat = re.compile("|".join(re.escape(t) for t in sorted(terms)), re.I) if terms else None
    hits = {}
    for f in tracked:
        if pat and pat.search(f):
            hits.setdefault(f, []).append("(file name)")
        p = ROOT / f
        if not pat or not p.is_file() or p.stat().st_size > 5_000_000 or f.endswith((".png", ".pdf", ".npz", ".gz")):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                hits.setdefault(f, []).append(f"{i}: {line.strip()[:110]}")
    for f, ls in sorted(hits.items()):
        print(f"IDENTIFYING  {f}  ({len(ls)} hits)")
        for l in ls[:3]:
            print("      ", l)
    print(f"{len(tracked)} tracked files; {bad} problems; {len(hits)} files with identifying strings")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
