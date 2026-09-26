"""Score the Yogii demo scenarios in Python, with the same maths as src/app.js.

    python ml/check_scenarios.py

Loads models/yogii_risk_model.json, rebuilds the fictional demo accounts and
their history, replays each scenario and prints one line per check. Exits with
status 1 if any scenario lands in the wrong band. This mirrors the browser
engine so the committed model can be checked without a browser; the seed data
below must stay identical to SEED_PAYMENTS in src/app.js (tests/engine.test.js
checks the same scenarios on the JavaScript side).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000

SEED_USERS = [
    ("u_yogesh", "yogesh@yogii", 400),
    ("u_visrojit", "visrojit@yogii", 250),
    ("u_dinesh", "dinesh@yogii", 180),
]
DIRECTORY = {
    "rahul@upi": {"type": "contact", "registered": True, "age": 900},
    "freshmarket@merchant": {"type": "merchant", "registered": True, "age": 1200},
    "campuscafe@merchant": {"type": "merchant", "registered": True, "age": 800},
    "techgadgets@merchant": {"type": "merchant", "registered": True, "age": 600},
    "crypto_drain@unknown": {"type": "unknown", "registered": False, "age": 2, "watchlist": True},
}
SEED_PAYMENTS = [
    ("yogesh@yogii", "rahul@upi", 800, 2, 11), ("yogesh@yogii", "rahul@upi", 1200, 5, 19),
    ("yogesh@yogii", "rahul@upi", 1500, 9, 13), ("yogesh@yogii", "rahul@upi", 900, 14, 18),
    ("yogesh@yogii", "rahul@upi", 2000, 20, 12), ("yogesh@yogii", "rahul@upi", 1100, 26, 16),
    ("yogesh@yogii", "freshmarket@merchant", 1450, 3, 17), ("yogesh@yogii", "freshmarket@merchant", 2300, 8, 10),
    ("yogesh@yogii", "freshmarket@merchant", 1750, 16, 18), ("yogesh@yogii", "freshmarket@merchant", 1600, 23, 11),
    ("yogesh@yogii", "campuscafe@merchant", 250, 4, 13), ("yogesh@yogii", "campuscafe@merchant", 400, 12, 14),
    ("yogesh@yogii", "campuscafe@merchant", 320, 18, 15),
    ("visrojit@yogii", "freshmarket@merchant", 3200, 3, 12), ("visrojit@yogii", "freshmarket@merchant", 2600, 10, 18),
    ("visrojit@yogii", "campuscafe@merchant", 900, 6, 15), ("visrojit@yogii", "techgadgets@merchant", 4500, 15, 16),
    ("visrojit@yogii", "freshmarket@merchant", 2800, 21, 11), ("visrojit@yogii", "campuscafe@merchant", 1600, 25, 14),
    ("dinesh@yogii", "freshmarket@merchant", 1500, 2, 10), ("dinesh@yogii", "campuscafe@merchant", 600, 5, 13),
    ("dinesh@yogii", "freshmarket@merchant", 2100, 11, 17), ("dinesh@yogii", "techgadgets@merchant", 2800, 17, 15),
    ("dinesh@yogii", "campuscafe@merchant", 500, 22, 12), ("dinesh@yogii", "freshmarket@merchant", 1500, 27, 19),
]
START_BALANCE = 300_000


def local_hour(ms):
    t = time.localtime(ms / 1000)
    return t.tm_hour + t.tm_min / 60


def start_of_local_day(ms):
    d = datetime.fromtimestamp(ms / 1000).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


class World:
    def __init__(self, model, now):
        self.m = model
        self.now = now
        self.users = {upi: {"upi": upi, "created": now - age * DAY, "balance": START_BALANCE}
                      for _, upi, age in SEED_USERS}
        self.payments = []
        day0 = start_of_local_day(now)
        for i, (f, t, a, days, hour) in enumerate(SEED_PAYMENTS):
            self.payments.append({"id": f"seed{i}", "from": f, "to": t, "amount": a,
                                  "at": day0 - days * DAY + hour * HOUR, "status": "COMPLETED"})

    # -- recipients --------------------------------------------------------
    def recipient(self, upi):
        if upi in self.users:
            return {"upi": upi, "type": "user", "registered": True, "created": self.users[upi]["created"], "watchlist": False}
        d = DIRECTORY.get(upi)
        if d:
            return {"upi": upi, "type": d["type"], "registered": d["registered"],
                    "created": self.now - d["age"] * DAY, "watchlist": d.get("watchlist", False)}
        return {"upi": upi, "type": "unregistered", "registered": False, "created": None, "watchlist": False}

    # -- engine (mirror of src/app.js) --------------------------------------
    def features(self, sender, r, amount, at, controls):
        hist = [p for p in self.payments if p["from"] == sender and p["status"] in ("COMPLETED", "PENDING") and p["at"] <= at]
        last30 = [p for p in hist if at - p["at"] <= 30 * DAY]
        avg, std = 2000.0, 1000.0
        if len(last30) >= 3:
            avg = sum(p["amount"] for p in last30) / len(last30)
            std = math.sqrt(sum((p["amount"] - avg) ** 2 for p in last30) / len(last30))
        prior = sum(1 for p in hist if p["to"] == r["upi"])
        is_new = 1 if prior == 0 else 0
        c30 = sum(1 for p in hist if at - p["at"] <= 30 * MIN)
        v24 = sum(p["amount"] for p in hist if at - p["at"] <= DAY)
        path = self.indirect_path(sender, r["upi"], at) if is_new else None
        hour = 2 if controls.get("night") else local_hour(at)
        hours = [local_hour(p["at"]) for p in hist if at - p["at"] <= 90 * DAY]
        dev = 0.0
        if len(hours) >= 3:
            s = sum(math.sin(h / 24 * 2 * math.pi) for h in hours)
            c = sum(math.cos(h / 24 * 2 * math.pi) for h in hours)
            ang = math.atan2(s, c)
            if ang < 0:
                ang += 2 * math.pi
            mean = ang / (2 * math.pi) * 24
            d = abs(hour - mean) % 24
            dev = min(d, 24 - d)
        bal = self.users[sender]["balance"]
        f = {
            "log_amount": math.log(1 + amount),
            "amount_ratio": amount / avg,
            "amount_z": (amount - avg) / max(std, 0.25 * avg, 100),
            "share_of_balance": min(5, max(0, amount / max(bal, 1))),
            "is_round": 1 if amount >= 5000 and amount % 1000 == 0 else 0,
            "is_new_recipient": is_new,
            "prior_count": min(prior, 50),
            "tx_count_30m": c30,
            "value_24h_ratio": v24 / max(avg, 100),
            "indirect_connection": 1 if path else 0,
            "is_p2m": 1 if r["type"] == "merchant" else 0,
            "is_night": 1 if hour < 5 else 0,
            "hour_deviation": dev,
            "new_device": 1 if controls.get("newDevice") else 0,
            "account_age_days": min(3650, max(0, (at - self.users[sender]["created"]) // DAY)),
        }
        return f, path

    def component(self, name, f):
        comp = self.m["components"][name]
        x = [f[k] for k in self.m["features"][name]]
        b = comp["base_score"]
        margin = math.log(b / (1 - b))
        for nodes in comp["trees"]:
            k = 0
            while "v" not in nodes[k]:
                nd = nodes[k]
                k = nd["l"] if np.float32(x[nd["f"]]) < nd["t"] else nd["r"]
            margin += nodes[k]["v"]
        return 1 / (1 + math.exp(-margin))

    def chain(self, sender, amount, at):
        g = self.m["graph"]
        links, visited = [], {sender}
        node, out_amt, out_at = sender, amount, at
        while len(links) < g["max_hops"] - 1:
            best, best_sim = None, -1
            for p in self.payments:
                if p["status"] != "COMPLETED" or p["to"] != node or p["from"] in visited:
                    continue
                if p["at"] > out_at or out_at - p["at"] > g["window_minutes"] * MIN:
                    continue
                if abs(p["amount"] - out_amt) > g["amount_tolerance"] * out_amt:
                    continue
                sim = 1 - abs(p["amount"] - out_amt) / max(p["amount"], out_amt)
                if sim > best_sim or (sim == best_sim and p["at"] > best["at"]):
                    best, best_sim = p, sim
            if not best:
                break
            links.append(best_sim)
            visited.add(best["from"])
            node, out_amt, out_at = best["from"], best["amount"], best["at"]
        hops = min(g["max_hops"], len(links) + 1) if links else 0
        avg = sum(links) / len(links) if links else 0
        return hops, (g["hop_factor"][hops] * (0.6 + 0.4 * avg) if hops else 0.0)

    def indirect_path(self, src, dst, at):
        g = self.m["graph"]
        adj = {}
        for p in self.payments:
            if p["status"] == "COMPLETED" and p["at"] <= at and at - p["at"] <= g["indirect_days"] * DAY:
                adj.setdefault(p["from"], set()).add(p["to"])
        parent = {src: None}
        frontier = [src]
        for depth in range(1, g["max_hops"] + 1):
            nxt = []
            for u in frontier:
                for v in sorted(adj.get(u, ())):
                    if v in parent:
                        continue
                    parent[v] = u
                    if v == dst:
                        if depth < 2:
                            return None
                        path = [v]
                        while parent[path[0]] is not None:
                            path.insert(0, parent[path[0]])
                        return path
                    nxt.append(v)
            frontier = nxt
            if not frontier:
                break
        return None

    def receiver(self, r, sender, at):
        c = self.m["receiver"]
        if r["watchlist"]:
            return c["watchlist"]
        s = 0.0
        if not r["registered"]:
            s += c["unregistered"]
        if r["registered"] and r["created"] is not None and at - r["created"] < c["new_account_days"] * DAY:
            s += c["new_account"]
        payers, inflow, outflow = set(), 0.0, 0.0
        for p in self.payments:
            if p["status"] != "COMPLETED" or p["at"] > at or at - p["at"] > DAY:
                continue
            if p["to"] == r["upi"]:
                inflow += p["amount"]
                if p["from"] != sender:
                    payers.add(p["from"])
            if p["from"] == r["upi"]:
                outflow += p["amount"]
        if len(payers) >= c["many_payers_count"]:
            s += c["many_payers"]
        if r["type"] == "user" and inflow > 0 and outflow >= c["pass_through_ratio"] * inflow:
            s += c["pass_through"]
        return min(1.0, s)

    def assess(self, sender, to, amount, controls=None, at=None):
        at = self.now if at is None else at
        r = self.recipient(to)
        f, path = self.features(sender, r, amount, at, controls or {})
        p = [self.component(c, f) for c in ("amount", "behavior", "context")]
        hops, graph = self.chain(sender, amount, at)
        rec = self.receiver(r, sender, at)
        st = self.m["stacker"]
        raw = st["intercept"] + sum(w * x for w, x in zip(st["weights"], p + [graph, rec]))
        score = int(math.floor(min(1, max(0, raw)) * 100 + 0.5))
        band = "VERY_HIGH" if score >= 85 else "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW"
        return {"score": score, "band": band, "hops": hops, "receiver": rec, "path": path, "f": f, "p": p}

    def complete(self, sender, to, amount, at):
        self.payments.append({"id": f"p{len(self.payments)}", "from": sender, "to": to, "amount": amount,
                              "at": at, "status": "COMPLETED"})
        self.users[sender]["balance"] -= amount
        if to in self.users:
            self.users[to]["balance"] += amount


def main():
    path = os.path.join(ROOT, "models", "yogii_risk_model.json")
    if not os.path.exists(path):
        print(f"FAIL  model file missing: {path}. Run: python ml/train.py")
        return 1
    with open(path, encoding="utf-8") as fh:
        model = json.load(fh)
    now = int(datetime(2026, 9, 26, 14, 0, 0).timestamp() * 1000)
    failures = 0

    def check(label, ok, detail):
        nonlocal failures
        print(f"{'OK  ' if ok else 'FAIL'}  {label:<58} {detail}")
        failures += 0 if ok else 1

    w = World(model, now)
    a = w.assess("yogesh@yogii", "rahul@upi", 500)
    check("Yogesh -> rahul@upi 500 is LOW", a["band"] == "LOW", f"score {a['score']} {a['band']}")

    w = World(model, now)
    a = w.assess("yogesh@yogii", "techgadgets@merchant", 24500)
    reasons_ok = a["f"]["amount_ratio"] >= 2.5 and a["f"]["is_new_recipient"] == 1
    check("Yogesh -> techgadgets 24,500 is HIGH (amount + new recipient)", a["band"] == "HIGH" and reasons_ok,
          f"score {a['score']} {a['band']}")

    w = World(model, now)
    a = w.assess("yogesh@yogii", "crypto_drain@unknown", 1000)
    check("Yogesh -> crypto_drain@unknown is VERY_HIGH, receiver High", a["band"] == "VERY_HIGH" and a["receiver"] >= 0.6,
          f"score {a['score']} receiver {a['receiver']}")
    a100 = w.assess("yogesh@yogii", "crypto_drain@unknown", 100)
    check("crypto_drain@unknown limit is 0 (Rs 100 already blocked)", a100["score"] >= 85, f"score at Rs 100: {a100['score']}")

    w = World(model, now)
    t = now
    a = w.assess("yogesh@yogii", "visrojit@yogii", 10000, at=t)
    check("Yogesh -> visrojit 10,000 is not blocked", a["band"] != "VERY_HIGH", f"score {a['score']} {a['band']}")
    w.complete("yogesh@yogii", "visrojit@yogii", 10000, t)
    t += 10 * MIN
    a = w.assess("visrojit@yogii", "dinesh@yogii", 9800, at=t)
    check("Visrojit -> dinesh 9,800: 2-hop chain, HIGH, not blocked", a["hops"] == 2 and a["band"] == "HIGH",
          f"score {a['score']} {a['band']} hops {a['hops']}")
    w.complete("visrojit@yogii", "dinesh@yogii", 9800, t)
    t += 10 * MIN
    a = w.assess("dinesh@yogii", "rahul@upi", 9500, at=t)
    check("Dinesh -> rahul 9,500: 3-hop chain, VERY_HIGH", a["hops"] == 3 and a["band"] == "VERY_HIGH",
          f"score {a['score']} {a['band']} hops {a['hops']}")
    t += 10 * MIN
    a = w.assess("yogesh@yogii", "dinesh@yogii", 2000, at=t)
    want = ["yogesh@yogii", "visrojit@yogii", "dinesh@yogii"]
    check("Yogesh -> dinesh: indirect path yogesh -> visrojit -> dinesh", a["path"] == want,
          f"path {' -> '.join(a['path'] or ['none'])} ({a['band']})")

    w = World(model, now)
    a = w.assess("yogesh@yogii", "rahul@upi", 500, controls={"night": True, "newDevice": True})
    check("Demo controls raise context risk but stay below blocking", a["p"][2] > 0.5 and a["band"] != "VERY_HIGH",
          f"p_context {a['p'][2]:.2f} score {a['score']}")

    print()
    if failures:
        print(f"{failures} scenario check(s) FAILED. Adjust synthetic data or rating weights and retrain; never hard-code a score.")
        return 1
    print("All scenario checks OK (synthetic model, prototype thresholds).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
