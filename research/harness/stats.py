"""Significance and robustness statistics for a list of per-trade values."""

from __future__ import annotations

import numpy as np

# Pre-registered periods. HOLDOUT is touched once per hypothesis, via --confirm-holdout.
SPLITS = {
    'train': ('2019-01-01', '2023-01-01'),
    'valid': ('2023-01-01', '2025-01-01'),
    'holdout': ('2025-01-01', '2027-01-01'),
}


def signflip_p(values: np.ndarray, n_perm: int = 20_000, seed: int = 0) -> float:
    """Two-sided p that |mean| is this large if outcomes were symmetric around zero."""
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        return 1.0
    rng = np.random.default_rng(seed)
    observed = abs(v.mean())
    hits, done, chunk = 0, 0, max(1, 4_000_000 // len(v))
    while done < n_perm:
        k = min(chunk, n_perm - done)
        signs = rng.integers(0, 2, size=(k, len(v)), dtype=np.int8) * 2 - 1
        hits += int((np.abs((signs * v).mean(axis=1)) >= observed - 1e-12).sum())
        done += k
    return (hits + 1) / (n_perm + 1)


def max_drawdown(values: np.ndarray) -> float:
    cum = np.cumsum(values)
    return float((np.maximum.accumulate(np.concatenate(([0.0], cum)))[1:] - cum).max()) if len(cum) else 0.0


def summarize(values, n_perm: int = 20_000) -> dict:
    v = np.asarray([x for x in values if np.isfinite(x)], dtype=float)
    n = len(v)
    if n < 2:
        return {'n': n}
    std = float(v.std(ddof=1))
    wins, losses = v[v > 0].sum(), -v[v < 0].sum()
    return {'n': n, 'mean': float(v.mean()), 'std': std,
            't': float(v.mean() / (std / np.sqrt(n))) if std else 0.0,
            'win_rate': float((v > 0).mean()),
            'profit_factor': float(wins / losses) if losses else float('inf'),
            'max_dd': max_drawdown(v), 'p_signflip': signflip_p(v, n_perm)}


def by_year(trades: list[dict], key: str) -> dict[int, tuple[int, float]]:
    out: dict[int, list[float]] = {}
    for t in trades:
        if np.isfinite(t[key]):
            out.setdefault(t['date'].year, []).append(t[key])
    return {y: (len(v), float(np.mean(v))) for y, v in sorted(out.items())}


def passes_gate(summary: dict, yearly: dict, n_trials: int, min_n: int = 300) -> bool:
    """Promotion gate: n, positive net mean, t>=2 Bonferroni-adjusted p<0.05, most years positive."""
    if summary.get('n', 0) < min_n or summary['mean'] <= 0:
        return False
    if summary['p_signflip'] * n_trials >= 0.05:
        return False
    positive = sum(1 for _, m in yearly.values() if m > 0)
    return positive > len(yearly) / 2
