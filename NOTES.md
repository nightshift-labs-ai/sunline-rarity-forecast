# NOTES: sunline-rarity-forecast (build v1 + v2, session s263, 2026-11-19)

Competition: make.fun gta6-trophy-rarity-forecast-01. The task is to forecast every GTA VI PS5 trophy's Exophase earn rate at
2026-11-26T00:00Z as 5 quantiles. The final case f00 is cut at 2026-11-21T11:30Z (~350 reads, 108.5 h horizon), and the bar is the best
house entry (persistence, house curve, house AI). Spec: briefs forecast1_notes_model_s262.md and forecast1_notes_beat_s262.md.
The operator pushes and submits; the agent does neither.

## What main.py does (v1, all done)
1. Parse and dedupe: consecutive identical (N, rates) reads become STATES, timed at their first read. A null rate takes the last non-null.
   The tester era (before the first >3x jump in N, or N < 0.15*N_last) is dropped from the fits, and its counts are kept as floors.
2. Groups: regex plus a name table. G0 gate, G1c chapters, G1f final mission, G1m missions 8-13, G2 side strands and secret beats,
   G3 easy feats, G4m medium grind, G4h hard grind, G4p platinum. On p00 the counts are G1m 6, G2 15, G3 11, G4h 7, G4m 9.
   Data promotion: G4h becomes G4m when its 24 h gain is > 2x tester + 2. Data demotion: G3 becomes G4h when it is still at the tester floor.
3. Medians: P(T) is the geometric mean of a damped ln N vs ln(1+h) trend (0.8) and the 24 h velocity (x0.7), with sigma_lnP set by the
   disagreement between them. M1 is a damped logit trend on the states (last 36 h, <= 60 states, damping capped at 1.3). M2 is count flow
   C + v*Delta*f_g over P(T). M3 is chain gap closure, integrated hourly with Euler steps, with lambda floored at 0.5 x the median of the
   strong rows and capped at 0.5/h. Missions take as parent the chapter just above them. Chain rows blend 0.25/0.25/0.5, other rows
   0.4 M1 + 0.6 M2. Count floor: 0.98*C_now/P(T). The medians get PAV along ch1..ch4 -> final -> platinum.
   T_eff = T - gap/2.
4. Constraints per quantile level: PAV down the chain, missions >= final, 100% (id 14) <= final, platinum <= every row.
   The gate row (>= 99.95 in every post-tester state) is fixed at [99.97, 100, 100, 100, 100].
5. Spreads: a split normal in logit with s^2 = (S_G * sqrt(h/108.5))^2 + sigma_lnP^2 + 1/C. Skew is up for late chain and grind and
   down for early or common rows; rows above 20% get a fatter downside (to hedge an N wave). Floor 0.15. Floor mass: q05 (q25) goes to
   0.01 when P(rate <= 0.01) > 5% (25%). A per-level count floor uses P(T) at the matching quantile. Sanity: |dlogit| > 4 gets a 50/50
   blend with the last rate and a 1.5x widening, except upward moves of G1/G2 rows below 1%.
6. Self-calibration: runs when the post-tester history is >= 24 h. Up to 12 origins h0 in [max(first+3, 12), h_hi] use the case's
   ln-time ratio ((1+h_tgt)/(1+h_at) = 2.79 for f00). The grid is damp {0.6..1.5} x smult {0.7..1.45} x skew {0.8, 1, 1.25}, and the
   result is shrunk 50% toward the priors. (v1 text; v2 changed the origins and the grid, see "v2" below.) The per-group guard compares hindcast loss for ours, the house curve (re-implemented per RULES)
   and persistence. A group keeps ours only if ours <= both; otherwise it gets a 50/50 logit blend with the better house method.
7. Fallbacks: per-trophy and per-case try/except fall back to the persistence row, and a final validator checks every row before
   writing. stderr shows one JSON line per case with fallback counts, calibration_ran, params, calib losses, guard, diag (P(T), wide, sanity).

## Checks (python 3.13, `-P -s`)
- Kit p00/p01: valid, two runs byte-identical, 0.02 s, fallbacks 0. No calibration (launch night only, priors only).
- Synthetic f00-like cut (358 reads, 22 distinct) and worst case (358 reads, 358 distinct): valid, byte-identical, ~0.25 s each
  (0.5 s for both), fallbacks 0, calibration_ran true, 12 origins.
- RULES worked example in tools/backtest.py: 0.403404 (matches).
- Fuzz (40 mutated cases: random nulls, an all-null trophy, N halved, one read, launch-night only, short rate lists): 0 invalid, 0 fallbacks.
- Edge cases through main() itself: an empty history writes a valid persistence file (fallback_case=1, visible on stderr), a
  1-read history runs the priors path with 0 fallbacks, and an unreadable .in file is reported and skipped without stopping later cases.
- Final run (commit eb5442e): kit 0.02 s, synthetic pair 0.52 s, all byte-identical on a second run, all outputs valid.
  On the synthetic f00-like cut, calibration picked damp 0.8, smult 1.225, skew 1.125. The guard kept ours for G2/G3, blended
  G1c/G1m/G4m with persistence, and blended G1f/G4h/G4p with the curve. The worst-case variant kept ours for G1c/G1f/G1m as well.

## Backtest table (SYNTHETIC: plumbing/timing only; the generator encodes our own assumptions, so do not tune on it)
Checkpoints h = 35.5, 47.5, 59.5, horizon 108.5 h, mean pinball (logit):

| group | n | ours | persist | curve |
|---|---|---|---|---|
| G0 | 3 | 0.022 | 0.107 | 0.107 |
| G1c | 12 | 0.600 | 1.383 | 5.586 |
| G1f | 3 | 4.161 | 5.829 | 7.415 |
| G1m | 18 | 0.728 | 1.454 | 5.102 |
| G2 | 45 | 0.220 | 0.509 | 2.499 |
| G3 | 33 | 0.160 | 0.287 | 0.415 |
| G4h | 21 | 2.411 | 2.129 | 2.952 |
| G4m | 27 | 0.548 | 1.033 | 2.136 |
| G4p | 3 | 1.331 | 0.943 | 1.710 |
| TOTAL | 165 | 0.712 | 1.021 | 2.620 |

90% coverage (ours) is 0.80. History of the total: v0 persistence 1.019, edit A 0.761, B1 0.721, B2 0.796 (origins from first+3),
then 0.712 (origins from h=12). Synthetic G1f/G4h are poor because the generator's final-mission rush and grind earners all come after
the deadline. That is a generator assumption, not evidence.

## Known risks
- The hindcast uses day-1 origins (h0 12-21) whose dynamics (launch surge) differ from days 3-7. The guard may then pick house-method
  blends for groups where ours is actually better at long range. On synthetic data it blended G1c/G1m/G4m with persistence, which widens the bands.
- The G1c bands are wide (Ch3 q95 ~86% on synthetic) after the persistence blend and the per-level PAV pooling.
- The final mission and platinum depend on M3 lambda from tiny 24 h gains. They could under-predict a late rush, mitigated by skew up.
- Group names are hard-coded for the GTA VI list, with a regex fallback. A renamed or added trophy falls to the regex class.
- The practice (p00/p01) gets priors only. Its 90-minute horizon straddles the first refresh, so expect ~baseline loss there; it pays nothing.

## v2 (session s263, from the independent review briefs/forecast1_v1review_s263.md)

### MUST findings, re-checked against the live main.py
- Horizon ?-1 (medians too damped at 108 h in playtime-driven worlds; the right damping depends on the world): CONFIRMED.
  v1 had no fmult axis (`grep -n GRID_ main.py` at 483e2c9 showed only GRID_DAMP/SMULT/SKEW; PRIORS fmult fixed at 1.0), and all
  hindcast origins were day-1 cuts (h0 12-21 on f00). One part of the finding was already met: those ln-ratio origins have horizons
  (ratio-1)(1+h0) = 23-39 h on f00, so they are not short. The real gap was origin age (day 1 only), not horizon length.
  Fixed: 0aa1fb6 (grid), fe79913 (origins), 3b776b6 (origin guard), details below.
- Rules ?-1 (LICENSE without SPDX line): ALREADY FIXED by the operator in 483e2c9. `head -1 LICENSE` prints `SPDX-License-Identifier: MIT`.
- Rules ?-3 (crash on missing horizon_minutes or empty history): the crash was ALREADY FIXED in eb5442e.
  `grep -n 'hist = case.get("history") or \[\]' main.py` finds baseline_case's guard. An empty-history case (out/edge/e00, and
  out/e2 a_empty / b_empty_nohz built from p01) writes a valid persistence file with a visible fallback_case=1.
  The optional extra is done in 672c5f2: a missing horizon_minutes now derives the horizon from target-at and runs the model. p01 without
  horizon_minutes gives a file byte-identical to p01 with it, with 0 fallbacks.
- Correctness lens: no MUST (its one SHOULD is done below).

### Changes (one commit each; CHECKS green after each)
1. 0aa1fb6 calibration grid: new GRID_FMULT {0.75, 1, 1.25, 1.5, 2} on F_G, and GRID_DAMP {0.6, 0.8, 1, 1.3, 1.6}. With the 50%
   shrink to the priors, the reachable top is damp 1.3 and fmult 1.5, the values that won the reviewer's cohort worlds; the bottom,
   0.8/0.875, keeps the saturation worlds. Coordinate search: damp x fmult (25 median sets, smult = skew = 1), then smult x skew
   (15) on the best medians. That is fewer predict calls than v1's 75-point joint grid. Axes <= 5 values; <= 12 origins; <= 60 states per fit (thin).
2. fe79913 hindcast origins: late cuts at h_end - {24, 30, 36, 42, 48, 54} h (those >= max(first+3, 12)), scored against the last
   state, so days 2-3 dynamics and slow cumulative rises are in the loss. The ln-ratio day-1 origins fill the rest, up to 12.
   3b776b6: the fixed origins are used only when the case's own horizon is >= 24 h. stderr `calib.fixed_origins` counts the origins
   scored at the last state, and that includes the last ln-ratio origin, whose h1 equals h_end.
3. ec4b2d1 (horizon ?-2) s_hi >= 2.0 for G4h/G4m/G4p rows with median < 0.2%. This widens the thin upper tail of rows near the 0.01 floor.
4. 91bfc48 (rules ?-2) build_states drops a read that repeats any earlier state (stale or reverted page), not only the previous one.
   Test: s00 plus 320 re-served previous pages, 20 s after each slot from h > 6. The output is within 0.016 pp of clean (the rest comes from the raw-read
   house curve in the guard), valid, 0 fallbacks.
5. 088d671 (correctness ?-1, rules ?-4) leading nulls are seeded with the trophy's first observed rate, not 0. Test: s00 with id 55
   null for h < 40. The row went [26.07, 41.04, 52.74, 61.14, 72.06] vs clean [28.80, 44.40, 56.14, 64.34, 74.74], sanity 0.
   Changes 4 and 5 leave the kit and synthetic outputs byte-identical (cmp against the previous commit).

### v2 checks (python 3.13, `-P -s`)
- Kit p00/p01: valid, two runs byte-identical, 0 fallbacks, calibration_ran false (launch night only, as before).
- Synthetic s00 (f00-like) and s01w (worst case, 358 reads, 358 distinct): valid, two runs byte-identical, also identical under
  PYTHONHASHSEED 0 and 1. 0.62-0.68 s for both together (~0.33 s per case), 0 fallbacks, calibration_ran true, 12 origins.
  s00 picks damp 0.8, fmult 1.5, smult 1.225, skew 1.125. The guard keeps ours for G1c/G1f/G1m/G2/G3, blends G4h/G4p with the curve and G4m with persistence.
- tools/backtest.py: worked example 0.403404. Worst variant at 0.44 s per checkpoint, 0 fallbacks.
  Synthetic TOTAL 0.714 (v1 0.712), worst 0.712. By group vs v1: G1c 0.600 -> 0.848, G1m 0.728 -> 1.069 (the guard now keeps ours
  instead of the persistence blend), G1f 4.161 -> 3.131, G4h 2.411 -> 2.131, G4p 1.331 -> 1.212; cov90 0.78. PLUMBING ONLY: this
  generator is a saturation world, which the review shows rewards damping, so nothing was chosen from it.
- Edge: empty history -> valid persistence file (fallback visible), short-horizon (90 min) variant of s00 valid with 0 fallbacks.

### Not done in v2
- Horizon ?-3 (NICE, smult range 1.0-1.3): not changed. The shrunk smult range is 0.85-1.225, so the top is already below 1.3.
- Rules ?-5 (NICE, README "self-calibrates" sentence): no change needed, because B2 ships.
- The reviewer's cohort worlds (A-E) were not re-run against v2: their generator is outside this repository, and this session works
  only inside it. So it is UNVERIFIED that calibration actually picks the high damp/fmult end in those worlds.

### Next steps (v3)
1. Re-run the reviewer's cohort worlds A-E and the builder synth against v2. Check that calibration picks damp/fmult near the top in
   cohort worlds and near the prior in saturation worlds. If it is too timid, try a smaller shrink (e.g. 30%) only on damp/fmult.
2. Weight hindcast origins by age (the late fixed-horizon cuts look most like days 3-7), for the grid loss and for the guard.
3. Guard weights from loss ratios instead of a hard 50/50.
4. S_G per group from hindcast residual quantiles (quantile matching), keeping <= 8 tuned numbers.
5. When real post-launch reads exist, run `tools/backtest.py --case <file>` on them and replace the synthetic table.
6. Keep the run < 2 s worst case and byte-identical. Re-run `tools/check_out.py` and the double-run cmp after every change.
