"""Feature engine (including missing history) and transaction-graph traversal limits."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.ml.features import (
    COLD_START_AVG, FEATURE_COLUMNS, PastPayment, PaymentContext, ReceiverStats, circular_mean_hour, compute_features,
)
from backend.ml.graph_engine import GraphEdge, GraphSignals, TransactionGraph

T0 = datetime(2026, 3, 10, 8, 30, tzinfo=timezone.utc)  # 14:00 IST


def ctx(amount=500.0, at=T0, to="acct:rahul", device="d1", location="l1", ptype="P2P"):
    return PaymentContext(amount, at, to, ptype, device, location)


def history(n=10, amount=500.0, to="acct:rahul", start=T0, step=timedelta(days=1), device="d1", location="l1"):
    return [PastPayment(start - step * (i + 1), amount, to, device, location) for i in range(n)]


def feats(c=None, hist=(), receiver=None, graph=None, window=30):
    return compute_features(c or ctx(), list(hist), receiver or ReceiverStats(is_registered=True), graph or GraphSignals(),
                            window)


def test_every_feature_present_and_numeric():
    f = feats(hist=history())
    assert list(f) == FEATURE_COLUMNS
    assert all(isinstance(v, float) for v in f.values())


def test_missing_history_uses_cold_start_baseline():
    f = feats(c=ctx(amount=2000))
    assert f["history_missing"] == 1.0
    assert f["sender_history_count"] == 0.0
    assert f["sender_avg_amount"] == COLD_START_AVG
    assert f["amount_ratio_avg"] == 2.0
    assert f["is_new_recipient"] == 1.0
    assert f["hour_deviation"] == 0.0  # no baseline to compare against
    assert f["device_novelty"] == 0.0 and f["location_novelty"] == 0.0  # nothing known yet


def test_amount_and_familiarity_features():
    f = feats(c=ctx(amount=5000), hist=history(10, amount=500))
    assert f["history_missing"] == 0.0
    assert f["sender_avg_amount"] == 500 and f["sender_median_amount"] == 500
    assert f["amount_ratio_avg"] == pytest.approx(10.0)
    assert f["amount_zscore"] > 2
    assert f["is_new_recipient"] == 0.0 and f["prior_pair_count"] == 10.0


def test_velocity_windows():
    burst = [PastPayment(T0 - timedelta(minutes=m), 400, "acct:x") for m in (5, 10, 20, 45, 300)]
    f = feats(hist=history(5, start=T0 - timedelta(days=1)) + burst)
    assert f["tx_count_30m"] == 3.0
    assert f["tx_count_24h"] == 5.0
    assert f["velocity_ratio_24h"] > 3


def test_history_window_7_vs_30_days():
    hist = history(3, amount=300, step=timedelta(days=1)) + history(10, amount=3000, start=T0 - timedelta(days=10))
    f7, f30 = feats(hist=hist, window=7), feats(hist=hist, window=30)
    assert f7["sender_avg_amount"] == 300
    assert f30["sender_avg_amount"] > 2000


def test_future_and_old_events_ignored():
    future = [PastPayment(T0 + timedelta(minutes=1), 99999, "acct:rahul")]
    ancient = [PastPayment(T0 - timedelta(days=120), 99999, "acct:rahul")]
    f = feats(hist=history(5) + future + ancient)
    assert f["sender_avg_amount"] == 500 and f["prior_pair_count"] == 5.0


def test_unusual_time_uses_circular_mean():
    assert circular_mean_hour([23, 1]) == pytest.approx(0, abs=1e-6) or circular_mean_hour([23, 1]) == pytest.approx(24)
    night = T0.replace(hour=21, minute=30)  # 03:00 IST
    f = feats(c=ctx(at=night), hist=history(10, start=night - timedelta(hours=13)))
    assert f["unusual_hour"] == 1.0
    assert f["hour_deviation"] > 10


def test_device_and_location_novelty():
    f = feats(c=ctx(device="new", location="elsewhere"), hist=history(5))
    assert f["device_novelty"] == 1.0 and f["location_novelty"] == 1.0
    assert feats(hist=history(5))["device_novelty"] == 0.0


def test_receiver_summaries():
    r = ReceiverStats(is_registered=False, on_watchlist=True, account_age_days=None, distinct_senders_24h=4,
                      inflow_count_24h=6, inflow_value_24h=1000, outflow_value_24h=900)
    f = feats(receiver=r)
    assert f["receiver_on_watchlist"] == 1.0 and f["receiver_is_registered"] == 0.0
    assert f["receiver_account_age_days"] == -1.0
    assert f["receiver_outflow_ratio_24h"] == pytest.approx(0.9)


# ------------------------------------------------------------------ graph

def chain_graph(depth):
    g = TransactionGraph(depth)
    g.add_edge(GraphEdge("A", "B", 10000, T0 - timedelta(minutes=50)))
    g.add_edge(GraphEdge("B", "C", 9800, T0 - timedelta(minutes=30)))
    g.add_edge(GraphEdge("C", "D", 9700, T0 - timedelta(minutes=10)))
    return g


def test_k_hop_depth_limits():
    g = chain_graph(2)
    hops = g.k_hop_neighbourhood("A", depth=2)
    assert hops[1] == {"B"} and hops[2] == {"C"}
    assert "D" not in set().union(*hops.values())
    assert g.k_hop_neighbourhood("A", depth=3)[3] == {"D"}
    assert set(g.k_hop_neighbourhood("A", depth=9)) == {1, 2, 3}  # hard cap at 3


def test_pass_through_chain_respects_depth():
    s2 = chain_graph(2).upstream_chain("D", 9600, T0, 120, 0.25)
    assert s2.pass_through and s2.hop_count == 2 and len(s2.links) == 1
    s3 = chain_graph(3).upstream_chain("D", 9600, T0, 120, 0.25)
    assert s3.hop_count == 3 and [l.sender for l in s3.links] == ["B", "C"]
    assert 0.9 < s3.amount_similarity <= 1 and s3.time_gap_minutes == pytest.approx(10)
    assert chain_graph(1).upstream_chain("D", 9600, T0, 120, 0.25).hop_count == 0


def test_chain_needs_similar_amount_and_short_gap():
    g = chain_graph(2)
    assert g.upstream_chain("D", 3000, T0, 120, 0.25).hop_count == 0          # amounts too different
    assert g.upstream_chain("D", 9600, T0 + timedelta(hours=3), 120, 0.25).hop_count == 0  # gap too long
    assert g.upstream_chain("D", 9600, T0 - timedelta(minutes=20), 120, 0.25).hop_count == 0  # inbound is later


def test_cycles_terminate():
    g = TransactionGraph(3)
    for a, b, m in (("A", "B", 40), ("B", "C", 30), ("C", "A", 20), ("A", "B", 10)):
        g.add_edge(GraphEdge(a, b, 1000, T0 - timedelta(minutes=m)))
    s = g.upstream_chain("B", 1000, T0, 120, 0.25)
    assert s.hop_count <= 3
    assert len({l.sender for l in s.links}) == len(s.links)
    assert g.k_hop_neighbourhood("A", 3)[1] == {"B"}


def test_indirect_link_depth():
    g = chain_graph(2)
    assert g.indirect_link("A", "C") is True           # A -> B -> C
    assert g.indirect_link("A", "D") is False          # 3 hops, beyond default depth 2
    assert TransactionGraph.from_edges([GraphEdge("A", "B", 1, T0), GraphEdge("B", "C", 1, T0),
                                        GraphEdge("C", "D", 1, T0)], 3).indirect_link("A", "D") is True
    g.add_edge(GraphEdge("A", "C", 1, T0))
    assert g.indirect_link("A", "C") is False          # a direct payee is not "indirect"


def test_invalid_depth_rejected():
    with pytest.raises(ValueError):
        TransactionGraph(4)
