from datetime import datetime, timezone, timedelta
from backend.ml.graph_engine import TransactionGraphEngine

def test_graph_k_hop_traversal_and_depth_limits():
    engine = TransactionGraphEngine(max_traversal_depth=2)
    t0 = datetime.now(timezone.utc)

    # A -> B -> C -> D
    engine.add_edge("user:A", "user:B", 1000.0, t0, 1)
    engine.add_edge("user:B", "user:C", 1000.0, t0, 2)
    engine.add_edge("user:C", "user:D", 1000.0, t0, 3)

    hops = engine.get_k_hop_neighborhood("user:A", max_depth=2)
    assert "user:B" in hops[1]
    assert "user:C" in hops[2]
    # At depth 2, user:D must not be included
    assert "user:D" not in hops.get(2, set())

    # Depth 3 traversal
    hops3 = engine.get_k_hop_neighborhood("user:A", max_depth=3)
    assert "user:D" in hops3[3]

def test_graph_cycle_safety():
    engine = TransactionGraphEngine(max_traversal_depth=3)
    t0 = datetime.now(timezone.utc)

    # Create cycle: A -> B -> C -> A
    engine.add_edge("user:A", "user:B", 500.0, t0, 1)
    engine.add_edge("user:B", "user:C", 500.0, t0, 2)
    engine.add_edge("user:C", "user:A", 500.0, t0, 3)

    # Must complete safely without infinite loop
    hops = engine.get_k_hop_neighborhood("user:A", max_depth=3)
    assert "user:B" in hops[1]
    assert "user:C" in hops[2]
    # 'user:A' was the root visited, so not re-added in successors
    assert "user:A" not in hops[3]

def test_pass_through_detection():
    engine = TransactionGraphEngine()
    now = datetime.now(timezone.utc)

    # Target node B sent ₹10,000 to C 30 minutes ago
    engine.add_edge("user:B", "user:C", 10000.0, now - timedelta(minutes=30), 1)

    # Check proposed payment from A to B for ₹9,800 (within 2% amount difference)
    result = engine.detect_pass_through_pattern(
        sender_node="user:A",
        target_node="user:B",
        proposed_amount=9800.0,
        time_window_hours=2.0,
        amount_tolerance_pct=0.10
    )

    assert result["possible_pass_through"] is True
    assert result["hop_count"] == 2
    assert result["intermediary_node"] == "user:B"
    assert result["amount_similarity"] >= 0.90
    assert result["time_gap_minutes"] <= 60.0

def test_graph_relationship_alone_is_not_treated_as_fraud():
    engine = TransactionGraphEngine()
    now = datetime.now(timezone.utc)

    # Routine 1-hop edge
    engine.add_edge("user:1", "upi:merchant@upi", 200.0, now, 1)
    stats = engine.get_node_degree_stats("user:1")
    assert stats["out_degree"] == 1
    # Terminology invariant: graph relationships are network signals, not proof of guilt
