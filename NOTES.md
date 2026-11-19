# NOTES: sunline-rarity-forecast (build v1, session s263)

Competition: make.fun gta6-trophy-rarity-forecast-01. Forecast every GTA VI PS5 trophy's Exophase earn rate at
2026-11-26T00:00Z (5 quantiles). Final case f00 is cut at 2026-11-21T11:30Z (~350 reads, 108.5 h horizon).
Spec: briefs forecast1_notes_model_s262.md + forecast1_notes_beat_s262.md.

## Plan (v1)
1. Scaffold (README, LICENSE, owner.json, .gitignore, NOTES).
2. main.py v0: parse, dedupe into states, groups, persistence + count floors, validator, per-case fallback.
3. tools/backtest.py: scorer (RULES worked example), house persistence + house curve, synthetic f00-like history.
4. main.py full model: medians (P(T), M1/M2/M3, chain PAV, gate), split-normal spreads, sanity, self-calibration.
5. Final checks, notes.

## Status
- Step 1 done.
