# ALGORITHM_SPEC — exact rules implemented in `drrsim/schedulers.py`

> **STATUS (2026-10-22): rules 1–4 verified (4 against its paper); rule 6 (CQDRR) checked
> against its open-access paper, with documented gaps. Rules 5, 7, 8 are DRAFT
> INTERPRETATIONS: 7 and 8 are inspired-by designs (papers paywalled; abstract / preview only), 5 is our own design.**
> Rules 5–8 were written from the papers' published intent (titles/abstracts/known
> descriptions), not from their full text. Before any result is written into the paper,
> each rule below must be checked against its PDF and either confirmed or corrected
> (then re-run the experiments). Every place where we had to choose is marked
> **[Interpretation]**. Labels such as "inspired by" are deliberate:
> these are re-implementations *in the spirit of* each line of work.

## Common model

- `K = 3` classes: 0 = latency (200 B), 1 = video (U{1000..1500} B), 2 = bulk (1500 B).
- Link rate `C` (bit/s). Per-class FIFO queues, one shared byte buffer `B`, tail drop.
- The buffer counts **queued** bytes only; the packet in transmission has left the buffer.
- Non-preemptive. When the link becomes idle and some queue is non-empty, the scheduler's
  `select(now)` names one class; the engine transmits that class's head packet.
- Per-class delay targets `D = (10 ms, 50 ms, 500 ms)`; prices `p = (3, 2, 1)`.
- Notation at time `t`: `B_i(t)` backlog bytes of class i; `H_i(t)` head-of-line waiting
  time (0 if empty); `Q_i` DRR quantum (bytes); `Q^0_i = 1500 B` base quantum;
  `Q_F = Σ_i Q^0_i = 4500 B` the frame.
- Adaptive schedulers recompute quanta every `Δ = 10 ms` (one uniform update clock for all
  four, so oscillation is comparable). **[Interpretation]** some papers update per round.
  A new quantum takes effect at the class's next DRR visit.

## 1. FIFO
Serve the head packet with the smallest packet id (= earliest arrival; ties by id).

## 2. Strict Priority (SP)
Serve the lowest-index non-empty class (0 > 1 > 2).

## 3. DRR (Shreedhar & Varghese, 1996)
Active list of backlogged classes. On visiting class i: `DC_i += Q_i`; while the queue is
non-empty and `head size ≤ DC_i`, send head and `DC_i -= size`. If the queue empties,
`DC_i = 0` and i leaves the list; otherwise i moves to the list tail. A class joining
the list is appended at the tail with `DC_i = 0`. Static quanta `Q = (1500, 1500, 1500)`.

## 4. RL-SP + DRR — **VERIFIED** against Algorithm 1 of Tokmakov, Sarker, Domaschka, Wesner, "A Case for Data Centre Traffic Management on Software Programmable Ethernet Switches", IEEE CloudNet 2019, arXiv:2002.07027
Class 0 is the high-priority queue (HPQ). On enqueue, an HPQ packet of size s arriving at t gets
a departure time `d = max(t, d_prev + s / r)` (paper: `p.departure = q.last_sent + p.size/q.rate`).
On dequeue: if the HPQ head has `d ≤ now`, send it; otherwise run DRR (rule 3) over the
**low-priority classes only** (paper: `active_list[0..N−2]`). A held HPQ packet is *not* given
to DRR, so the scheduler is not work-conserving (the paper lists under-utilisation as RL-SP's cost).
**[Interpretation]** the `max(t, ·)` clamp, so idle time does not accumulate into an unlimited
burst (as in bmv2's rate-limited queues, on which the paper builds). Parameter: `r = 0.3·C`.
*History:* the first draft used a token bucket (3000 B) and handed non-conforming class-0 packets
to DRR; both contradicted the paper and were replaced (protocol deviation 4).

## 5. DR-DRR (Delay-Risk DRR) — **our own design** (scheduler id "DR-DRR"; formerly labelled "SQ-DRR style")
The plan attributed this idea to "Kim & Park, J. High Speed Networks, 2004"; no such paper could be found
(REFERENCES_CHECK.md), so the scheduler is presented as our own delay-risk boosting baseline, not attributed.
Short-term delay risk per class, with current share `φ_i = Q_i / Σ_j Q_j`:

    d̂_i = max( H_i ,  8·B_i / (C·φ_i) )          (head wait, or predicted drain time)
    r_i = d̂_i / D_i
    Q_i ← clip( Q^0_i · (1 + κ · max(0, r_i − θ)),  Q^0_i,  M·Q^0_i )

Quanta are only *raised* above base when the delay constraint is at risk and fall back to
base as soon as risk clears. **[Interpretation]** form of the risk estimate and the
proportional boost. Parameters: `κ = 4`, `θ = 0.5`, `M = 8`.
Ablation only (E9): optional smoothing `Q_i ← (1−λ)Q_i + λ·Q*_i`; `λ = 1` (default) is the rule above.

## 6. CQDRR — **CHECKED** against Zhang & Lu, "Asynchronous Channel-Aware and Queue-Aware Deficit Round Robin Scheduling Strategy for Different TSN Traffics in the TSN-5G Network", Electronics Letters 61(1) e70418, 2025 (open access; Algorithm 1, Eqs. 1–13)
Class mapping: latency → TT, video → AVB, bulk → BE. DRR rounds visit classes in priority order
TT, AVB, BE (paper: "prioritise CurrentList according to QoS priority"). At every update:

    R_i  = C · Q_i / Σ_j Q_j                      (Eq. 12; channel factor constant on a wired link)
    R̄_i ← (1 − g) R̄_i + g R_i                     (Eq. 13)
    D_i  = 8 (Q_i + L_max,i) / R_i                 (Eq. 3)
    η_i  = −ln(p_i) / D^c_i ,  h = mean over TT classes of η_i D_i      (Eq. 2)
    W_i  = M/M/1/K blocking at ρ_i = λ_i / R_i, K_i = B / mean size_i    (Eq. 4)
    U(x) = α-fair utility (Eqs. 7–8)
    TT : Q_i = S·a_i·exp((η_i D_i − h)/(1 + √h))·U(R_i/R̄_i) + b_i·L_i·W_i   (Eq. 1)
    AVB: Q_i = S·(−a_i ln D_i)·U(R_i/R̄_i) + b_i·L_i·W_i                     (Eq. 5)
    BE : Q_i = S·U(R_i/R̄_i)                                                  (Eq. 6)
    Q_i clipped to [64 B, 64 000 B]

L_i is the class backlog in bytes; λ_i an EWMA of the offered rate.
**Consequence:** with a single TT class, `h = η D` and the exponential factor is exactly 1 — the
delay term is inert in a class-level setting (tested).
**[Interpretation]** (the paper does not give these): α-fair α = 0 (α = 1 makes U ≈ 0 on a wired
link and the BE quantum vanish); a_i = b_i = 0.5 (middle of the paper's [0,1]); p_i = 0.05 (our
targets are p95); g = 0.1; λ EWMA gain 0.1; byte scale S for the dimensionless terms (the paper's
quantum mixes units), tuned on dev seeds; K_i from the shared buffer; the clip range.
*History:* the first draft (queue share × (D_min/D_i)^β) is not the paper's rule; it is kept as the
labelled variant "CQDRR-draft" (protocol deviation 5).

## 7. Fuzzy Adaptive DRR, simplified (after Alsahag et al., JNCA, doi:10.1016/j.jnca.2013.04.004) — **partially checked (abstract only)**
*Known mismatch:* the paper's fuzzy inputs are maximum latency (real-time classes) and throughput (non-real-time classes), producing a deadline used as a DRR weight; our second input is queue occupancy. Rule base and membership functions not available.
Inputs per class: queue occupancy `x = min(1, B_i / (B/K))` and delay ratio
`y = min(1, H_i / (s·D_i))`. Triangular membership on [0,1]:
`L = (0,0,0.5)`, `M = (0,0.5,1)`, `H = (0.5,1,1)`.
Rule table (zero-order Sugeno singletons, output = quantum multiplier `o`):

| queue \ delay | L    | M   | H   |
|---------------|------|-----|-----|
| L             | 0.75 | 1.0 | 1.5 |
| M             | 1.0  | 1.5 | 2.5 |
| H             | 1.5  | 2.5 | 4.0 |

    m_i = Σ_rules μ_x·μ_y·(1 + g·(o − 1)) / Σ_rules μ_x·μ_y
    Q_i = max(Q_min, Q^0_i · m_i)

**[Interpretation]** Sugeno instead of Mamdani/centroid, the rule table values, and the
absolute (non-incremental) update. Parameters: `g = 1`, `s = 2`, `Q_min = 300 B`.

## 8. Revenue-based adaptive DRR (Sayenko et al., QoS-IP 2005, LNCS 3375, pp. 600–612) — **partially checked (2-page preview)**
*Consistent with the preview:* QoS requirements fix minimum resources and prices allocate free bandwidth to more expensive classes; our greedy price order is the LP-relaxation optimum of that integer program. *Unverified:* the paper's delay constraints, flow-count-based requirements and integer rounding.
Demand estimate per class (bit/s), with offered-rate EWMA `R_i` (gain `a` per update):

    R_i ← (1 − a)·R_i + a · 8·(arrived bytes in last Δ)/Δ
    δ_i = R_i + 8·B_i / τ                         (arrivals + backlog cleared within τ)
    alloc_i = min(δ_i, G_i)                        (guaranteed minimum first)
    spare  = C − Σ alloc_i, given greedily in decreasing price p_i, up to δ_i − alloc_i
    remaining spare split equally
    Q_i = max(Q_min, Q_F · alloc_i / C)

Delay targets are **not** used: spare capacity follows revenue. **[Interpretation]**
greedy price ordering and the demand estimator.
Parameters: `G = (0.2, 0.3, 0.2)·C`, `p = (3, 2, 1)`, `τ = 100 ms`, `a = 0.1`, `Q_min = 150 B`.

## Bounds every adaptive scheduler must respect (tested)
Quanta stay finite and positive at every update, within each rule's own range:
DR-DRR `[Q^0, M·Q^0]`; CQDRR `[64 B, 64 000 B]`; FuzzyDRR `[Q_min, (1 + 3g)·Q^0]` for gain g;
RevenueDRR `[Q_min, Q_F]`. The test suite checks `0 < Q ≤ 64 000 B` for all four.

## 9. SCRR — **VERIFIED** against Sharafzadeh et al., "Self-Clocked Round-Robin Packet Scheduling", USENIX NSDI 2025, Appendix A, Algorithms 3–4 (open access)
Optional ninth scheduler, run as a separate arm (protocol §ES). Parameter-free and unweighted; each class
is one sub-queue; virtual times in bytes. Enqueue: an inactive sub-queue joins the priority list
(Sparse Flow Optimization) if its clock ≤ the global clock or no sub-queue is active (No Empty), otherwise
the normal list. Dequeue: serve the head of the priority list, else the normal list; packet virtual time
`v = clock_f` if the sub-queue stayed active, else `v_prev + length` (Initial Advance; No Packet Metadata);
`clock_f = v + length`; the global clock advances to the largest dequeued virtual time once per round;
the scheduler stays on a sub-queue while `clock_f ≤ global clock`.
**[Interpretation]** `nq` = sub-queues in the schedule; a sub-queue leaves the schedule as soon as it
empties (the paper's "keep newly empty sub-queues for one more round" refinement is described in §3.3.1
but absent from Algorithm 4, so it is not modelled).

