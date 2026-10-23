# Reference check (2026-10-22, from public sources)

What could be confirmed online, and what still needs the full text. Bibliographic facts below
came from publisher/indexing pages; verify each against the PDF before citing.

| Plan entry | What the public record shows | Status |
|---|---|---|
| RL-SP + DRR, "arXiv 2002.07027 (2020)" | K. Tokmakov, M. Sarker, J. Domaschka, S. Wesner, "A Case for Data Centre Traffic Management on Software Programmable Ethernet Switches", **IEEE CloudNet 2019**; arXiv:2002.07027 (Feb 2020). Full text read; Algorithm 1 implemented as written (see ALGORITHM_SPEC §4). | **Verified**; cite as CloudNet 2019 |
| CQDRR, "Zhang et al., Electronics Letters, 2025" | X. Zhang, Y. Lu, "Asynchronous Channel-Aware and Queue-Aware Deficit Round Robin Scheduling Strategy for Different TSN Traffics in the TSN-5G Network", *Electronics Letters* 61(1), e70418, 2025, doi:10.1049/ell2.70418 (open access). Full text read in a browser (open access). Rule = EXP-PF-style delay term + α-fair channel term + queue-length × M/M/1/K blocking (Eqs. 1–13); our draft rule was wrong and has been replaced (deviation 5). Unstated constants are documented in ALGORITHM_SPEC §6. | **Checked** (with documented gaps) |
| Fuzzy Adaptive DRR, "Alsahag et al., JNCA, 2014" | A.M. Alsahag, B.M. Ali, N.K. Noordin, H. Mohamad (paywalled at Elsevier; no open author copy found), "Fair uplink bandwidth allocation and latency guarantee for mobile WiMAX using fuzzy adaptive deficit round robin", *J. Network and Computer Applications*, doi:10.1016/j.jnca.2013.04.004 (online 2013; check print year/volume). **Abstract/landing page read (2026-10-22):** uplink WiMAX scheduler "FADRR"; fuzzy inputs are *maximum latency* (real-time classes) and *throughput* (non-real-time classes); output is a deadline used as a DRR weight factor, accounting for the HoL packet's scheduling delay; compared against MDRR and CDRR. **Our draft uses queue occupancy instead of throughput for the second input** — a known mismatch. Rule table and membership functions not visible. Copyright notice on the page reads 2013. | **Partially checked** (abstract only) |
| SQ-DRR, "Kim and Park, J. High Speed Networks, 2004" | Not found in public indexes searched (IOS Press, DBLP-indexed lists, general web), and not found by the author via Google Scholar / library (2026-10-22). | **Cannot be cited.** Present the scheduler as our own unattributed design, or drop it. |
| Revenue-based ADRR, "Sayenko et al., 2004/2005" | A. Sayenko, T. Hämäläinen, J. Joutsensalo, K. Raatikainen, "Revenue-based adaptive deficit round robin", QoS-IP 2005, LNCS 3375, doi:10.1007/978-3-540-30573-6_47. Paywalled (Springer); the author's 2005 Jyväskylä PhD thesis "Adaptive scheduling for the QoS supported networks" (JYX handle 123456789/103716) is a restricted file. Companion: "Adaptive scheduling using the revenue-based weighted round robin", IEEE ICON 2004, doi:10.1109/ICON.2004.1409276. **2-page Springer preview read (pp. 600–601 of 600–612), saved as papers/revenue_drr.pdf:** quanta come from an integer linear program; QoS requirements set the minimum resources, prices allocate the free bandwidth to more expensive classes; per-class active-flow counts (e.g. via RSVP) drive requirements; bandwidth and delay guarantees kept. **Our greedy "guarantee first, spare by price" equals the LP-relaxation optimum of a linear revenue objective with per-class caps**, so the core logic matches; the exact constraints (delay, flow counts) and integer rounding remain unverified. | **Partially checked** (2-page preview) |
| "Sayenko et al., Comparison and analysis of the revenue-based adaptive queuing models, Computer Networks, 2005" | DBLP lists a Sayenko *Computer Networks* article comparing revenue-based adaptive queuing models in **2006**. | Check year (2005 vs 2006) |

Sources: arxiv.org/abs/2002.07027; ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/ell2.70418;
api.semanticscholar.org (DOI 10.1049/ell2.70418); cris.vtt.fi and research.fi entries for the
Sayenko papers; reference lists citing doi:10.1016/j.jnca.2013.04.004.

## Network-calculus and SCRR references (checked 2026-10-23)

| Reference | Confirmed details | Source of the check |
|---|---|---|
| Tabatabaee & Le Boudec, "Deficit round-robin: A second network calculus analysis" | IEEE/ACM Trans. Netw., 2022, doi:10.1109/TNET.2022.3164772; conference version RTAS 2021; arXiv:2106.01034 | EPFL Infoscience record; full text read |
| Boyer, Stea & Mangoua Sofack, "Deficit round robin with network calculus" | Proc. 6th Int. ICST Conf. VALUETOOLS, 2012, pp. 138-147, doi:10.4108/valuetools.2012.250202 | reference lists citing it (publisher page not reached) |
| Soni, Li, Scharbarg & Fraboul, "Optimizing network calculus for switched Ethernet network with deficit round robin" | IEEE RTSS 2018, pp. 300-311 | DBLP; reference list of Tabatabaee & Le Boudec |
| Bouillard, "Individual service curves for bandwidth-sharing policies using network calculus" | IEEE Networking Letters, vol. 3, no. 2, pp. 80-83, 2021 | reference list of Tabatabaee & Le Boudec; author preprint |
| Sharafzadeh, Matson, Tourrilhes, Sharma & Ghorbani, "Self-Clocked Round-Robin Packet Scheduling" | USENIX NSDI 2025 | USENIX program page |
| Alsahag et al. (fuzzy adaptive DRR) | doi:10.1016/j.jnca.2013.04.004; vol. 39, pp. 17-25, March 2014 | confirmed through Crossref on 2026-10-23 |
