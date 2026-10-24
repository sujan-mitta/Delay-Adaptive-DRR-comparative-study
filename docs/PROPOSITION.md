# Proposition 1: bounded service gap of DR-DRR

## Statement
Consider a non-preemptive link of rate C serving K classes with per-class FIFO queues, scheduled by DRR whose quanta Q_j(t) change
at arbitrary instants but always satisfy Q0 <= Q_j(t) <= M Q0, with integer packet sizes (bytes), and let L_j be the largest
packet of class j. **Assumption A:** Q0 >= max_j L_j. Then, for every class i, the head-of-line packet of class i starts service no
later than

    G_i = 8 * sum_{j != i} (M Q0 + L_j - 1) / C          seconds

after it becomes the head of line (that is, after max(its arrival, the end of service of its predecessor in class i)).

For K = 3, Q0 = 1500 B, M = 8, L_j = 1500 B and C = 10 Mb/s, G_i = 8 * 2 * 13499 / 10^7 = 21.6 ms for every class whose other
two classes carry 1500-byte packets (smaller for the others). Because 21.6 ms < the 100 ms starvation threshold, no starvation
episode is possible under Assumption A.

## What the proof uses (DRR as implemented in `drrsim/schedulers.py`)
1. **Active list.** A class is on the active list exactly while its queue is non-empty. A class that becomes backlogged joins at
   the tail with deficit 0. A class that empties leaves with deficit 0.
2. **Visit.** When class j reaches the front of the list for a new visit, its deficit becomes d_j + Q_j(t_visit), where d_j is the
   deficit carried from its last visit, and it sends head packets while the head fits in the deficit. The visit ends when the head
   no longer fits (the class moves to the tail with the remainder as its new deficit) or the queue empties.
3. **Carried deficit is small.** After any visit that does not empty the queue, d_j < size of the head packet <= L_j, so, with
   integer sizes, d_j <= L_j - 1.
4. Quanta may change between visits, even during one; a visit only reads Q_j once, when it starts, so a change cannot lengthen a
   visit that has started.

## Proof
Fix class i and the instant s at which its head packet becomes the head of the line.

*Claim 1: one visit of class j sends at most M Q0 + L_j - 1 bytes.* A visit starts with deficit d_j + Q_j <= (L_j - 1) + M Q0 (by 3
and the bound on Q_j) and every byte sent is deducted from it.

*Claim 2: each class j != i has at most one visit, or one visit in progress, between s and the start of i's next visit.* If i is on
the list at s, the list is a cyclic queue: j is ahead of i or behind it, and in either case it is served at most once before i
reaches the front (a visit moves j to the tail, behind i). If i is not on the list at s (its queue was empty and the head packet
has just arrived), it joins at the tail (by 1), so every class already on the list is served at most once before i. A class that
joins the list after s is placed behind i and is not served before i. If a visit of j is in progress at s, it is the one visit
counted for j (its remaining bytes are at most its Claim 1 bound).

*Claim 3: i's next visit sends its head packet.* The visit starts with deficit >= Q_i >= Q0 >= L_i >= head size (Assumption A), so
the first head packet is sent at the start of the visit.

*Conclusion.* Between s and the start of service of i's head packet, the link serves only packets of classes j != i, at most one
visit per class (Claim 2), each at most M Q0 + L_j - 1 bytes (Claim 1). Service is non-preemptive and work-conserving, so these
bytes take at most 8 sum_j (M Q0 + L_j - 1) / C seconds. QED.

## Units and the packet in service
The factor 8 turns bytes into bits because C is in bit/s, so G_i is in seconds. A packet already being transmitted when i's head
packet becomes head of line belongs to a visit of some class j != i that Claim 2 already counts (its bytes are inside the Claim 1
bound), so no separate residual-packet term max L_k / C is added; adding one would count that packet twice.

## Where the assumptions matter
- **Assumption A fails** (for example 9000 B jumbo packets with Q0 = 1500 B): a visit may not be able to send its head packet, and
  the class waits for further visits; the bound does not hold. The simulator has such scenarios (E11 jumbo); the paper states the
  assumption and claims nothing outside it.
- **The skip-ahead over empty rounds** (`DRR._skip_empty_passes`) only triggers when a full pass sends nothing, which cannot happen
  when Q_j >= Q0 >= every head packet, so it does not interact with this bound.
- **Adaptation changes only the quanta**, and the proof uses only Q0 <= Q_j <= M Q0. It therefore holds for DR-DRR, its damped
  variant and the two ablation variants, and for any other rule with quanta inside that range, including static DRR with
  Q_j = Q (replace M Q0 by Q): the bound is not specific to DR-DRR.

## Evidence in the repository (not a substitute for the proof)
- `tests/test_drr_theory.py::test_dr_drr_service_gap_bound`: random overloaded traffic, four variants, random M and update interval.
- `tests/test_proposition.py`: an adversarial search (Hypothesis) for a counterexample over arrival patterns on a tie-heavy grid,
  packet sizes up to 1500 B, quantum parameters from "never adapts" to "always at the cap", and all four variants.
- All 1,680 saved DR-DRR and DR-DRR+damping runs at 10 Mb/s: the longest gap is 89-95 % of G_i for M = 4, 8, 12; none exceeds it
  (`tools/claims_audit.py`).
