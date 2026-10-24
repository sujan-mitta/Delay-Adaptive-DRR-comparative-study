"""The generated audit documents must match the repository: verification counts and the reproduction guide."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_verification_counts_doc_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "verification_counts.py"), "--check"], capture_output=True)
    assert r.returncode == 0, "run python tools/verification_counts.py"


def test_reproduce_doc_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_reproduce_doc.py"), "--check"], capture_output=True)
    assert r.returncode == 0, "run python tools/make_reproduce_doc.py"


def test_verification_totals_match_the_numbers_in_the_paper_claims():
    text = (ROOT / "docs" / "VERIFICATION_COUNTS.md").read_text(encoding="utf-8")
    for n in ("395,010", "197,505", "706,629", "21,945"):
        assert n in text
