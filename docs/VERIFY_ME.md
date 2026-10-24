# For an independent reader: what to check, in order of importance

Nothing here has been checked by anyone outside the authors. This page lists exactly what to look at and how long it should take.

## 1. The service-gap proof (about one hour, pen and paper)
Read `docs/PROPOSITION.md`. Questions to answer:
1. Is Claim 2 right: between the instant a class's head packet becomes head of line and the start of its next visit, every other class has at most one visit (or one in progress)? Look at a class that joins the list after that instant, and at a class whose queue empties mid-visit.
2. Is the carried-deficit step right: after a visit that does not empty the queue, the deficit is at most L_j - 1 (integer sizes)?
3. Does the packet already on the link when the wait begins belong to a counted visit, so that no extra residual-packet term is needed?
4. Is Assumption A (Q0 at least every packet) used exactly where it is needed (Claim 3), and is it enough?
5. The units: bytes x 8 / C gives seconds.
Then compare with the exact DRR latency bounds of Lenzini, Mingozzi and Stea (IEEE/ACM ToN 2004): is Proposition 1 implied by them, or does it say something they do not?

## 2. The code against the definition (about one hour)
- `drrsim/schedulers.py`, class `DRR` (and `SQDRR.update`, which clips quanta to [Q0, M Q0]): does it implement the visit rules stated in the proof?
- `tests/reference.py`: a second, independent DRR written from the definition; `tests/test_proposition_model.py`: an abstract model that tries every quantum at every visit.

## 3. The numbers (about 15 minutes of commands, longer to run)
Follow `docs/REPRODUCE.md`. The quick path from a fresh clone:
```
pip install -r requirements.txt
python tools/run_ledger.py --check            # run accounting
python tools/verification_counts.py --check   # docs/VERIFICATION_COUNTS.md
python tools/claims_audit.py                  # recomputes the quantitative claims from results/*/runs.csv
python scripts/make_paper_tables.py           # regenerates Tables III-VI
python -m pytest -q                           # the full test suite (about 15 minutes)
python tools/regress_check.py                 # re-simulates every saved run exactly (about 25 minutes)
```

## 4. What was not checked
The two reconstructed baselines (FuzzyDRR, RevenueDRR) and the Modified DRR variants are readings of abstracts and vendor descriptions, not the published designs.
The SCRR correction has no proof. No line-rate implementation exists.
