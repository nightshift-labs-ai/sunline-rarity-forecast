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

## v3 (session s265, 2026-11-19)

### Inputs this run
- Operator practice diagnosis (/home/agent/makefun/briefs/fc_s264/practice_diag/): v2 scored 1.31 on p00/p01 with cov90 0.04. Every
  read there has players_tracked 638, so build_states collapses them to one state and v2 takes the "persist" branch with a ~0.3-0.5
  logit band. The page later refreshed to ~3,868 players (~6x), diluting every non-gate row.
- Operator cohort world simulator (fc_s264/sim.py, 33 worlds = 11 types x 3 seeds, score.py). It is our own guess at the world, so it was
  used as a check only. No constant was tuned to it: every constant below is the value given in the brief.

### Changes (one commit each; CHECKS green after each)
1. 914fdca M2 feasibility cap (medians): the projected new earners over the span are <= 0.8 x (players_now - earners_now)
   + rho x (p_t - N_now), with rho = clamp(gain_since_ref / players_added_since_ref, 0, 1). It applies only when players were added (dn_hist > 0).
   Sim 0.360 -> 0.317, and all 11 world types improved. Added tools/checks.sh (CHECKS a/b/c in one script).
2. 98ebb89 calibration: smult = min(calibrated smult, 1.0). Sim 0.317 -> 0.294, cov90 0.99 -> 0.97. All 11 types improved or tied.
   Coverage moved toward 0.90 but is still above it (0.97 pooled).
3. 612bbf0 platinum / 100% rows: median >= logit(0.04%) at the target, before the chain PAV (apply_constraints still runs after).
   Sim 0.294 -> 0.292, G4p 0.834 -> 0.706 (cov90 0.79 -> 0.91). MIXED by world type: W8_fastN_slowP 0.307 -> 0.326,
   W10_lateWave 0.341 -> 0.350, W2_fastN 0.257 -> 0.261 got WORSE. W1/W4/W5/W6/W7 got better. G4h rose 0.500 -> 0.505 (the 100% rows).
   It is kept because the mean drops and the floor is a domain fact, not a fit. Revisit it if real day-7 platinum rates come in below 0.04%.
4. 15b9980 no-refresh path (no_refresh_q, refresh_prob): when every state has the same players_tracked N0, the forecast is a deterministic
   mixture. Weight 1-p goes on the current rate. Weight p goes on a refresh to N1 = N0*g (ln g ~ N(ln 4, 0.8), truncated at g >= 1)
   with E_i + f_i*(N1-N0) earners, where f_i = min(1, kappa*max(E_i - E_plat, 0)/N0) and ln kappa ~ N(ln 0.3, 1). E_plat is the platinum
   count, or the lowest non-gate count if there is no platinum. p = P(first refresh in (A, A+D] | none in [0, A]), with the period
   log-uniform on [0.5, 6] h and a uniform phase. A = the span of the reads, D = target - last read. p00 0.885, p01 0.935 (they match a hand
   calculation). Grid: 41 g nodes x 9 kappa nodes + the no-refresh atom. Each quantile is the smallest atom whose cumulative weight
   is >= tau. Gate rows stay at GATE_ROW. Calibration is skipped on this path (it never ran on launch night anyway).
   Practice (operator truths, mean of p00/p01), v2 -> v3: a_pure6x 1.490 -> 0.405, a2_pure6x_gate16 1.679 -> 0.594, b_board 1.318 -> 0.317,
   b+_strong_new 0.935 -> 0.199, c_mild3x 0.797 -> 0.165. cov90 went from 0.00-0.07 to 0.95-1.00.
   Multi-N histories never take this path: world sim and synth s00/s01w are byte-identical to 612bbf0.

### v3 checks (python 3.13, `-P -s`, tools/checks.sh)
- (a) Kit p00/p01: two runs byte-identical, check_out OK, 0 fallbacks.
- (b) s00 0.35 s, s01w (worst, 358 distinct reads) 0.46 s. 0 fallbacks, calibration_ran true, params damp 0.8, fmult 1.5, smult 1.0, skew 1.125.
- Edge (in-process): a single read (p 0.826), a far target with one N (p 1.0), and no platinum row are all valid with 0 fallbacks.
  refresh_prob gives 0 when A >= 6 h or D <= 0, and then the main model runs.
- (c) World sim (mean pinball / cov90), house curve | v2 (e0b02a4) | v3 (15b9980):

| world type      | curve      | v2         | v3         |
|-----------------|------------|------------|------------|
| W1_base         | 0.322/0.94 | 0.344/0.95 | 0.261/1.00 |
| W2_fastN        | 0.383/0.95 | 0.325/0.96 | 0.261/0.99 |
| W3_slowN        | 0.324/0.95 | 0.307/0.98 | 0.235/1.00 |
| W4_fastP        | 0.338/0.96 | 0.321/0.96 | 0.224/1.00 |
| W5_slowP        | 0.333/0.95 | 0.370/0.99 | 0.325/0.95 |
| W6_stall        | 1.016/0.55 | 0.515/0.92 | 0.466/0.88 |
| W7_satur        | 0.359/0.97 | 0.338/0.96 | 0.255/0.99 |
| W8_fastN_slowP  | 0.416/0.93 | 0.343/0.98 | 0.326/0.97 |
| W9_slowN_fastP  | 0.317/0.97 | 0.330/0.95 | 0.226/1.00 |
| W10_lateWave    | 0.497/0.98 | 0.387/0.95 | 0.350/0.92 |
| W11_backfill    | 0.438/0.96 | 0.379/0.95 | 0.286/0.97 |
| MEAN            | 0.431/0.92 | 0.360/0.96 | 0.292/0.97 |

  Step means: v2 0.360 -> m2cap 0.317 -> smult<=1 0.294 -> plat floor 0.292 -> no-refresh 0.292 (unchanged, as designed).
  Per group v3: G0 0.022, G1c 0.222, G1f 0.331, G1m 0.245, G2 0.296, G3 0.173, G4h 0.505, G4m 0.308, G4p 0.706 (worst group still G4p).

### Not done in v3
- The planned multi-agent review of the v3 diff was not run (the launch was declined in this session). Only the edge tests above were run.
- Pooled 90% coverage is still 0.97 (target 0.90). The bands are still too wide in most world types. smult was only capped, not lowered further.
- The no-refresh path models ONE refresh. For a far target with one N (p -> 1), several refreshes would dilute more. It only matters if a
  live case ever arrives with a single players_tracked value and a long horizon.
- v2 next steps 2-5 (age-weighted origins, guard weights from loss ratios, quantile-matched S_G, real-read backtest) are not started.

### Next steps (v4)
1. Narrow the bands toward cov90 0.90 in a principled way, e.g. quantile-matched S_G from hindcast residuals (v2 list item 4). Check it in
   every world type, not only on the mean.
2. Look at W8_fastN_slowP / W10_lateWave, where the plat floor hurt. Test whether the floor should apply to the 100% rows (G4h) or to G4p only.
3. W6_stall is still the worst type (0.466). Check whether project_p over-projects N after a stall.
4. When real post-refresh reads exist: re-check the no-refresh priors (g ~ 4, kappa ~ 0.3, period 0.5-6 h) against the observed refresh.
5. Keep < 2 s worst case, byte-identical double runs, and tools/checks.sh green after every change.

## v4 (s265, operator stress test with the independent agent-based sim2)

### Changes (both inside the model; each one checked with (a) and (c)+(d) before its commit)
1. `predict()`: upper-tail lift for rows that have not started (last rate < 0.5 %, not gate, not G4p or 100 % rows):
   the median goes up 0.3 logit and the upper split-normal spread s_hi is doubled, so the q75/q95 offsets are x2. Method tag `+lift`.
2. `forecast_case()`: hard grinds (G4h) below 2 % never take the `persist` guard. They get the union of our band and the house curve's
   band (q05 = min, q95 = max, q25/q50/q75 = logit average). Method tag `+union`. Not applied on the no-refresh path.

### Scores (MEAN: loss / cov90)
| sim | v3 | after step 1 | after step 2 (v4) |
|---|---|---|---|
| s264 world sim (fc_s264, 11 types x 3 seeds) | 0.292 / 0.97 | 0.284 / 0.98 | 0.284 / 0.98 |
| sim2 (fc_s265, 10 types x 2 seeds) | 0.923 / 0.66 | 0.774 / 0.80 | 0.749 / 0.80 |

s264 per world type, v4 (loss/cov90/miss): W1_base 0.252/0.99, W2_fastN 0.254/0.99, W3_slowN 0.236/1.00, W4_fastP 0.234/1.00,
W5_slowP 0.283/0.99, W6_stall 0.431/0.93, W7_satur 0.268/0.99, W8_fastN_slowP 0.285/0.99, W9_slowN_fastP 0.230/1.00,
W10_lateWave 0.359/0.92, W11_backfill 0.297/0.97. Per group v4: G4h 0.468/1.00, G4p 0.723/0.97.
sim2 per world type, v4: A2_hourly_fastflat 0.632/0.89, A3_weekend_surge 0.560/0.89, A4_late_backfill 0.619/0.87,
A5_stall_precut 1.431/0.68, A6_stall_pretgt 0.538/0.92, A7_nearcut_slow80 0.580/0.91, A8_casual_flood 0.571/0.89,
A9_fast60_grinders 0.515/0.91, A10_frozen 1.465/0.15 (A1 not recorded). Per group v4: story 1.141/0.64, grind 1.007/0.93, plat 0.336/0.82.
(a) byte-identical and valid on p00/p01, 0 fallbacks; (b) s00 0.27 s, s01w 0.47 s, calibration_ran True, 0 fallbacks.

### Not done in v4 (from the brief's v4 list)
- Item 3: when the calibration is pinned at the grid edge (damp 1.3, fmult 1.5), allow smult > 1 or a wider skew.
- Item 4: data-driven chain membership for secret trophies (rows 37/38/48 are sim2's worst).
- Item 5: saturation-aware cap for rows at 40 % or more.
- Item 6: platinum/100 % floor tied to N instead of a fixed 0.04 %.
- The principled version of step 1 (a chain-front bound in place of the constants 0.3 / x2).
- Story rows in sim2 are still too narrow (cov90 0.64), and A5_stall_precut / A10_frozen are still the worst types.

## v5 (s266, 2026-11-19; one Edit per change, then (a)+(b) via tools/checks.sh plus (c) s264 and (d) sim2; keep only if neither mean rises > 0.01)

### Changes kept
1. a4d8f95 platinum / 100 % rows: the fixed 0.04 % median floor is replaced by median >= logit(max(last rate, 100 x (tester earners + 5) / P(T))).
   The upper tail is unchanged (s_hi >= 2.0 for grind/plat rows below 0.2 %). sim2 0.749 -> 0.745 (plat 0.336 -> 0.237), s264 0.284 -> 0.286.
2. 1bec9ec saturation cap for rows at >= 40 % (only when players were added since the ref state): median <= logit((E_now + rho x (P(T) - N_now)) / P(T)),
   rho = clamp(gain / dN_hist, 0, 1), the same marginal ratio as the M2 cap. Applied before the count floor. sim2 0.745 -> 0.726, s264 0.286 -> 0.284.
   PLAT_FLOOR (the constant) is now unused; it is left in place.

### Changes tried and reverted (diffs kept in /tmp/s266_step*.diff, not committed)
- Item 1, secret trophies 37/38/48 as story beats. The data in sim2 (f00 cut vs truth, all 20 worlds) says yes: id 38 ends between chapters 3 and 4,
  id 37 near chapter 4, and id 48 near the final. But at the cut only id 38 (and id 37 in A9) has >= 30 earners.
  (a) Matching every secret G2/G3 row (mean |logit d| < 0.3 to a story item) and regrouping it as G1m: sim2 0.749 -> 0.760, s264 got worse too (W10 0.359 -> 0.427). Reverted.
  (b) Narrower: no side strands ("final mission for", "hunt"), group unchanged, matched rows only join the chain closure (mean |d| < 0.5):
      sim2 0.726 -> 0.717 (story 1.089 -> 1.056, A9 0.474 -> 0.460) but s264 0.284 -> 0.306. Reverted: the matches are spurious in s264's world.
- Item 3, smult up to 1.3 when the calibration is pinned (raw damp 1.6 and fmult 2.0): sim2 0.745 -> 0.730 but s264 0.286 -> 0.306. Reverted
  (the brief's stated risk: hindcast horizons are shorter than the target's).

### Scores (MEAN loss / cov90)
| sim | v4 | step 2 (plat floor) | step 4 (sat cap) = v5 |
|---|---|---|---|
| s264 world sim (11 types x 3 seeds) | 0.284 / 0.98 | 0.286 / 0.98 | 0.284 / 0.98 |
| sim2 (10 types x 2 seeds) | 0.749 / 0.80 | 0.745 / 0.80 | 0.726 / 0.83 |

s264 per world type, v4 -> v5 (loss/cov90): W1_base 0.252 -> 0.267/0.98, W2_fastN 0.254 -> 0.258/0.98, W3_slowN 0.236 -> 0.240/0.98,
W4_fastP 0.234 -> 0.242/0.98, W5_slowP 0.283 -> 0.290/0.99, W6_stall 0.431 -> 0.450/0.93, W7_satur 0.268 -> 0.264/0.99,
W8_fastN_slowP 0.285 -> 0.290/0.99, W9_slowN_fastP 0.230 -> 0.225/1.00, W10_lateWave 0.359 -> 0.339/0.93, W11_backfill 0.297 -> 0.262/1.00.
s264 per group v5: G0 0.022, G1c 0.269, G1f 0.323, G1m 0.262, G2 0.255, G3 0.173, G4h 0.478, G4m 0.308, G4p 0.793/0.88 (v4 G4p 0.723/0.97, G4h 0.468).
sim2 per world type, v4 -> v5 (loss/cov90): A1_mix_irreg (n/a) -> 0.552/0.93, A2_hourly_fastflat 0.632 -> 0.632/0.91, A3_weekend_surge 0.560 -> 0.564/0.89,
A4_late_backfill 0.619 -> 0.600/0.88, A5_stall_precut 1.431 -> 1.416/0.70, A6_stall_pretgt 0.538 -> 0.507/0.94, A7_nearcut_slow80 0.580 -> 0.556/0.93,
A8_casual_flood 0.571 -> 0.556/0.91, A9_fast60_grinders 0.515 -> 0.474/0.95, A10_frozen 1.465 -> 1.402/0.23.
sim2 per group v5: gate 0.022, story 1.089/0.70, side 0.400/0.87, collect 0.723/0.90, grind 1.007/0.93, plat 0.237/0.82.
(a) p00/p01 byte-identical and valid, 0 fallbacks; (b) s00 0.28 s, s01w 0.48 s, calibration_ran True, 0 fallbacks.

### Not done in v5 / next
- The s264 mean is flat (0.284). Several s264 types got slightly worse (W1 +0.015, W6 +0.019, W4/W5 ~+0.007), mostly from the plat floor (G4p 0.723 -> 0.793).
  The saturation cap won back W10/W11. Check whether the (tester + 5) floor should use the low P(T) quantile.
- Item 1 helps sim2 only. A safer match needs a stronger test than the level: e.g. the row's gain must track the matched item's gain over the last 24 h.
- Item 3 (wider bands when pinned) helps sim2 only; the simulators still disagree about post-cut motion. Not revisited.
- Not run this session: a multi-agent review (no time).
