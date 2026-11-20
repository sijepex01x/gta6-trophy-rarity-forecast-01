# gta6-trophy-rarity-forecast-01

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/sijepex01x/gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/sijepex01x/gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecast, for every trophy of Grand Theft Auto VI on PlayStation 5, its earn
rate on Exophase at 2026-11-26T00:00:00Z, as five quantiles per trophy.
Entry for the [gta6-trophy-rarity-forecast-01 bounty](https://make.fun/bounty/gta6-trophy-rarity-forecast-01) on Make.fun.

## The model, in plain words

A trophy's earn rate is earners over tracked players, and the two move for
different reasons, so the program models them separately.

- **Earners:** for each trophy it fits a recency-weighted line to
  log(earners) against log time since release (earners grow as players play).
  The slope is shrunk toward its tier's slope — platinum, gold, silver and
  bronze trophies grow very differently — and the line is re-anchored at the
  weighted mean point, so shrinking the slope pivots the line where the data
  is instead of around zero.
- **Tracked players:** it fits a line to log(tracked players) against the
  same clock and reads it at the target. This is the dilution term: when
  Exophase refreshes and the tracked count jumps, rates fall, because the
  new players have not earned the trophies yet.
- **The forecast rate** is forecast earners over forecast tracked players.
  Earn growth pulls rates up; denominator growth pulls them down. A trophy
  already at ~100% is pinned there — the documented launch-night refresh
  kept the 100% trophy at 100% through a 6x jump in tracked players.
- **The spread** is a random walk on the logit scale that widens with the
  horizon (0.5·√days, the house baseline's scale), plus a 0.35 floor for the
  structural uncertainty of a week nobody has seen (refresh timing,
  denominator jumps) and the trophy's own fit residual. The floor is set
  from the final's ~4.5-day horizon, not tuned on the 90-minute practice.

## Practice results (honest)

The practice cases straddle Exophase's first refresh, and the kit does **not**
contain the true answer rates — they live on the server. The losses below
are scored against proxies built from what the rules document about the
refresh (638 → 3,868 players tracked, 943 → 4,276 trophies earned, every
rate but the 100% one lower):

| proxy | this entry | house baseline |
|---|---|---|
| aggregate-consistent (id 2 stays 100, other 54 × 0.2207, chosen so total earned matches 4,276) | **1.216** | 1.402 |
| pure dilution (other 54 × 638/3868) | **1.503** | 1.688 |

The documented house practice loss is ~1.51 with typical miss ~0.68 and 90%
coverage 0; it sits between the two proxy-implied house losses (1.402 /
1.688), and the aggregate proxy reproduces the documented typical miss
(0.677 vs ~0.68), which is a consistency check on the proxy range. Both
proxies agree this entry beats the house baseline on practice by ~0.19,
driven by the wider spread — the refresh is a ~1.5-logit shock no honest
90-minute band covers (practice 90% coverage is 0 for both entries).

Practice is a weak guide to the final: its 90-minute horizon rewards narrow
bands, while the final's ~4.5-day horizon rewards a good median plus an
honest wide spread. The entry is built for the final, not fitted to practice.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` in the input directory and writes one `<id>.out` per
case: `{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}, ...]}`,
five quantiles in percent, non-decreasing. Standard library only, no
network, deterministic (two runs write byte-identical outputs), ~0.05 s per
case, outputs written mode 0644.

---

<sub>Entered on [make.fun](https://make.fun/?ref=s3jx158p&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>

