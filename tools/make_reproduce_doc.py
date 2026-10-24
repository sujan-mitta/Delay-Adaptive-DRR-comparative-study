"""Generate docs/REPRODUCE.md: the exact command, seeds, configuration and expected output of every experiment.

  python tools/make_reproduce_doc.py          (--check: exit 1 if docs/REPRODUCE.md is out of date)

Row counts and SHA-256 checksums are read from the saved results/*/runs.csv. Checksums are of the file with line endings
normalised to LF, so they do not depend on the operating system or on git's end-of-line conversion.
"""
import hashlib
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import run_ledger  # noqa: E402

OUT = ROOT / "docs" / "REPRODUCE.md"
DEV, REP, FRESH = "1-5 (development)", "101-120", "201-220"
# id, command, seeds, configuration read, result file
STEPS = [
    ("TUNE", "python scripts/tune.py", DEV, "drrsim/experiments.py TUNE_GRID", "config/tuned_params.json"),
    ("E1-E8", "python scripts/run_experiments.py", REP, "config/tuned_params.json", "results/E1 ... E8/runs.csv"),
    ("E9, E10", "python scripts/run_experiments.py E9 E10", REP, "config/tuned_params.json", "results/E9, E10/runs.csv"),
    ("E9C", "python scripts/e9_control.py", REP, "mean quanta of the saved E9 runs", "results/E9C/runs.csv"),
    ("DEVD, E1D", "python scripts/run_experiments.py DEVD E1D", f"{DEV}; {REP}", "config/tuned_params.json", "results/DEVD, E1D/runs.csv"),
    ("E1V, ES", "python scripts/run_experiments.py E1V ES", REP, "config/tuned_params.json", "results/E1V, ES/runs.csv"),
    ("E11, E12", "python scripts/run_experiments.py E11 E12", "101-110 (E12: 101-200 for one check)", "drrsim/experiments.py", "results/E11, E12/runs.csv"),
    ("E13", "python scripts/run_benchmarks.py", "n/a (published examples)", "drrsim/literature.py", "results/E13/<timestamp>/"),
    ("E14TUNE, E14, E15", "python scripts/e14_ablation.py", f"{DEV}; {REP}; {FRESH}", "writes config/tuned_ablation.json", "results/E14TUNE, E14, E15/runs.csv"),
    ("E19TUNE, E19, E19H", "python scripts/e19_static.py", f"{DEV}; {REP}; {FRESH}", "writes config/tuned_static_drr.json", "results/E19TUNE, E19, E19H/runs.csv"),
    ("E16, E16b", "bash testbed/run.sh (Linux, root), then python scripts/e16_kernel.py [--e16b]", "kernel traces", "testbed/setup.sh", "results/E16, E16b/<run>/summary.csv"),
    ("E17, E17b", "python scripts/e17_realtrace.py parse <mawi.pcap.gz>; python scripts/e17_realtrace.py run [strict|size]", "10 windows of 100,000 packets", "scripts/e17_realtrace.py (class mappings)", "results/E17, E17b/runs.csv"),
    ("E17c", "E17_TRACE=c python scripts/e17_realtrace.py parse <mawi-2022.pcap.gz>; E17_TRACE=c python scripts/e17_realtrace.py run", "10 windows", "as E17", "results/E17c/runs.csv"),
    ("E20", "python scripts/e20_mdrr.py", REP, "none (no tunable parameter)", "results/E20/runs.csv"),
    ("E20B", "python scripts/e20_mdrr.py b", REP, "none", "results/E20B/runs.csv"),
    ("E21", "python scripts/e20_mdrr.py e21", "101-110", "config/tuned_params.json", "results/E21/runs.csv"),
    ("E22", "python scripts/e22_tandem.py", "101-110 (cross traffic: seed + 1000)", "config/tuned_params.json", "results/E22/runs.csv"),
    ("E23TUNE, E23, E23R", "python scripts/e23_sddrr.py", f"{DEV}; {FRESH}; 101-110", "config/tuned_2knob.json, config/tuned_static_drr.json; writes config/tuned_sddrr.json", "results/E23TUNE, E23, E23R/runs.csv"),
    ("E24TUNE, E24", "python scripts/e24_retune.py", f"{DEV}; {REP}", "writes config/tuned_2knob.json", "results/E24TUNE, E24/runs.csv"),
    ("E25TUNE, E25", "python scripts/e25_readings.py", f"{DEV}; {REP}", "config/tuned_2knob.json; writes config/tuned_readings.json", "results/E25TUNE, E25/runs.csv"),
]
CHECKS = [
    ("python -m pytest", "all tests pass (the count is in docs/TESTING.md)"),
    ("python tools/run_ledger.py --check", "RUN_LEDGER.md is current"),
    ("python tools/regress_check.py", "{total} saved runs re-simulated; 0 differ"),
    ("python tools/claims_audit.py [paper_src.html]", "every claim verified (result-level checks only without the private paper source)"),
    ("python tools/verification_counts.py --check", "exit code 0 (docs/VERIFICATION_COUNTS.md is current)"),
    ("python tools/make_reproduce_doc.py --check", "exit code 0 (this file is current)"),
    ("python scripts/make_paper_tables.py", "regenerates docs/PAPER_TABLES.md (Tables III-VI) from results/*/runs.csv"),
    ("python scripts/make_report.py", "regenerates RESULTS.md"),
    ("EXHAUSTIVE_N=5 python -m pytest tests/test_exhaustive.py", "optional, about 10 minutes: the five-packet scope (33,649 traces)"),
    ("python tools/mutation_check.py", "optional, hours: 58 planted bugs, 56 behaviour-changing killed, 2 equivalent (docs/MUTATION_REPORT.md)"),
    ("python tools/release_check.py", "0 problems; lists identifying strings for the anonymous mirror"),
]


def sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def build():
    _, t = run_ledger.build()
    total = f"{t['simulator_total']:,}"
    lines = ["# Reproducing every number (generated by tools/make_reproduce_doc.py; do not edit)", "",
             "Python 3.13 with the versions in `requirements-lock.txt`. Run everything from the repository root. All randomness is seeded: each",
             "run is fixed by (experiment, operating point, scheduler, seed), and `results/*/manifest_*.json` records the code hash, package versions",
             "and configuration of every batch. `scripts/reproduce.ps1` runs the whole pipeline in dependency order.", "",
             "## Experiments", "", "| experiment | command | seeds | configuration read | output |", "|---|---|---|---|---|"]
    for eid, cmd, seeds, cfg, out in STEPS:
        lines.append(f"| {eid} | `{cmd}` | {seeds} | {cfg} | {out} |")
    lines += ["", "## Saved results: rows and checksums", "", "| file | rows | sha256 (LF-normalised, first 16 hex) |", "|---|---|---|"]
    for p in sorted((ROOT / "results").glob("*/runs.csv")):
        if p.parent.name.startswith("_"):
            continue
        lines.append(f"| results/{p.parent.name}/runs.csv | {len(pd.read_csv(p)):,} | `{sha(p)[:16]}` |")
    lines += ["", "## Configuration files", "", "| file | sha256 (LF-normalised, first 16 hex) |", "|---|---|"]
    lines += [f"| config/{p.name} | `{sha(p)[:16]}` |" for p in sorted((ROOT / "config").glob("*.json"))]
    lines += ["", "## Expected totals (from tools/run_ledger.py)", "",
              f"main matrix {t['main']:,}; further arms {t['further']:,}; tuning {t['tuning']:,}; **simulator total {total}**; "
              f"kernel runs {t['kernel_runs']}; replay runs {t['replay_runs']:,}; tandem runs {t['tandem_runs']}; archived (superseded) {t['archived']:,}.",
              "", "## Checks and their expected output", "", "| command | expected |", "|---|---|"]
    for cmd, exp in CHECKS:
        lines.append(f"| `{cmd}` | {exp.format(total=total)} |")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text(encoding="utf-8").replace("\r\n", "\n") == text else 1)
    OUT.write_text(text, encoding="utf-8")
    print(text[:1200])
