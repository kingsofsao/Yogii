"""Transaction graph signals built on NetworkX.

Vocabulary: this module talks about transaction graphs, intermediaries,
multi-hop links and possible pass-through patterns. A graph link is a signal
for the model, never proof of fraud on its own: ordinary life (splitting a
bill, repaying someone) produces the same shapes.

Nodes are keyed hashes of UPI IDs ("acct:<hash>"), so the graph holds no
plaintext identifiers. Edges are completed simulated payments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Set

import networkx as nx

MAX_SUPPORTED_DEPTH = 3


@dataclass(frozen=True)
class GraphEdge:
    sender: str
    receiver: str
    amount: float
    at: datetime
    payment_id: int = 0


@dataclass
class ChainLink:
    """One upstream transfer that fed the payment being assessed."""
    sender: str
    receiver: str
    amount: float
    at: datetime
    amount_similarity: float
    gap_minutes: float


@dataclass
class GraphSignals:
    hop_count: int = 0                 # transfers in the chain including this one; 0 = no chain
    amount_similarity: float = 0.0     # mean similarity of linked transfers (0-1)
    time_gap_minutes: Optional[float] = None  # gap between the most recent inbound link and this payment
    pass_through: bool = False
    indirect_link: bool = False        # sender reaches recipient through an intermediary
    links: List[ChainLink] = field(default_factory=list)


class TransactionGraph:
    """A directed multigraph of payments with bounded, cycle-safe traversals."""

    def __init__(self, max_depth: int = 2):
        if max_depth not in (1, 2, 3):
            raise ValueError("Graph depth must be 1, 2 or 3.")
        self.max_depth = max_depth
        self.g = nx.MultiDiGraph()

    @classmethod
    def from_edges(cls, edges: Iterable[GraphEdge], max_depth: int = 2) -> "TransactionGraph":
        tg = cls(max_depth)
        for e in edges:
            tg.add_edge(e)
        return tg

    def add_edge(self, e: GraphEdge) -> None:
        self.g.add_edge(e.sender, e.receiver, amount=float(e.amount), at=e.at, payment_id=e.payment_id)

    def __len__(self) -> int:
        return self.g.number_of_edges()

    # ------------------------------------------------------------------ neighbourhoods
    def k_hop_neighbourhood(self, source: str, depth: Optional[int] = None) -> dict[int, Set[str]]:
        """Nodes first reached at each hop distance from `source` (depth capped at 3)."""
        limit = min(depth or self.max_depth, MAX_SUPPORTED_DEPTH)
        out: dict[int, Set[str]] = {h: set() for h in range(1, limit + 1)}
        if source not in self.g:
            return out
        for node, dist in nx.single_source_shortest_path_length(self.g, source, cutoff=limit).items():
            if dist >= 1:
                out[dist].add(node)
        return out

    def indirect_link(self, sender: str, recipient: str, depth: Optional[int] = None) -> bool:
        """True when sender reaches recipient in 2..depth hops but has never paid them directly."""
        limit = min(depth or self.max_depth, MAX_SUPPORTED_DEPTH)
        if limit < 2 or sender not in self.g or recipient not in self.g:
            return False
        if self.g.has_edge(sender, recipient):
            return False
        # Meet in the middle: forward from the sender, backward from the recipient.
        forward = {sender}
        frontier = {sender}
        for _ in range((limit + 1) // 2):
            frontier = {n for f in frontier for n in self.g.successors(f)} - forward
            forward |= frontier
        backward = {recipient}
        frontier = {recipient}
        for _ in range(limit // 2):
            frontier = {n for f in frontier for n in self.g.predecessors(f)} - backward
            backward |= frontier
        return bool((forward - {sender}) & backward)

    # ------------------------------------------------------------------ pass-through chains
    def upstream_chain(self, sender: str, amount: float, at: datetime, window_minutes: int,
                       amount_tolerance: float, depth: Optional[int] = None) -> GraphSignals:
        """Follow inbound transfers upstream from the sender.

        A link counts when money reached the node within `window_minutes` before
        it paid onwards, and the amounts differ by at most `amount_tolerance`.
        `depth` is the maximum number of transfers in the chain, including the
        payment being assessed (2 = one upstream link). Visited nodes are never
        revisited, so cycles terminate.
        """
        limit = min(depth or self.max_depth, MAX_SUPPORTED_DEPTH)
        signals = GraphSignals()
        if limit < 2:
            return signals
        window = timedelta(minutes=window_minutes)
        visited = {sender}
        node, out_amount, out_at = sender, float(amount), at
        links: List[ChainLink] = []
        while len(links) < limit - 1 and node in self.g:
            best = None
            for src, _, data in self.g.in_edges(node, data=True):
                if src in visited:
                    continue
                t = data["at"]
                if t > out_at or out_at - t > window:
                    continue
                a = data["amount"]
                if abs(a - out_amount) > amount_tolerance * out_amount:
                    continue
                sim = 1.0 - abs(a - out_amount) / max(a, out_amount)
                if best is None or (sim, t) > (best[0], best[3]):
                    best = (sim, src, a, t)
            if best is None:
                break
            sim, src, a, t = best
            links.append(ChainLink(src, node, a, t, sim, (out_at - t).total_seconds() / 60.0))
            visited.add(src)
            node, out_amount, out_at = src, a, t
        if links:
            signals.hop_count = len(links) + 1
            signals.amount_similarity = sum(l.amount_similarity for l in links) / len(links)
            signals.time_gap_minutes = links[0].gap_minutes
            signals.pass_through = True
            signals.links = list(reversed(links))
        return signals

    def signals_for(self, sender: str, recipient: str, amount: float, at: datetime, window_minutes: int,
                    amount_tolerance: float) -> GraphSignals:
        s = self.upstream_chain(sender, amount, at, window_minutes, amount_tolerance)
        s.indirect_link = self.indirect_link(sender, recipient)
        return s
