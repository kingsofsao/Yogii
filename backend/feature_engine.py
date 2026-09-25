from datetime import datetime, timedelta

import networkx as nx

from models import Transaction


# IMPORTANT:
# This order must remain consistent with the model training data.
FEATURE_COLUMNS = [
    "amount",
    "avg_amount",
    "amount_ratio",
    "max_amount",
    "max_ratio",
    "transactions_today",
    "amount_today",
    "transactions_1h",
    "recipient_count",
    "new_recipient",
    "unusual_hour",
    "high_velocity",
    "graph_degree",
    "recipient_seen",
    "hour",
]


def build_transaction_graph(db):
    graph = nx.DiGraph()

    transactions = db.query(Transaction).all()

    for tx in transactions:
        source = f"user:{tx.user_id}"
        target = f"upi:{tx.recipient_upi}"

        if graph.has_edge(source, target):
            graph[source][target]["weight"] += 1
        else:
            graph.add_edge(source, target, weight=1)

    return graph


def build_features(
    db,
    user,
    recipient_upi,
    amount,
    timestamp=None,
    device_id=None,
    location=None,
):
    if isinstance(timestamp, datetime):
        now = timestamp
    else:
        now = datetime.utcnow()

    user_id = user.id if hasattr(user, "id") else int(user)

    transactions = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )

    # Only successful historical transactions define normal behaviour.
    historical = [
        tx for tx in transactions
        if tx.status == "SUCCESS"
    ]

    amounts = [
        float(tx.amount)
        for tx in historical
    ]

    # -----------------------------
    # Behavioural analysis
    # -----------------------------

    if amounts:
        avg_amount = sum(amounts) / len(amounts)
        max_amount = max(amounts)
    else:
        avg_amount = 0.0
        max_amount = 0.0

    amount_ratio = (
        float(amount) / avg_amount
        if avg_amount > 0
        else 1.0
    )

    max_ratio = (
        float(amount) / max_amount
        if max_amount > 0
        else 1.0
    )

    # -----------------------------
    # Time-based behaviour
    # -----------------------------

    today_start = datetime(
        now.year,
        now.month,
        now.day,
    )

    one_hour_ago = now - timedelta(hours=1)

    transactions_today = sum(
        1
        for tx in historical
        if tx.timestamp and tx.timestamp >= today_start
    )

    amount_today = sum(
        float(tx.amount)
        for tx in historical
        if tx.timestamp and tx.timestamp >= today_start
    )

    transactions_1h = sum(
        1
        for tx in historical
        if tx.timestamp and tx.timestamp >= one_hour_ago
    )

    # -----------------------------
    # Recipient analysis
    # -----------------------------

    recipient_seen = any(
        tx.recipient_upi == recipient_upi
        for tx in historical
    )

    new_recipient = 0 if recipient_seen else 1

    recipient_count = len(
        set(
            tx.recipient_upi
            for tx in historical
        )
    )

    # -----------------------------
    # Context analysis
    # -----------------------------

    unusual_hour = (
        1
        if now.hour < 6 or now.hour >= 23
        else 0
    )

    high_velocity = (
        1
        if transactions_1h >= 5
        else 0
    )

    # -----------------------------
    # Transaction graph
    # -----------------------------

    graph = build_transaction_graph(db)

    user_node = f"user:{user_id}"

    graph_degree = (
        graph.out_degree(user_node)
        if graph.has_node(user_node)
        else 0
    )

    # -----------------------------
    # Final feature dictionary
    # -----------------------------

    features = {
        "amount": float(amount),
        "avg_amount": float(avg_amount),
        "amount_ratio": float(amount_ratio),
        "max_amount": float(max_amount),
        "max_ratio": float(max_ratio),
        "transactions_today": int(transactions_today),
        "amount_today": float(amount_today),
        "transactions_1h": int(transactions_1h),
        "recipient_count": int(recipient_count),
        "new_recipient": int(new_recipient),
        "unusual_hour": int(unusual_hour),
        "high_velocity": int(high_velocity),
        "graph_degree": int(graph_degree),
        "recipient_seen": int(recipient_seen),
        "hour": int(now.hour),
    }

    return features