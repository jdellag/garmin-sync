# Exercise-Science Audit — Sources & Per-Parameter Verdicts

Working reference for verifying the scientific soundness of garmin-sync's training metrics.
Verdicts are **synthesized from the cited sources below**, not from model recollection. Each
parameter is tagged: ✅ **established** · 🟡 **reasonable simplification** · 🟠 **contested/weak** · 🔴 **unsupported**.

> Provenance note: the deep-research harness's search+fetch stages found these 24 sources and
> extracted the claims; its automated verification stage malfunctioned (agents returned no
> structured votes), so the verdicts here are applied manually against the source evidence.
> "Confirm-later" = source identified but full text not yet fetched.

## ✅ Actions taken (pass a)

- **Area 2 (A:C):** ratio now **uncoupled** — `acute_chronic_ratio` = acute(7d) ÷ prior-3-week
  weekly avg (`chronic_baseline_weekly`), excluding the acute window (Lolli 2019). Reframed
  from "injury risk" → descriptive **load-ramp** (`load_ramp`: reduced/steady/building/
  rapid_increase). Overload anomaly downgraded critical→**warning** (cardio) / **info** (strength).
  Updated in `aggregators.py`, `anomaly_detector.py`, `executor.py`, `mcp/server.py`,
  `prompt_builder.py`, `llm_formatter.py` + docs.
- **Area 5 (volume):** `DEFAULT_WEEKLY_SET_TARGETS` raised to **hypertrophy** (MEV→low-MAV;
  major muscles ~12–14). `ai/config.py` + docs.
- **Area 1 (sRPE):** documented as **modified sRPE** (volume-weighted per-set RPE, not Foster's
  single-session) and the estimation heuristic as an unvalidated proxy. `strength_load.py`.
- **Area 6:** documented HR-drift <5% interpretation and the deload 120%/3-week rule as a heuristic.
- **Area 3 (HRV):** **deferred** — single-day delta → 7-day rolling ln-rMSSD vs personal CV is its
  own task (touches `get_hrv_context`, `_score_hrv`, the HRV anomaly).
- **Area 4:** thresholds left as-is (reasonable heuristics); Foster monotony/strain not implemented.

---

## AREA 1 — Strength Training Load via sRPE  (`reports/strength_load.py`)

| Element | Verdict | Basis |
|--------|---------|-------|
| sRPE *applied to resistance training* | ✅ established | Day 2004 ICC 0.88 vs %1RM; McGuigan & Foster 2004 ICC 0.95; HIFT r 0.83–0.87 |
| `STL = sessionRPE × duration_min × 1.0` (A.U.) | ✅ established formula | Foster 2001; Haddad 2017 (87 min × RPE 4 = 348 A.U.) |
| **Volume-weighted mean of per-set RPE** | 🟡 deviation from canonical | Foster sRPE is ONE whole-session CR10 rating × duration, *not* a per-set mean |
| **Estimation heuristics** (base 5.0 ± PR/failure/volume) | 🟠 our invention, unvalidated | no literature; pragmatic proxy only |
| `STL_SCALE_FACTOR = 1.0` | 🟡 document-as-approximate | already self-labeled in code |

- **sRPE is genuinely validated for resistance training** — strong reliability/validity vs. objective markers (Day et al. 2004, ICC 0.88, 0.70–0.96 vs %1RM; McGuigan & Foster 2004, ICC 0.95; CrossFit/HIFT r 0.834–0.865 vs Edwards-TRIMP). **KEEP** the method.
- **But correlations are weaker/noisier for resistance & intermittent work than for steady endurance** (e.g. r ≈ 0.52 rugby resistance, r ≈ 0.31 plyometric vs TRIMP). → keep the "approximate" framing.
- **Volume-weighting is a deviation.** Foster's validated method = a single global "how was your workout?" CR10 rating (~30 min post) × total duration. We compute a volume-weighted mean of *per-set* RPEs. Per-set ratings are what HEVY logs, so this is defensible — but it is **modified sRPE, not Foster sRPE**, and a single whole-session value diverges from per-set ratings (Sweet 2004). → **DOCUMENT** as "modified sRPE"; optionally support a single end-of-session RPE if HEVY exposes one.
- **The estimation heuristics have no literature backing** (they're ours). → **DOCUMENT** as a heuristic estimate; fine as a fallback, don't present as validated.

**Sources:** Foster 2001 [PDF](https://paulogentil.com/pdf/A%20New%20Approach%20to%20Monitoring%20Exercise%20Training.pdf) · Day 2004 [PMID 15142026](https://pubmed.ncbi.nlm.nih.gov/15142026/) · Sweet 2004 [PMID 15574104](https://pubmed.ncbi.nlm.nih.gov/15574104/) · Haddad 2017 review [Front Neurosci](https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2017.00612/full) · sRPE methods review [PMC5673663](https://pmc.ncbi.nlm.nih.gov/articles/PMC5673663/) · HIFT validity [PMC6162408](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6162408/)

---

## AREA 2 — Combined EPOC + sRPE Acute:Chronic ratio  (`reports/aggregators.py`, `anomaly_detector.py`)  ⚠️ weakest link

| Element | Verdict | Basis |
|--------|---------|-------|
| Summing Garmin EPOC + our sRPE into one load | 🟡 document-as-approximate | no source validates the mix; already self-labeled |
| ACWR as an **injury-risk** predictor | 🔴 largely discredited | Impellizzeri 2020; multiple 2019–21 critiques |
| The `0.8–1.3 sweet spot` / `>1.5 high injury risk` bands | 🔴 unsupported | "no evidence supports the 0.8–1.3 zone" |
| `chronic = 28d-sum / 4` (coupled window) | 🟠 mathematical coupling | acute is *inside* chronic → spurious correlation |
| Rolling average vs EWMA | 🟡 EWMA preferred | Williams 2017 |

- **This is the least defensible area.** The acute:chronic workload ratio has been heavily criticized: *"no evidence supports the use of ACWR"* for injury reduction; it's statistically inaccurate and not consistently related to injury risk (Impellizzeri et al. 2020). There is **no evidence for the 0.8–1.3 "sweet spot"** and no rationale for the specific 7d/28d windows.
- **Mathematical coupling:** our `chronic` (28-day sum ÷ 4) *contains* the acute 7-day window, which produces a spurious/artefactual correlation (Lolli 2019). If we keep a ratio, **uncouple** it (chronic = days 8–28 only) and/or use **EWMA** (Williams 2017, more sensitive than rolling averages).
- **Recommendation → CHANGE the framing (not necessarily delete the metric):** stop labeling A:C as "high injury risk." Reframe as a *descriptive ramp-rate* ("acute load is X% of your 4-week average") and soften/relabel the `>1.5` anomaly. Heavily **DOCUMENT** that mixing EPOC+sRPE and the ratio itself are approximate monitoring signals, not causal injury prediction. (Editorial consensus: ACWR monitoring "shouldn't be abandoned" wholesale, but must not be treated as precise risk.)

**Sources:** Impellizzeri 2020 "conceptual issues & pitfalls" [PMID 32502973](https://pubmed.ncbi.nlm.nih.gov/32502973/) · ACWR critique [PMC8138569](https://pmc.ncbi.nlm.nih.gov/articles/PMC8138569/) · Lolli 2019 mathematical coupling [PMID 29101104](https://pubmed.ncbi.nlm.nih.gov/29101104/) · Williams 2017 EWMA [PMID 28003238](https://pubmed.ncbi.nlm.nih.gov/28003238/)

---

## AREA 3 — Readiness score 0–100  (`reports/periodization.py`)

| Element | Verdict | Basis |
|--------|---------|-------|
| HRV-guided readiness *in principle* | ✅ established | Plews & Buchheit |
| **Single-morning HRV-delta vs 7d baseline** | 🟠 too noisy | best practice = 7-day rolling mean of ln rMSSD |
| Component weights (25/20/20/15/20…) | 🟡 expert-judgment heuristic | no literature prescribes weights (like Garmin/Whoop proprietary scores) |
| A:C as a readiness component | 🟠 inherits Area 2 issues | reduce weight or reframe |
| ~48h same-muscle recovery penalty | 🟡 reasonable | consistent with 24–72h recovery literature |

- HRV monitoring works, but the **validated method uses a 7-day rolling average of log-transformed RMSSD (ln rMSSD)** vs. a longer baseline, judged against the **smallest worthwhile change (~0.5×CV)** — not a single morning value vs. a fixed −20% linear ramp (Plews & Buchheit). The day-to-day **variability (CV) of HRV** is itself a maladaptation signal. → **CHANGE:** smooth HRV over ~7 days and personalize the threshold to the athlete's own CV.
- Component weights are reasonable expert judgment but **arbitrary** → **DOCUMENT** as a heuristic composite; don't claim empirical weighting.

**Sources:** Plews & Buchheit HRV case study [ResearchGate](https://www.researchgate.net/publication/221863314_Heart_rate_variability_in_elite_triathletes_is_variation_in_variability_the_key_to_effective_training_A_case_comparison) · Altini HRV primer [blog](https://marcoaltini.substack.com/p/a-brief-history-of-heart-rate-variability) · additional HRV (confirm-later): [PMID 24334285](https://pubmed.ncbi.nlm.nih.gov/24334285/), [PMID 18308872](https://pubmed.ncbi.nlm.nih.gov/18308872/)

---

## AREA 4 — Anomaly thresholds  (`reports/anomaly_detector.py`)

| Threshold | Verdict | Note |
|----------|---------|------|
| Foster **monotony** (weekly mean ÷ SD) & **strain** (load × monotony) | ✅ established definitions | matches Foster 2001 exactly; "high" cutoffs not standardized |
| HRV crash `−15%` / 3 days below | 🟡 reasonable, personalize | tie to individual CV / smallest-worthwhile-change |
| RHR spike `+5 bpm` | 🟡 reasonable | elevated RHR is a recognized overtraining/illness marker; no universal cutoff |
| SpO₂ `<92%` | 🟡 reasonable (wellness flag) | clinically <90% = hypoxemia; 90–94% borderline — fine as a non-diagnostic flag |
| Sleep `3 nights >1 SD below mean` | 🟡 reasonable | sensible personalized statistic |

- Mostly **reasonable heuristics**. The main upgrade is **personalization** (use each metric's own variability) rather than fixed global cutoffs. Foster monotony/strain are correctly defined; just document that the *trigger* levels are practical choices, not validated cutoffs.

**Sources:** Foster 2001 [PDF](https://paulogentil.com/pdf/A%20New%20Approach%20to%20Monitoring%20Exercise%20Training.pdf) (monotony/strain) · HRV smallest-worthwhile-change (Area 3 sources)

---

## AREA 5 — Muscle-group weekly set targets  (`ai/config.py`)  ← actionable calibration

RP volume landmarks (Israetel): **MV 8–12 · MEV 10–16 · MAV 16–20 · MRV 20+** sets/muscle/week.
Schoenfeld 2017 dose-response: **>10 sets/week beats <10** for hypertrophy.

Our targets (sets/wk): quads 10, hams 8, glutes 10, chest 10, lats 10, delts 10, upper-back 8, biceps 6, triceps 6, traps 6, calves 6, abs 8, forearms/adductors/abductors/lower-back 4.

- **Verdict: 🟡 fine for "general fitness / maintenance," under-dosed for hypertrophy.** Most targets sit at the **MV–MEV boundary** (maintenance ≈ 8–12). For hypertrophy you'd want **≥10–16+** per muscle.
- Specifically low if the goal is growth: **hamstrings 8, biceps 6, triceps 6, calves 6**.
- **Recommendation → decide the goal and label it.** (a) If "moderate general fitness" (as the docs say) → **KEEP** but state it's a maintenance/floor target, not hypertrophy-optimal. (b) If hypertrophy is intended → **raise** toward MEV/MAV (chest 12–16, hams 10–12, biceps/triceps 8–12 direct). The defaults are user-overridable in `profile.toml`, which mitigates this.

**Sources:** RP MEV/MAV/MRV [Israetel/RP](https://drmikeisraetel.com/dr-mike-israetel-mv-mev-mav-mrv-explained/) · volume dose-response (confirm-later): [PMID 27433992](https://pubmed.ncbi.nlm.nih.gov/27433992/), [PMID 35291645](https://pubmed.ncbi.nlm.nih.gov/35291645/), [Sports Med 2025](https://link.springer.com/article/10.1007/s40279-025-02344-w)

---

## AREA 6 — Cardio & strength metrics  (`reports/aggregators.py`, `sync/fit_parser.py`)

| Metric | Verdict | Note |
|--------|---------|------|
| Epley 1RM `w×(1+reps/30)`, **reps 1–10 only** | ✅ established | standard formula; capping at low reps is correct (accuracy degrades >~10–12 reps); Epley≈Brzycki, Epley slightly higher at high reps |
| HR drift / decoupling, **<5% good** | ✅ practitioner standard | TrainingPeaks/Friel: <5% strong, 5–10% moderate, >10% poor |
| Garmin/Firstbeat VO₂max | 🟡 reasonable (consume as-is) | Firstbeat reports high accuracy (~±5%); **confirm-later** (PDF fetch refused) |
| Deload: ≥3 wks >120% baseline + declining recovery | 🟡 reasonable heuristic | consistent with monotony/strain & overreaching literature; not a single cited cutoff |
| Pacing CoV / negative splits | 🟡 reasonable descriptors | standard performance signals |

**Sources:** decoupling [TrainingPeaks](https://www.trainingpeaks.com/coach-blog/aerobic-endurance-and-decoupling/) · Firstbeat VO₂max [white paper](https://assets.firstbeat.com/firstbeat/uploads/2017/06/white_paper_VO2max_30.6.2017.pdf) (confirm-later) · 1RM formulas (textbook; weightliftcalculator source rated unreliable)

---

## Headline takeaways

1. 🔴 **A:C "injury risk" framing (Area 2) is the least defensible thing in the app** — reframe as a descriptive ramp-rate, uncouple the window, soften the `>1.5` label, consider EWMA.
2. 🟠 **Single-day HRV delta (Area 3)** should become a 7-day rolling ln-rMSSD trend vs. personal CV.
3. 🟡 **Volume targets (Area 5)** are maintenance-level — fine if labeled "general fitness," low for hypertrophy.
4. ✅ **Core methods are sound:** sRPE for strength, the sRPE formula, Foster monotony/strain, Epley (reps≤10), decoupling <5%. Mostly need honest "approximate/heuristic" labeling.
5. 🟡 **Our own approximations (STL volume-weighting, EPOC+sRPE mix, estimation heuristics, scoring weights)** are defensible simplifications — keep, but **document** rather than present as validated.

## Confirm-later (sources surfaced, full text not yet fetched)
PMID 24334285, 18308872, 27433992, 35291645 · [Sports Med 2025](https://link.springer.com/article/10.1007/s40279-025-02344-w) · [PMC12881131](https://pmc.ncbi.nlm.nih.gov/articles/PMC12881131/) · [Front Sports 2025](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2025.1707991/full) · Firstbeat VO₂max PDF
