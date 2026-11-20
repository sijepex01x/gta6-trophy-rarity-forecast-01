"""Forecast GTA VI trophy earn rates on Exophase at a case's target.

Model (one paragraph for the README): each trophy's earn rate is earners over
tracked players, and the two move for different reasons, so the program models
them separately.  For every trophy it fits a recency-weighted line to
log(earners) against log time since release -- earners grow as players play --
with the slope shrunk toward its tier's slope (platinum/gold/silver/bronze
trophies grow very differently), and it fits a line to log(tracked players)
against the same clock, so the forecast rate is forecast earners over forecast
tracked players: earn growth pulls rates up, denominator growth (Exophase
refreshes dilute rates when new players arrive who have not earned the
trophies yet) pulls them down.  A trophy already at ~100% is pinned there.
The spread is a random walk in logit space that widens with the horizon, plus
a floor for the unseen-week structural uncertainty and the trophy's own fit
residual, so the 90% band is honest about a 4.5-day horizon rather than the
90-minute practice one.

Standard library only, no network, deterministic: no randomness anywhere, and
files are read in name order with fixed JSON formatting, so two runs write the
same bytes.  Outputs are written with plain open() (mode 0644 by default);
never a 0600 temporary file.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Random-walk scale of a rate's move, logit units per square-root day
# (the house baseline's 0.5, kept: it is the documented scale).
RW_SIGMA = 0.5
# Floor on the logit spread: structural uncertainty about a week nobody has
# seen (refresh timing, denominator jumps).  A judgment constant, not tuned
# on the 90-minute practice; at the final horizon it adds only ~5% in
# quadrature on top of the random-walk term, which carries the honesty.
SPREAD_FLOOR = 0.35
# Recency half-life for the trend fits (hours): launch-night reads are one
# frozen page, later reads are what the final's week turns on.
HALF_LIFE_HOURS = 24.0
# Shrinkage strength for a trophy's slope toward its tier's slope, in
# effective reads (below): reads frozen between Exophase refreshes are not
# independent observations, so a raw read count would overstate information.
SHRINK_READS = 2.0
# Bounds on the tracked-player forecast, as a multiple of the last read.
PLAYERS_MIN_MULT = 1.0
PLAYERS_MAX_MULT = 100.0
# A trophy this close to everyone having it is pinned: the documented refresh
# kept the 100% trophy at 100% through a 6x jump in tracked players.  The
# threshold is 99.9, not 99: only a trophy essentially at 100% has that
# evidence behind it; a trophy at 99.2% goes through the normal model.
SATURATED_RATE = 99.9
SATURATED_SIGMA = 0.30
# Fit-residual contribution to the spread, floored and capped.
FIT_FLOOR = 0.10
FIT_CAP = 1.0
FIT_DEFAULT = 0.30


def clamp_rate(x):
    return min(99.99, max(0.01, x))


def logit(pct):
    p = clamp_rate(pct) / 100.0
    return math.log(p / (1.0 - p))


def sigmoid(lg):
    if lg >= 0:
        return 1.0 / (1.0 + math.exp(-lg))
    e = math.exp(lg)
    return e / (1.0 + e)


def round4(x):
    """Round to 4 decimals, half up (as the house baseline does)."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value == int(value) else value


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def log_time(at, release):
    """ln(1 + hours from release to `at`); reads before release count as 0."""
    hours = (at - release).total_seconds() / 3600.0
    return math.log1p(max(hours, 0.0))


def wls(xs, ys, ws):
    """Weighted least squares for y ~ a + b*x.

    Returns (a, b, resid_sd, xm, ym): the line passes through the weighted
    mean point (xm, ym), so a caller that shrinks the slope can re-anchor the
    line there instead of pivoting it around x = 0.

    With no variance in x, or a single point, the slope is 0 and the level is
    the weighted mean.  The residual sd is 0 when fewer than 3 points remain.
    """
    sw = sum(ws)
    if sw <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    xm = sum(w * x for w, x in zip(ws, xs)) / sw
    ym = sum(w * y for w, y in zip(ws, ys)) / sw
    sxx = sum(w * (x - xm) ** 2 for w, x in zip(ws, xs))
    if sxx <= 1e-12:
        resid = [y - ym for y in ys]
        sd = _sd(resid, ws) if len(ys) >= 3 else 0.0
        return ym, 0.0, sd, xm, ym
    sxy = sum(w * (x - xm) * (y - ym) for w, x, y in zip(ws, xs, ys))
    b = sxy / sxx
    a = ym - b * xm
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    sd = _sd(resid, ws) if len(ys) >= 3 else 0.0
    return a, b, sd, xm, ym


def _sd(values, ws):
    sw = sum(ws)
    if sw <= 0 or len(values) < 3:
        return 0.0
    mean = sum(w * v for w, v in zip(ws, values)) / sw
    var = sum(w * (v - mean) ** 2 for w, v in zip(ws, values)) / sw
    return math.sqrt(var)


def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def forecast_case(case, name):
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    if not case["history"]:
        raise ValueError(f"{name} has no history")

    release = parse_time(case["game"]["release_date"] + "T00:00:00Z")
    target = parse_time(case["target"])
    x_target = log_time(target, release)
    days = case["horizon_minutes"] / 1440.0
    rw = RW_SIGMA * math.sqrt(days)

    history = sorted(case["history"], key=lambda r: r["at"])
    last = history[-1]
    t_last = parse_time(last["at"])
    n_last = last["players_tracked"]

    # Recency weights: a read a half-life older counts half.
    times = [parse_time(r["at"]) for r in history]
    weights = [0.5 ** ((t_last - t).total_seconds() / 3600.0 / HALF_LIFE_HOURS)
               for t in times]
    xs = [log_time(t, release) for t in times]
    log_n = [math.log(max(r["players_tracked"], 1)) for r in history]

    # Tracked players at the target: log-linear in log time, never falling,
    # capped so one wild early jump cannot dilute the forecast to nothing.
    _, d_n, _, _, _ = wls(xs, log_n, weights)
    d_n = max(d_n, 0.0)
    c_n = sum(w * (y - d_n * x) for w, x, y in zip(weights, xs, log_n)) / sum(weights)
    n_target = math.exp(c_n + d_n * x_target)
    n_target = min(max(n_target, PLAYERS_MIN_MULT * n_last),
                   PLAYERS_MAX_MULT * n_last)

    trophies = case["trophies"]
    n_troph = len(trophies)

    # Per-trophy log-earners fits, and each tier's slope (median) and
    # residual (median) for shrinkage.
    fits = []
    for i in range(n_troph):
        px, py, pw = [], [], []
        # Effective reads: reads frozen between Exophase refreshes carry no
        # new information about the slope, so count distinct states (a read
        # whose rate or tracked count changed from the previous usable read)
        # instead of raw reads.  On the flat practice history this is 1.
        n_eff = 0
        prev_state = None
        for j, r in enumerate(history):
            rate = r["rates"][i]
            if rate is None:
                continue
            state = (rate, r["players_tracked"])
            if state != prev_state:
                n_eff += 1
                prev_state = state
            earners = clamp_rate(rate) / 100.0 * max(r["players_tracked"], 1)
            px.append(xs[j])
            py.append(math.log(max(earners, 1e-6)))
            pw.append(weights[j])
        if px:
            a, b, sd, xm, ym = wls(px, py, pw)
            fits.append({"a": a, "b": b, "sd": sd, "xm": xm, "ym": ym,
                         "n": len(px), "n_eff": n_eff,
                         "last_rate": history[-1]["rates"][i]})
        else:
            fits.append({"a": None, "b": None, "sd": None, "xm": None,
                         "ym": None, "n": 0, "n_eff": 0, "last_rate": None})

    tiers = {}
    for i, t in enumerate(trophies):
        tiers.setdefault(t["tier"], []).append(i)
    tier_slope, tier_sd = {}, {}
    for tier, idxs in tiers.items():
        slopes = [fits[i]["b"] for i in idxs if fits[i]["b"] is not None]
        sds = [fits[i]["sd"] for i in idxs if fits[i]["sd"] is not None]
        tier_slope[tier] = median(slopes) if slopes else 0.0
        tier_sd[tier] = median(sds) if sds else FIT_DEFAULT

    # Fallback level for a trophy with no usable read: its tier's last rates.
    tier_last = {}
    for tier, idxs in tiers.items():
        vals = [fits[i]["last_rate"] for i in idxs
                if fits[i]["last_rate"] is not None]
        tier_last[tier] = median(vals) if vals else 1.0

    rows = []
    for i, t in enumerate(trophies):
        f = fits[i]
        tier = t["tier"]
        last_rate = f["last_rate"]
        if last_rate is not None and last_rate >= SATURATED_RATE:
            # Everyone has it; the documented refresh left it at 100%.
            med = clamp_rate(last_rate)
            sigma = SATURATED_SIGMA
        else:
            if f["a"] is not None:
                # Shrink the slope toward the tier's; the level stays the
                # trophy's own (it is measured, not guessed).  The weight
                # uses effective reads, so shrinkage still operates in the
                # final, where reads arrive every 10 minutes but only
                # refreshes change anything.  Re-anchor the shrunk line at
                # the weighted mean point, so changing the slope pivots the
                # line there instead of around x = 0.
                w = f["n_eff"] / (f["n_eff"] + SHRINK_READS)
                b = w * f["b"] + (1.0 - w) * tier_slope[tier]
                log_e = f["ym"] + b * (x_target - f["xm"])
                fit_sd = f["sd"] if f["sd"] is not None else tier_sd[tier]
            else:
                b = tier_slope[tier]
                level = tier_last[tier]
                log_e = math.log(max(level / 100.0 * n_last, 1e-6)) + b * (x_target - xs[-1])
                fit_sd = tier_sd[tier]
            rate = 100.0 * math.exp(log_e) / n_target
            med = clamp_rate(rate)
            fit_part = min(max(fit_sd, FIT_FLOOR), FIT_CAP)
            sigma = math.sqrt(rw * rw + SPREAD_FLOOR ** 2 + fit_part ** 2)

        lg = logit(med)
        qs = []
        prev = None
        for z in Z:
            q = round4(100.0 * sigmoid(lg + z * sigma))
            q = min(max(q, 0.01), 99.99)
            if prev is not None and q < prev:
                q = prev
            qs.append(q)
            prev = q
        rows.append({"id": t["id"], "q": qs})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(forecast, separators=(",", ":")) + "\n")
        # The grader reads /output as a different uid: plain open() takes its
        # mode from the umask (here 0660, unreadable to others), so force
        # 0644 explicitly.  Never ship a 0600 output.
        os.chmod(out_path, 0o644)


if __name__ == "__main__":
    main()
