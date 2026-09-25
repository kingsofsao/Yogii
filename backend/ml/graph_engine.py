from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple
import networkx as nx
from sqlalchemy.orm import Session
from backend.database.models import TransactionGraphEdge

class TransactionGraphEngine:
    """
    Transaction graph analysis engine built on NetworkX.
    Analyzes transaction networks, multi-hop intermediaries, and pass-through patterns.
    
    Terminology Policy:
    - Uses terms: 'transaction relationship', 'intermediary', 'multi-hop connection', 'possible pass-through pattern'.
    - NEVER describes relationships as 'friendship'.
    - A graph relationship by itself is NEVER treated as definitive proof of fraud.
    """

    def __init__(self, max_traversal_depth: int = 2):
        self.max_traversal_depth = min(max_traversal_depth, 3)  # Safe bounded depth (2 default, max 3)
        self.graph = nx.DiGraph()

    def load_from_db(self, db: Session, limit: int = 5000) -> None:
        """Loads recent transaction edges from database into the directed graph."""
        self.graph.clear()
        edges = (
            db.query(TransactionGraphEdge)
            .order_by(TransactionGraphEdge.timestamp.desc())
            .limit(limit)
            .all()
        )
        for e in edges:
            self.add_edge(e.sender_node, e.receiver_node, e.amount, e.timestamp, e.payment_id)

    def add_edge(self, sender: str, receiver: str, amount: float, timestamp: datetime, payment_id: int) -> None:
        """Adds a directed payment edge with attributes."""
        if not self.graph.has_edge(sender, receiver):
            self.graph.add_edge(
                sender,
                receiver,
                payments=[{
                    "payment_id": payment_id,
                    "amount": float(amount),
                    "timestamp": timestamp
                }],
                weight=1
            )
        else:
            self.graph[sender][receiver]["payments"].append({
                "payment_id": payment_id,
                "amount": float(amount),
                "timestamp": timestamp
            })
            self.graph[sender][receiver]["weight"] += 1

    def get_k_hop_neighborhood(self, source_node: str, max_depth: Optional[int] = None) -> Dict[int, Set[str]]:
        """
        Cycle-safe bounded breadth-first search up to max_depth (1, 2, or 3 hops).
        Returns a dict mapping hop_distance -> set of reachable nodes.
        """
        depth_limit = max_depth if max_depth is not None else self.max_traversal_depth
        depth_limit = min(depth_limit, 3)  # Hard bound to prevent runaway traversals

        if not self.graph.has_node(source_node):
            return {hop: set() for hop in range(1, depth_limit + 1)}

        visited: Set[str] = {source_node}
        queue: List[Tuple[str, int]] = [(source_node, 0)]
        hops_map: Dict[int, Set[str]] = {hop: set() for hop in range(1, depth_limit + 1)}

        while queue:
            current, dist = queue.pop(0)
            if dist >= depth_limit:
                continue

            for neighbor in self.graph.successors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    hops_map[dist + 1].add(neighbor)
                    queue.append((neighbor, dist + 1))

        return hops_map

    def detect_pass_through_pattern(
        self,
        sender_node: str,
        target_node: str,
        proposed_amount: float,
        time_window_hours: float = 4.0,
        amount_tolerance_pct: float = 0.25
    ) -> Dict[str, Any]:
        """
        Detects possible pass-through patterns where funds flow A -> B -> C within a short time gap
        with similar amounts (e.g. Visrojit receives from Yogesh and sends to Dinesh).
        
        Returns a structured summary.
        """
        result = {
            "possible_pass_through": False,
            "intermediary_node": None,
            "hop_count": 0,
            "amount_similarity": 0.0,
            "time_gap_minutes": None,
            "summary": "No pass-through pattern detected."
        }

        if not self.graph.has_node(target_node):
            return result

        # Check if target_node has recent outgoing transactions to a third node C
        now = datetime.now(timezone.utc)
        outgoing_edges = self.graph.out_edges(target_node, data=True)

        for _, downstream_node, edge_data in outgoing_edges:
            for payment in edge_data.get("payments", []):
                pmt_amt = payment["amount"]
                pmt_time = payment["timestamp"]
                if pmt_time.tzinfo is None:
                    pmt_time = pmt_time.replace(tzinfo=timezone.utc)

                time_diff = abs((now - pmt_time).total_seconds()) / 60.0  # minutes

                if time_diff <= (time_window_hours * 60):
                    # Check amount similarity
                    amt_diff_ratio = abs(pmt_amt - proposed_amount) / max(proposed_amount, 1.0)
                    if amt_diff_ratio <= amount_tolerance_pct:
                        result["possible_pass_through"] = True
                        result["intermediary_node"] = target_node
                        result["downstream_node"] = downstream_node
                        result["hop_count"] = 2
                        result["amount_similarity"] = round(1.0 - amt_diff_ratio, 3)
                        result["time_gap_minutes"] = round(time_diff, 1)
                        result["summary"] = (
                            "Multi-hop connection: recipient node recently transferred "
                            f"similar amount (within {int(amount_tolerance_pct*100)}%) to a third party."
                        )
                        return result

        return result

    def get_node_degree_stats(self, node: str) -> Dict[str, int]:
        """Returns in-degree and out-degree connectivity metrics."""
        if not self.graph.has_node(node):
            return {"in_degree": 0, "out_degree": 0, "total_degree": 0}
        in_deg = self.graph.in_degree(node)
        out_deg = self.graph.out_degree(node)
        return {
            "in_degree": in_deg,
            "out_degree": out_deg,
            "total_degree": in_deg + out_deg
        }
