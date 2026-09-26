"""A small, faithful numpy implementation of the XGBoost training algorithm.

Used when the real `xgboost` library is not installed. It implements the same
maths as XGBoost's `hist` tree method for `binary:logistic`:

  * second-order gradients: g = p - y, h = p * (1 - p), scaled by sample weight
    (positive rows are weighted by scale_pos_weight)
  * L2-regularised leaf weights: w = -G / (H + lambda)
  * split gain: 0.5 * [GL^2/(HL+lambda) + GR^2/(HR+lambda) - G^2/(H+lambda)] - gamma
  * shrinkage: every leaf is multiplied by eta
  * row subsampling per tree
  * histogram split candidates from per-feature quantile cuts (max_bin bins)

The output uses the browser tree format: {"f", "t", "l", "r"} for splits and
{"v"} for leaves, where x < t goes left and leaf values already include eta.
"""

from __future__ import annotations

import math

import numpy as np


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


class NumpyXGBClassifier:
    def __init__(self, n_estimators=60, max_depth=3, eta=0.2, reg_lambda=1.0, gamma=0.0,
                 subsample=0.8, max_bin=32, min_child_weight=1.0, scale_pos_weight=1.0, seed=42):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.eta = eta
        self.reg_lambda = reg_lambda
        self.gamma = gamma
        self.subsample = subsample
        self.max_bin = max_bin
        self.min_child_weight = min_child_weight
        self.scale_pos_weight = scale_pos_weight
        self.seed = seed
        self.trees = []
        self.base_score = 0.5
        self.cuts = []

    # -- histogram cuts ---------------------------------------------------
    def _make_cuts(self, X):
        cuts = []
        qs = np.linspace(0, 1, self.max_bin + 1)[1:-1]
        for j in range(X.shape[1]):
            col = X[:, j]
            uniq = np.unique(col)
            if len(uniq) <= self.max_bin:
                c = (uniq[:-1] + uniq[1:]) / 2.0 if len(uniq) > 1 else np.array([])
            else:
                c = np.unique(np.quantile(col, qs))
            # float32 thresholds, like xgboost, so the browser's Math.fround compare matches
            cuts.append(np.unique(np.asarray(c, dtype=np.float32)).astype(float))
        return cuts

    def _bin(self, X):
        B = np.zeros(X.shape, dtype=np.int32)
        for j, c in enumerate(self.cuts):
            # bin b holds cuts[b-1] <= x < cuts[b]; "bin <= b" is exactly "x < cuts[b]"
            B[:, j] = np.searchsorted(c, X[:, j], side="right")
        return B

    # -- tree growth ------------------------------------------------------
    def _leaf(self, G, H):
        return -G / (H + self.reg_lambda) * self.eta

    def _score(self, G, H):
        return G * G / (H + self.reg_lambda)

    def _grow(self, B, g, h, idx, depth, nodes):
        G, H = g[idx].sum(), h[idx].sum()
        node_id = len(nodes)
        nodes.append(None)
        best = None
        if depth < self.max_depth and len(idx) > 1:
            parent = self._score(G, H)
            for j, c in enumerate(self.cuts):
                nb = len(c) + 1
                if nb < 2:
                    continue
                gh = np.bincount(B[idx, j], weights=g[idx], minlength=nb)
                hh = np.bincount(B[idx, j], weights=h[idx], minlength=nb)
                GL, HL = np.cumsum(gh)[:-1], np.cumsum(hh)[:-1]
                GR, HR = G - GL, H - HL
                ok = (HL >= self.min_child_weight) & (HR >= self.min_child_weight)
                if not ok.any():
                    continue
                gain = 0.5 * (self._score(GL, HL) + self._score(GR, HR) - parent) - self.gamma
                gain = np.where(ok, gain, -np.inf)
                b = int(np.argmax(gain))
                if gain[b] > 1e-12 and (best is None or gain[b] > best[0]):
                    best = (gain[b], j, b)
        if best is None:
            nodes[node_id] = {"v": float(self._leaf(G, H))}
            return node_id
        _, j, b = best
        left_mask = B[idx, j] <= b
        li, ri = idx[left_mask], idx[~left_mask]
        l = self._grow(B, g, h, li, depth + 1, nodes)
        r = self._grow(B, g, h, ri, depth + 1, nodes)
        nodes[node_id] = {"f": int(j), "t": float(self.cuts[j][b]), "l": l, "r": r}
        return node_id

    def fit(self, X, y):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        rng = np.random.default_rng(self.seed)
        self.cuts = self._make_cuts(X)
        B = self._bin(X)
        w = np.where(y == 1, self.scale_pos_weight, 1.0)
        self.base_score = float(np.clip(y.mean(), 1e-6, 1 - 1e-6))
        margin = np.full(len(y), math.log(self.base_score / (1 - self.base_score)))
        self.trees = []
        n = len(y)
        for _ in range(self.n_estimators):
            p = _sigmoid(margin)
            g = (p - y) * w
            h = np.maximum(p * (1 - p), 1e-16) * w
            idx = np.flatnonzero(rng.random(n) < self.subsample) if self.subsample < 1 else np.arange(n)
            nodes = []
            self._grow(B, g, h, idx, 0, nodes)
            self.trees.append(nodes)
            margin = margin + self._predict_tree(nodes, X)
        return self

    @staticmethod
    def _predict_tree(nodes, X):
        out = np.empty(len(X))
        stack = [(0, np.arange(len(X)))]
        while stack:
            k, idx = stack.pop()
            nd = nodes[k]
            if "v" in nd:
                out[idx] = nd["v"]
                continue
            go_left = X[idx, nd["f"]] < nd["t"]
            stack.append((nd["l"], idx[go_left]))
            stack.append((nd["r"], idx[~go_left]))
        return out

    def predict_proba(self, X):
        X = np.asarray(X, dtype=float)
        m = np.full(len(X), math.log(self.base_score / (1 - self.base_score)))
        for t in self.trees:
            m = m + self._predict_tree(t, X)
        return _sigmoid(m)

    def to_browser(self):
        return {"base_score": self.base_score, "trees": [{"nodes": t} for t in self.trees]}
