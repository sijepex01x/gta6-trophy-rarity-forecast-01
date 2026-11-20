"""Practice scorer for gta6-trophy-rarity-forecast-01 (NOT part of the entry).

Implements the pinball loss on the logit scale exactly as RULES.txt states it,
and builds the practice answers from what the kit documents about Exophase's
first refresh (the true answer rates are NOT in the kit; they live on the server).

Documented refresh (RULES.txt + competition.yaml):
  launch night: 638 players tracked, 943 trophies earned, every rate unchanged.
  refresh between 04:00Z and 04:30Z: 3,868 players tracked, 4,276 trophies
  earned; every rate but the one at 100% fell; the 05:00Z read unchanged again.

Primary proxy ("aggregate-consistent"): trophy id 2 ("Just Like Paradise") stays
at 100 (documented). The other 54 trophies scale by one common factor chosen so
the total trophies earned matches 4,276:
  factor = (4276*100/3868 - 100) / (943*100/638 - 100)  ~= 0.2207
i.e. the newly tracked players held almost no trophies besides id 2 (only ~103
newly earned trophies spread over the other 54). This proxy reproduces the
documented house-baseline practice stats (typical miss ~0.68 points, coverage 0).

Sensitivity proxy ("pure dilution"): earners frozen, every rate but id 2 scales
by 638/3868 ~= 0.1650. The truth is between the two proxies in the level of the
common scaling factor (the dilution proxy implies 4,173 total earned, not the
documented 4,276, so it is a level bound, not a realizable per-trophy answer);
the aggregate proxy is the better-grounded primary because it matches the
documented total exactly.

Usage:
  python3 score.py <outdir>   # scores <outdir>/p00.out and p01.out
"""
import json
import math
import sys
from pathlib import Path

KIT = Path.home() / "workspace/makefun/gta6-trophy-rarity-forecast-01-kit" / \
    "gta6-trophy-rarity-forecast-01-kit" / "input"
TAUS = [0.05, 0.25, 0.5, 0.75, 0.95]

# Documented refresh numbers (RULES.txt / competition.yaml).
OLD_PLAYERS, OLD_EARNED = 638, 943
NEW_PLAYERS, NEW_EARNED = 3868, 4276


def clamp(x):
    return min(99.99, max(0.01, x))


def logit(pct):
    p = clamp(pct) / 100.0
    return math.log(p / (1.0 - p))


def pinball(y, q, tau):
    d = logit(y) - logit(q)
    return 2.0 * max(tau * d, (tau - 1.0) * d)


def proxy_answers(case, kind):
    """Answer rates for a practice case, from the documented refresh."""
    last = case["history"][-1]
    rates = last["rates"]
    if kind == "aggregate":
        old_total = OLD_EARNED * 100.0 / OLD_PLAYERS
        new_total = NEW_EARNED * 100.0 / NEW_PLAYERS
        factor = (new_total - 100.0) / (old_total - 100.0)
        return [100.0 if r == 100 else r * factor for r in rates]
    if kind == "dilution":
        factor = OLD_PLAYERS / NEW_PLAYERS
        return [100.0 if r == 100 else r * factor for r in rates]
    raise ValueError(kind)


def score_case(out_path, case, kind):
    forecast = json.loads(Path(out_path).read_text())
    rows = {r["id"]: r["q"] for r in forecast["trophies"]}
    answers = proxy_answers(case, kind)
    trophies = case["trophies"]
    assert len(rows) == len(trophies) == 55
    losses, misses, covered = [], [], 0
    for i, t in enumerate(trophies):
        y = answers[i]
        q = rows[t["id"]]
        assert len(q) == 5
        for tau, qv in zip(TAUS, q):
            losses.append(pinball(y, qv, tau))
        misses.append(abs(y - q[2]))
        if q[0] <= y <= q[4]:
            covered += 1
    return {
        "loss": sum(losses) / len(losses),
        "typical_miss": sum(misses) / len(misses),
        "coverage90": covered / len(trophies),
    }


def main():
    outdir = Path(sys.argv[1])
    for kind in ("aggregate", "dilution"):
        tot_loss, tot_miss, tot_cov, n = 0.0, 0.0, 0.0, 0
        print(f"--- proxy: {kind} ---")
        for cid in ("p00", "p01"):
            case = json.loads((KIT / f"{cid}.in").read_text())
            s = score_case(outdir / f"{cid}.out", case, kind)
            print(f"  {cid}: loss {s['loss']:.6f}  typical miss {s['typical_miss']:.4f} pts"
                  f"  90% coverage {s['coverage90']:.3f}")
            tot_loss += s["loss"]
            tot_miss += s["typical_miss"]
            tot_cov += s["coverage90"]
            n += 1
        print(f"  MEAN: loss {tot_loss / n:.6f}  typical miss {tot_miss / n:.4f}"
              f"  90% coverage {tot_cov / n:.3f}")


if __name__ == "__main__":
    main()
