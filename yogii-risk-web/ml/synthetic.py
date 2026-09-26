"""Synthetic transaction generator for the Yogii risk prototype.

EVERYTHING HERE IS SYNTHETIC. The rows are drawn from hand-written
distributions; they are not real banking data and say nothing about real
fraud rates. The labels come from hand-written "anomaly severity" formulas
plus random noise, so the models learn a synthetic notion of "unusual".

Each row carries:
  * the 15 engine features (same definitions as src/app.js builds in the browser)
  * graph_score and receiver_score (the non-learned signals)
  * one anomaly label per component (amount, behavior, context)
  * a synthetic analyst risk rating in [0, 1] and an is_fraud flag (rating >= 0.6)
"""

from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta, timezone

import numpy as np

SEED = 42

AMOUNT_FEATURES = ["log_amount", "amount_ratio", "amount_z", "share_of_balance", "is_round"]
BEHAVIOR_FEATURES = [
    "is_new_recipient", "prior_count", "tx_count_30m", "value_24h_ratio",
    "indirect_connection", "is_p2m",
]
CONTEXT_FEATURES = ["is_night", "hour_deviation", "new_device", "account_age_days"]
ALL_FEATURES = AMOUNT_FEATURES + BEHAVIOR_FEATURES + CONTEXT_FEATURES

LABELS = ["label_amount", "label_behavior", "label_context"]
COLUMNS = (["tx_id", "timestamp"] + ALL_FEATURES
           + ["graph_score", "receiver_score"] + LABELS
           + ["analyst_rating", "is_fraud"])

# Weights of the synthetic analyst rating. These are Yogii prototype values
# chosen so the demo scenarios land in their documented bands; they are not
# RBI, NPCI or bank standards.
RATING = {
    "intercept": 0.05,
    "amount": 0.44,
    "behavior": 0.40,
    "context": 0.25,
    "graph": 0.45,
    "receiver": 0.85,
    "noise": 0.03,
}
FRAUD_RATING = 0.6

# Chain graph score, identical to the browser: [0, .2, .5, .8][hops] * (0.6 + 0.4 * similarity)
HOP_FACTOR = [0.0, 0.2, 0.5, 0.8]
RECEIVER_PARTS = [0.25, 0.2, 0.25, 0.3]


def clip01(x):
    return np.clip(x, 0.0, 1.0)


def severity_amount(f):
    ratio = np.maximum(f["amount_ratio"], 1e-6)
    base = clip01((np.log(ratio) - math.log(2.5)) / math.log(3.2))
    share = 0.25 * clip01((f["share_of_balance"] - 0.2) / 0.3)
    rnd = 0.1 * f["is_round"] * (ratio > 2)
    return clip01(base + share + rnd)


def severity_behavior(f):
    new = f["is_new_recipient"]
    s = (0.55 * new
         + 0.10 * new * (1 - f["is_p2m"])
         + 0.35 * clip01((f["tx_count_30m"] - 1) / 3)
         + 0.30 * clip01((f["value_24h_ratio"] - 3) / 7)
         + 0.25 * f["indirect_connection"] * new
         - 0.10 * clip01(f["prior_count"] / 5))
    return clip01(s)


def severity_context(f):
    s = (0.35 * f["is_night"]
         + 0.30 * clip01((f["hour_deviation"] - 3) / 6)
         + 0.40 * f["new_device"]
         + 0.35 * clip01((30 - f["account_age_days"]) / 30))
    return clip01(s)


def generate(n_rows: int = 24000, seed: int = SEED):
    """Return a dict of numpy columns (all synthetic)."""
    rng = np.random.default_rng(seed)
    n = n_rows

    # Sender profile
    avg = np.exp(rng.normal(math.log(1500), 0.7, n))
    std = avg * rng.uniform(0.3, 0.9, n)
    balance = np.clip(np.exp(rng.normal(math.log(60000), 1.0, n)), 2000, 2_000_000)
    age_kind = rng.random(n)
    age = np.where(age_kind < 0.85, rng.uniform(60, 2000, n),
                   np.where(age_kind < 0.95, rng.uniform(7, 60, n), rng.uniform(0, 7, n)))

    # Amount: mostly near the sender's average, some large spikes
    spike = rng.random(n) < 0.16
    ratio = np.where(spike, np.exp(rng.uniform(math.log(2), math.log(40), n)),
                     np.exp(rng.normal(0, 0.45, n)))
    amount = np.maximum(avg * ratio, 1.0)
    make_round = (amount >= 5000) & (rng.random(n) < np.where(spike, 0.45, 0.15))
    amount = np.where(make_round, np.round(amount / 1000) * 1000, np.round(amount))
    amount = np.maximum(amount, 1.0)
    is_round = ((amount >= 5000) & (np.mod(amount, 1000) == 0)).astype(float)

    f = {}
    f["log_amount"] = np.log1p(amount)
    f["amount_ratio"] = amount / avg
    f["amount_z"] = (amount - avg) / np.maximum.reduce([std, 0.25 * avg, np.full(n, 100.0)])
    f["share_of_balance"] = np.clip(amount / balance, 0, 5)
    f["is_round"] = is_round

    # Behaviour
    is_p2m = (rng.random(n) < 0.45).astype(float)
    p_new = np.where(is_p2m == 1, 0.30, 0.15)
    odd_behavior = rng.random(n) < 0.12
    is_new = ((rng.random(n) < p_new) | odd_behavior).astype(float)
    prior = np.where(is_new == 1, 0, np.minimum(rng.geometric(1 / 8, n), 50)).astype(float)
    burst = rng.random(n) < 0.08
    tx30 = np.where(burst, rng.integers(2, 9, n), rng.poisson(0.15, n)).astype(float)
    heavy = rng.random(n) < 0.08
    v24 = np.where(heavy, rng.uniform(3, 20, n), rng.gamma(0.6, 1.2, n))
    indirect = ((is_new == 1) & (is_p2m == 0) & (rng.random(n) < 0.18)).astype(float)
    f["is_new_recipient"] = is_new
    f["prior_count"] = prior
    f["tx_count_30m"] = tx30
    f["value_24h_ratio"] = v24
    f["indirect_connection"] = indirect
    f["is_p2m"] = is_p2m

    # Context
    night = (rng.random(n) < 0.08).astype(float)
    hour_dev = np.where(night == 1, rng.uniform(4, 11, n), np.minimum(np.abs(rng.normal(0, 2.2, n)), 12))
    new_device = (rng.random(n) < 0.08).astype(float)
    f["is_night"] = night
    f["hour_deviation"] = hour_dev
    f["new_device"] = new_device
    f["account_age_days"] = np.floor(age)

    # Round every feature once so the CSV and the training arrays are identical
    for k in ALL_FEATURES:
        f[k] = np.round(f[k], 4)

    # Non-learned signals
    chain = rng.random(n) < 0.12
    hops = np.where(rng.random(n) < 0.6, 2, 3)
    sim = rng.uniform(0.75, 1.0, n)
    graph = np.where(chain, np.array(HOP_FACTOR)[hops] * (0.6 + 0.4 * sim), 0.0)
    rk = rng.random(n)
    parts = (rng.random((n, 4)) < 0.45) * np.array(RECEIVER_PARTS)
    partial = np.minimum(parts.sum(axis=1), 1.0)
    receiver = np.where(rk < 0.03, 1.0, np.where(rk < 0.12, partial, 0.0))
    graph = np.round(graph, 4)
    receiver = np.round(receiver, 4)

    # Per-component anomaly labels: Bernoulli draws on hand-written severities
    s_a, s_b, s_c = severity_amount(f), severity_behavior(f), severity_context(f)
    lab_a = (rng.random(n) < s_a).astype(int)
    lab_b = (rng.random(n) < s_b).astype(int)
    lab_c = (rng.random(n) < s_c).astype(int)

    rating = (RATING["intercept"] + RATING["amount"] * s_a + RATING["behavior"] * s_b
              + RATING["context"] * s_c + RATING["graph"] * graph + RATING["receiver"] * receiver
              + rng.normal(0, RATING["noise"], n))
    rating = np.round(clip01(rating), 4)

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    offsets = np.sort(rng.uniform(0, 180 * 86400, n))
    stamps = [(start + timedelta(seconds=int(s))).strftime("%Y-%m-%dT%H:%M:%SZ") for s in offsets]

    data = {"tx_id": [f"syn{i:06d}" for i in range(n)], "timestamp": stamps}
    data.update(f)
    data["graph_score"] = graph
    data["receiver_score"] = receiver
    data["label_amount"] = lab_a
    data["label_behavior"] = lab_b
    data["label_context"] = lab_c
    data["analyst_rating"] = rating
    data["is_fraud"] = (rating >= FRAUD_RATING).astype(int)
    return data


def _fmt(v):
    if isinstance(v, str):
        return v
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    x = float(v)
    if x == int(x):
        return str(int(x))
    return f"{x:.4f}".rstrip("0").rstrip(".")


def write_csv(data, path):
    n = len(data["tx_id"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        for i in range(n):
            w.writerow([_fmt(data[c][i]) for c in COLUMNS])


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {"tx_id": [r["tx_id"] for r in rows], "timestamp": [r["timestamp"] for r in rows]}
    for c in COLUMNS[2:]:
        out[c] = np.array([float(r[c]) for r in rows])
    return out


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "data/synthetic_transactions.csv"
    write_csv(generate(), target)
    print(f"wrote synthetic data to {target}")
