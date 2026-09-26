"""Synthetic transaction stream for training the Yogii prototype model.

SYNTHETIC DATA ONLY. Every user, payee and payment here is generated from
hand-written rules. It is not real banking data, it does not describe real
fraud rates, and a model trained on it proves nothing about real-world
performance.

How it works: fictional users make everyday payments over 88 days. Scripted
fraud incidents (account takeover, push-payment scams, velocity drains and
mule pass-through chains) are injected and labelled 1. So are some benign
look-alikes, labelled 0: big legitimate purchases, late-night payers,
travellers, new phones and friends forwarding money for a shared bill. This
keeps any single signal (a new device, a graph link) from being proof on its own.
New customers join throughout the period, and a month of burn-in runs before
the first training row so established users have real histories.

Events are processed in time order, and each payment's features are computed
by backend.ml.features.compute_features from strictly earlier events. This is
the same function the live API uses.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.ml.features import FEATURE_COLUMNS, PastPayment, PaymentContext, ReceiverStats, compute_features
from backend.ml.graph_engine import GraphEdge, TransactionGraph

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
IST = timedelta(hours=5, minutes=30)


@dataclass
class SimUser:
    node: str
    device: str
    city: int
    hour_mean: float
    avg_amount: float
    rate: float
    created: datetime
    is_mule: bool = False
    favourites: List[str] = field(default_factory=list)
    extra_devices: List[str] = field(default_factory=list)


@dataclass
class Payee:
    node: str
    kind: str                 # merchant, contact, user, watchlist, unregistered
    registered: bool
    created: Optional[datetime]
    on_watchlist: bool = False


@dataclass(order=True)
class Event:
    at: datetime
    seq: int
    sender: str = field(compare=False)
    receiver: str = field(compare=False)
    amount: float = field(compare=False)
    device: str = field(compare=False)
    location: str = field(compare=False)
    label: int = field(compare=False)
    scenario: str = field(compare=False)


class Simulator:
    def __init__(self, seed: int = 42, n_users: int = 500, days: int = 88, graph_depth: int = 2,
                 window_days: int = 30, graph_window_minutes: int = 120, graph_tolerance: float = 0.25):
        self.rng = np.random.default_rng(seed)
        self.days = days
        # Burn-in: simulate a month before the first emitted row, so established users
        # have real histories. Rows from the burn-in are not used for training.
        self.warmup = 30
        self.total_days = self.warmup + days
        self.window_days = window_days
        self.graph_window = graph_window_minutes
        self.graph_tol = graph_tolerance
        self.graph = TransactionGraph(graph_depth)
        self.seq = 0
        self.queue: List[Event] = []
        self.users: Dict[str, SimUser] = {}
        self.payees: Dict[str, Payee] = {}
        self.history: Dict[str, List[PastPayment]] = defaultdict(list)
        self.inbound: Dict[str, Deque[Tuple[datetime, str, float]]] = defaultdict(deque)
        self.outbound: Dict[str, Deque[Tuple[datetime, float]]] = defaultdict(deque)
        self.rows: List[dict] = []
        self._fresh = 0
        self._build_population(n_users)

    # ------------------------------------------------------------------ population
    def _build_population(self, n_users: int) -> None:
        r = self.rng
        for j in range(90):
            self.payees[f"m{j}"] = Payee(f"m{j}", "merchant", True, START - timedelta(days=float(r.uniform(200, 2000))))
        for k in range(700):
            reg = r.random() < 0.75
            self.payees[f"c{k}"] = Payee(f"c{k}", "contact", reg, START - timedelta(days=float(r.uniform(100, 2000))) if reg else None)
        for k in range(14):
            self.payees[f"w{k}"] = Payee(f"w{k}", "watchlist", False, None, on_watchlist=True)
        n_mules = 18
        for i in range(n_users):
            mule = i < n_mules
            # Half the mules are new accounts; half are recruited established users with normal history.
            young_mule = mule and i < n_mules // 2
            late_owl = r.random() < 0.08
            if young_mule:
                created = START + timedelta(days=float(r.uniform(self.warmup - 20, self.total_days - 15)))
            elif r.random() < 0.3:
                # New customers keep joining throughout the period.
                created = START + timedelta(days=float(r.uniform(0, self.total_days - 3)))
            else:
                created = START - timedelta(days=float(r.uniform(30, 900)))
            u = SimUser(
                node=f"u{i}", device=f"dev-u{i}", city=int(r.integers(0, 8)),
                hour_mean=float((r.normal(23.5, 1.2) if late_owl else r.normal(14, 3)) % 24),
                avg_amount=float(np.exp(r.normal(math.log(900), 0.8))),
                rate=float(r.gamma(2.0, 0.5)) * (0.3 if young_mule else 1.0),
                created=created, is_mule=mule,
            )
            self.users[u.node] = u
            self.payees[u.node] = Payee(u.node, "user", True, created)
        user_nodes = [n for n, u in self.users.items() if not u.is_mule]
        for u in self.users.values():
            favs = list(r.choice(700, size=int(r.integers(5, 14)), replace=False))
            u.favourites = [f"c{k}" for k in favs]
            u.favourites += [f"m{j}" for j in r.choice(90, size=int(r.integers(4, 10)), replace=False)]
            u.favourites += [str(n) for n in r.choice(user_nodes, size=int(r.integers(0, 4)), replace=False) if n != u.node]

    def _fresh_payee(self, kind: str = "unregistered") -> str:
        self._fresh += 1
        node = f"x{self._fresh}"
        self.payees[node] = Payee(node, kind, False, None)
        return node

    def _confirmed(self, base: float, payee: str) -> int:
        """Fraud-shaped incidents are only sometimes confirmed fraud; the rest are
        genuine payments with the same shape (label 0). Watchlisted payees are
        almost always confirmed."""
        p = 0.97 if self.payees[payee].on_watchlist else base
        return int(self.rng.random() < p)

    def _push(self, at, sender, receiver, amount, device, location, label, scenario):
        self.seq += 1
        heapq.heappush(self.queue, Event(at, self.seq, sender, receiver, round(max(1.0, amount), 2),
                                         device, location, label, scenario))

    def _at(self, day: float, local_hour: float) -> datetime:
        return START + timedelta(days=int(day)) + timedelta(hours=local_hour) - IST

    # ------------------------------------------------------------------ schedules
    def _schedule_normal(self) -> None:
        r = self.rng
        for u in self.users.values():
            for day in range(self.total_days):
                if START + timedelta(days=day + 1) <= u.created:
                    continue
                for _ in range(r.poisson(u.rate)):
                    hour = float(r.normal(u.hour_mean, 2.3)) % 24
                    at = self._at(day, hour) + timedelta(seconds=float(r.uniform(0, 60)))
                    if at > u.created:
                        self._schedule_one_normal(u, at)

    def _schedule_one_normal(self, u: SimUser, at: datetime) -> None:
        r = self.rng
        big_purchase = r.random() < 0.02
        if big_purchase:
            payee = f"m{int(r.integers(0, 90))}"
            amount = u.avg_amount * float(r.uniform(3, 14))
            scenario = "benign_big_purchase"
        elif r.random() < 0.025:
            payee = self._fresh_payee()
            amount = u.avg_amount * float(r.uniform(1, 10))
            if r.random() < 0.5:
                amount = max(1000.0, round(amount / 1000) * 1000)
            scenario = "benign_new_unregistered_payee"
            u.favourites.append(payee)
        elif r.random() < 0.8 and u.favourites:
            payee = str(r.choice(u.favourites))
            amount = u.avg_amount * float(np.exp(r.normal(-0.2 if payee.startswith("m") else 0.0, 0.6)))
            scenario = "normal"
        else:
            roll = r.random()
            if roll < 0.55:
                payee = f"m{int(r.integers(0, 90))}"
            elif roll < 0.9:
                payee = f"c{int(r.integers(0, 700))}"
            else:
                payee = str(r.choice([n for n in self.users if n != u.node]))
            amount = u.avg_amount * float(np.exp(r.normal(0.1, 0.7)))
            scenario = "normal_new_payee"
            if r.random() < 0.4:
                u.favourites.append(payee)
        device = u.device
        if r.random() < 0.02:
            device = f"dev-{u.node}-new{len(u.extra_devices)}"
            u.extra_devices.append(device)
            scenario = "benign_new_device" if scenario == "normal" else scenario
        location = f"city{u.city}"
        if r.random() < 0.05:
            location = f"city{int(r.integers(0, 12))}"
        if r.random() < 0.3:
            amount = round(amount / 100) * 100 or amount
        self._push(at, u.node, payee, amount, device, location, 0, scenario)

    def _schedule_fraud(self) -> None:
        r = self.rng
        victims = [u for u in self.users.values() if not u.is_mule]
        n_incidents = int(len(victims) * 1.1)
        mules = [u.node for u in self.users.values() if u.is_mule]
        for _ in range(n_incidents):
            v = victims[int(r.integers(0, len(victims)))]
            earliest = max(self.warmup - 5.0, (v.created - START).total_seconds() / 86400 + 0.5)
            if earliest >= self.total_days - 1:
                continue
            day = float(r.uniform(earliest, self.total_days - 1))
            kind = r.choice(["ato", "scam", "velocity"], p=[0.38, 0.44, 0.18])
            if kind == "ato":
                hour = float(r.uniform(0, 5)) if r.random() < 0.45 else float(r.uniform(0, 24))
                at = self._at(day, hour)
                device = f"attacker-{self.seq}"
                location = f"city{int(r.integers(20, 40))}" if r.random() < 0.85 else f"city{v.city}"
                for k in range(int(r.integers(1, 4))):
                    payee = self._pick_fraud_payee(mules, p_mule=0.5, p_watch=0.3)
                    amount = v.avg_amount * float(r.uniform(2, 15))
                    label = self._confirmed(0.9 if location != f"city{v.city}" else 0.75, payee)
                    self._push(at + timedelta(minutes=float(k * r.uniform(2, 9))), v.node, payee, amount,
                               device, location, label, "fraud_account_takeover" if label else "lookalike_new_device")
            elif kind == "scam":
                hour = float(r.normal(v.hour_mean, 3)) % 24
                at = self._at(day, hour)
                fake_shop = r.random() < 0.2
                for k in range(int(r.integers(1, 3))):
                    if fake_shop:
                        payee = self._fresh_payee("unregistered_merchant")
                    else:
                        payee = self._pick_fraud_payee(mules, p_mule=0.3, p_watch=0.25)
                    amount = v.avg_amount * float(r.uniform(1.5, 20))
                    if r.random() < 0.5:
                        amount = max(1000.0, round(amount / 1000) * 1000)
                    label = self._confirmed(0.55 if fake_shop else 0.68, payee)
                    self._push(at + timedelta(minutes=float(k * r.uniform(5, 40))), v.node, payee, amount,
                               v.device, f"city{v.city}", label, "fraud_push_scam" if label else "lookalike_large_new_payee")
            else:
                at = self._at(day, float(r.uniform(0, 24)))
                device = v.device if r.random() < 0.5 else f"attacker-{self.seq}"
                for k in range(int(r.integers(4, 9))):
                    payee = self._pick_fraud_payee(mules, p_mule=0.4, p_watch=0.2)
                    amount = v.avg_amount * float(r.uniform(0.8, 3))
                    label = self._confirmed(0.72, payee)
                    self._push(at + timedelta(minutes=float(k * r.uniform(1, 4))), v.node, payee, amount,
                               device, f"city{v.city}", label, "fraud_velocity_drain" if label else "lookalike_burst")

    def _pick_fraud_payee(self, mules: List[str], p_mule: float, p_watch: float) -> str:
        roll = self.rng.random()
        if roll < p_mule:
            return str(self.rng.choice(mules))
        if roll < p_mule + p_watch:
            return f"w{int(self.rng.integers(0, 14))}"
        return self._fresh_payee()

    # ------------------------------------------------------------------ processing
    def _receiver_stats(self, receiver: str, sender: str, at: datetime) -> ReceiverStats:
        p = self.payees[receiver]
        cutoff = at - timedelta(hours=24)
        inbound = self.inbound[receiver]
        while inbound and inbound[0][0] < cutoff:
            inbound.popleft()
        outbound = self.outbound[receiver]
        while outbound and outbound[0][0] < cutoff:
            outbound.popleft()
        return ReceiverStats(
            is_registered=p.registered,
            on_watchlist=p.on_watchlist,
            account_age_days=((at - p.created).total_seconds() / 86400) if p.created else None,
            distinct_senders_24h=len({s for _, s, _ in inbound if s != sender}),
            inflow_count_24h=len(inbound),
            inflow_value_24h=sum(a for _, _, a in inbound),
            outflow_value_24h=sum(a for _, a in outbound) if p.kind == "user" else 0.0,
        )

    def _process(self, e: Event) -> None:
        payee = self.payees[e.receiver]
        emit = e.at >= START + timedelta(days=self.warmup)
        ptype = "P2M" if payee.kind in ("merchant", "unregistered_merchant") else "P2P"
        ctx = PaymentContext(e.amount, e.at, e.receiver, ptype, e.device, e.location)
        graph = self.graph.signals_for(e.sender, e.receiver, e.amount, e.at, self.graph_window, self.graph_tol)
        feats = compute_features(ctx, self.history[e.sender], self._receiver_stats(e.receiver, e.sender, e.at),
                                 graph, self.window_days)
        feats.update({"label": e.label, "scenario": e.scenario, "timestamp": e.at, "sender": e.sender})
        if emit:
            self.rows.append(feats)

        # Record the payment (all simulated payments complete in the training stream).
        hist = self.history[e.sender]
        hist.append(PastPayment(e.at, e.amount, e.receiver, e.device, e.location))
        if len(hist) > 400:
            del hist[:100]
        self.graph.add_edge(GraphEdge(e.sender, e.receiver, e.amount, e.at))
        self.inbound[e.receiver].append((e.at, e.sender, e.amount))
        self.outbound[e.sender].append((e.at, e.amount))
        self._maybe_forward(e)

    def _maybe_forward(self, e: Event) -> None:
        r = self.rng
        receiver = self.users.get(e.receiver)
        if receiver is None:
            return
        if receiver.is_mule and (e.label == 1 or e.scenario.startswith("lookalike")):
            # Mule pass-through: forward most of it quickly (fraud).
            mules = [u for u in self.users if self.users[u].is_mule and u != receiver.node]
            if r.random() < 0.3:
                # Cash-out through an established account (for example a compromised one).
                # Often indistinguishable from a genuine transfer, so fewer are confirmed.
                nxt = str(r.choice([u for u in self.users if not self.users[u].is_mule]))
                label = self._confirmed(0.6, nxt)
            else:
                nxt = self._pick_fraud_payee(mules, p_mule=0.3, p_watch=0.45)
                label = self._confirmed(0.85, nxt)
            self._push(e.at + timedelta(minutes=float(r.uniform(4, 45))), receiver.node, nxt,
                       e.amount * float(r.uniform(0.88, 0.995)), receiver.device, f"city{receiver.city}",
                       label, "fraud_mule_pass_through" if label else "lookalike_forward")
        elif not receiver.is_mule and e.scenario.startswith("normal") and r.random() < 0.12:
            # Benign look-alike: passing on money for a shared bill or group purchase.
            # Mostly to people they already pay; occasionally someone new.
            if receiver.favourites and r.random() < 0.9:
                nxt = str(r.choice(receiver.favourites))
            else:
                nxt = f"c{int(r.integers(0, 700))}"
            self._push(e.at + timedelta(minutes=float(r.uniform(8, 100))), receiver.node, nxt,
                       e.amount * float(r.uniform(0.85, 1.0)), receiver.device, f"city{receiver.city}",
                       0, "benign_forward")

    def run(self) -> pd.DataFrame:
        self._schedule_normal()
        self._schedule_fraud()
        end = START + timedelta(days=self.total_days)
        while self.queue:
            e = heapq.heappop(self.queue)
            if e.at >= end:
                continue
            self._process(e)
        df = pd.DataFrame(self.rows)
        # Label noise: a few frauds go unreported, a few normal payments are mislabelled.
        noise = self.rng.random(len(df))
        flip_fraud = (df["label"] == 1) & (noise < 0.02)
        flip_normal = (df["label"] == 0) & (noise < 0.002)
        df.loc[flip_fraud, "label"] = 0
        df.loc[flip_normal, "label"] = 1
        return df.sort_values(["timestamp"]).reset_index(drop=True)


def generate_synthetic_dataset(seed: int = 42, n_users: int = 500, days: int = 88, graph_depth: int = 2,
                               window_days: int = 30) -> pd.DataFrame:
    """Return a SYNTHETIC, time-ordered dataset with FEATURE_COLUMNS, `label`, `scenario`, `timestamp`."""
    df = Simulator(seed=seed, n_users=n_users, days=days, graph_depth=graph_depth, window_days=window_days).run()
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(f"Synthetic generator did not produce features: {missing}")
    return df
