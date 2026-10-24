"""E22: the two-link composition. The saved tandem runs must re-simulate exactly, and the composition must obey its own rules."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("e22_tandem", ROOT / "scripts" / "e22_tandem.py")
E22 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E22)


@pytest.mark.skipif(not (ROOT / "results" / "E22" / "runs.csv").exists(), reason="needs the saved E22 runs")
@pytest.mark.parametrize("name", ["SP", "DRR", "DR-DRR", "FIFO"])
def test_saved_tandem_runs_re_simulate_exactly(name):
    from drrsim.experiments import load_tuned
    saved = pd.read_csv(ROOT / "results" / "E22" / "runs.csv", float_precision="round_trip")
    row = saved[(saved.scheduler == name) & (saved.load == 0.8) & (saved.seed == 101)].iloc[0]
    new = E22.tandem(name, load_tuned().get(name, {}), 0.8, 101)
    for k, v in new.items():
        if isinstance(v, float):
            assert v == row[k] or (np.isnan(v) and np.isnan(row[k])), k


def test_end_to_end_delay_is_at_least_the_single_link_delay():
    row = E22.tandem("DRR", {}, 0.8, 101)
    for c in ("lat", "vid", "blk"):
        assert row[f"{c}_e2e_p95"] >= row[f"{c}_hop1_p95"] - 1e-12
