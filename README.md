# sunline-rarity-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/nightshift-labs-ai/sunline-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/nightshift-labs-ai/sunline-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

This is a deterministic Python program, standard library only, that forecasts the Exophase earn rate of every Grand Theft Auto VI PS5 trophy at 2026-11-26T00:00Z as five quantiles. An AI agent built it for Nightshift Labs. The model works in earner counts, not only in rates. It collapses repeated page reads into refresh states, and it projects the players-tracked count and each trophy's count growth. It keeps the story chapters in order and treats the tester-era counts as floors. Quantiles come from a split normal on the logit scale. When the case's history is long enough, the program calibrates its damping and spreads on that case's own history at run time. If anything fails, it falls back to the house persistence row.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=6m4cjq02&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
