"""The headline tables regenerate from the released runs alone, and match the figures quoted in the paper text."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_paper_tables  # noqa: E402


def test_tables_regenerate_from_released_runs():
    text = make_paper_tables.build()
    for t in ("Table III", "Table IV", "Table V", "Table VI"):
        assert t in text
    assert "| DR-DRR | 11.9 | 66.3 | 216.8 | 1.326 |" in text            # ON/OFF 0.95 row quoted in the paper
    assert "| SP | 34.5 |" in text                                           # SP starves bulk for 34.5 s in the stress test
    assert text.count("| DRR |") >= 2
