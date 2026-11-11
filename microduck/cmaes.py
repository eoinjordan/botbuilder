# SPDX-License-Identifier: MIT
"""A small CMA-ES (Hansen's (mu/mu_w, lambda) strategy) in NumPy.

Maximises a function of a point in the unit cube. Points are clipped to the
cube before evaluation and the distance clipped off is charged as a penalty,
so the search stays near the allowed range. Seeded and bounded by a number of
generations and a wall-clock budget.
"""
from __future__ import annotations

import time

import numpy as np


def maximise(evaluate_many, dim: int, seed: int, x0=None, sigma0: float = 0.25, popsize: int = 16,
             generations: int = 50, budget_s: float = 600.0, progress=None) -> dict:
    """evaluate_many(list of points) -> list of scores. Returns the best
    point seen, its score and the history of best scores per generation."""
    rng = np.random.default_rng(seed)
    mean = np.full(dim, 0.5) if x0 is None else np.asarray(x0, float).copy()
    sigma = sigma0
    mu = popsize // 2
    weights = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
    weights /= weights.sum()
    mueff = 1.0 / np.sum(weights ** 2)
    cc = (4 + mueff / dim) / (dim + 4 + 2 * mueff / dim)
    cs = (mueff + 2) / (dim + mueff + 5)
    c1 = 2 / ((dim + 1.3) ** 2 + mueff)
    cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((dim + 2) ** 2 + mueff))
    damps = 1 + 2 * max(0.0, np.sqrt((mueff - 1) / (dim + 1)) - 1) + cs
    chi = np.sqrt(dim) * (1 - 1 / (4 * dim) + 1 / (21 * dim ** 2))
    pc, ps = np.zeros(dim), np.zeros(dim)
    cov = np.eye(dim)
    best_x, best_f, history, evaluations = mean.copy(), -np.inf, [], 0
    started = time.time()
    for generation in range(generations):
        if time.time() - started > budget_s:
            break
        values, vectors = np.linalg.eigh(cov)
        values = np.maximum(values, 1e-12)
        root = vectors @ np.diag(np.sqrt(values)) @ vectors.T
        inv_root = vectors @ np.diag(1 / np.sqrt(values)) @ vectors.T
        z = rng.standard_normal((popsize, dim))
        raw = mean + sigma * z @ root.T
        clipped = np.clip(raw, 0.0, 1.0)
        scores = np.asarray(evaluate_many([row.tolist() for row in clipped]), float)
        evaluations += popsize
        penalised = scores - 10.0 * np.sum((raw - clipped) ** 2, axis=1)
        order = np.argsort(-penalised)
        if scores.max() > best_f:
            best_f = float(scores.max())
            best_x = clipped[int(np.argmax(scores))].copy()
        history.append(round(float(scores.max()), 4))
        if progress:
            progress(generation, float(scores.max()), best_f, sigma)
        chosen = raw[order[:mu]]
        old = mean
        mean = weights @ chosen
        step = (mean - old) / sigma
        ps = (1 - cs) * ps + np.sqrt(cs * (2 - cs) * mueff) * inv_root @ step
        hsig = np.linalg.norm(ps) / np.sqrt(1 - (1 - cs) ** (2 * (generation + 1))) / chi < 1.4 + 2 / (dim + 1)
        pc = (1 - cc) * pc + hsig * np.sqrt(cc * (2 - cc) * mueff) * step
        y = (chosen - old) / sigma
        cov = ((1 - c1 - cmu) * cov + c1 * (np.outer(pc, pc) + (1 - hsig) * cc * (2 - cc) * cov)
               + cmu * (y.T * weights) @ y)
        sigma *= np.exp((cs / damps) * (np.linalg.norm(ps) / chi - 1))
        sigma = float(min(max(sigma, 1e-4), 0.5))
    return {"x": best_x.tolist(), "score": best_f, "history": history, "evaluations": evaluations,
            "generations": len(history), "seconds": round(time.time() - started, 1), "seed": seed}
