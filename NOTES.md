# NOTES: sunline-rarity-forecast (build v1, session s263, 2026-11-19)

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
   result is shrunk 50% toward the priors. The per-group guard compares hindcast loss for ours, the house curve (re-implemented per RULES)
   and persistence. A group keeps ours only if ours <= both; otherwise it gets a 50/50 logit blend with the better house method.
7. Fallbacks: per-trophy and per-case try/except fall back to the persistence row, and a final validator checks every row before
   writing. stderr shows one JSON line per case with fallback counts, calibration_ran, params, calib losses, guard, diag (P(T), wide, sanity).

## Checks (python 3.13, `-P -s`)
- Kit p00/p01: valid, two runs byte-identical, 0.02 s, fallbacks 0. No calibration (launch night only, priors only).
- Synthetic f00-like cut (358 reads, 22 distinct) and worst case (358 reads, 358 distinct): valid, byte-identical, ~0.25 s each
  (0.5 s for both), fallbacks 0, calibration_ran true, 12 origins.
- RULES worked example in tools/backtest.py: 0.403404 (matches).
- Fuzz (40 mutated cases: random nulls, an all-null trophy, N halved, one read, launch-night only, short rate lists): 0 invalid, 0 fallbacks.

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

## Next steps (v2)
1. When real post-launch reads exist (practice or later kit), run `python3 tools/backtest.py --case <file>` on them and replace the
   synthetic table. Check the guard's choices and the hindcast losses per group.
2. Consider guard weights from loss ratios instead of a hard 50/50, and evaluate the guard only on origins >= 18 h.
3. Calibrate S_G per group from hindcast residual quantiles (quantile matching), keeping <= 8 tuned numbers.
4. Add the beat-notes drift table (section 3) as a soft lower bound on medians for rows 5, 6, 7 and 22-27 if hindcasts show undershoot.
5. Keep the run < 1 s and byte-identical. Re-run `tools/check_out.py` and the double-run cmp after every change.
