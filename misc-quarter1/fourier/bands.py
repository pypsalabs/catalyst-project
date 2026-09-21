"""Period-band decomposition of a residual demand series and the three-axis radar that shows it
(misc-quarter1/fourier). Shared by plot_residual_structure.py and plot_mix_radar.py."""

import numpy as np
import pandas as pd
from matplotlib.lines import Line2D


def fmt_period(h: float) -> str:
    for unit, hours in (("yr", 8760), ("mo", 730), ("wk", 168), ("d", 24), ("h", 1)):
        if h >= hours - 1e-9 and abs(h / hours - round(h / hours)) < 1e-6:
            return f"{round(h / hours)} {unit}"
    return f"{h:g} h"


def band_ranges(edges) -> list[str]:
    return [f"≤ {fmt_period(edges[0])}", f"{fmt_period(edges[0])} – {fmt_period(edges[1])}", f"≥ {fmt_period(edges[1])}"]


def band_masks(n: int, edges, labels) -> dict[str, np.ndarray]:
    """Boolean mask over the rfft bins of an n-hour series for each of the three period bands:
    period <= edges[0] (the diurnal line included), between, >= edges[1] (the monthly bin included).
    The DC bin belongs to no band."""
    per = np.full(n // 2 + 1, np.inf)
    per[1:] = 1 / np.fft.rfftfreq(n, d=1.0)[1:]
    return {
        labels[0]: per <= edges[0],
        labels[1]: (per > edges[0]) & (per < edges[1]),
        labels[2]: (per >= edges[1]) & np.isfinite(per),
    }


def band_stats(x, masks: dict[str, np.ndarray]) -> pd.DataFrame:
    """Band-pass the mean-removed residual (in units of mean demand) through each period band, all
    other Fourier bins set to zero, and report per band
      shifted_pct_annual_demand  energy a lossless storage acting on that band alone would cycle
                                 per year = positive part of the band-passed series, % of annual demand
      rms_pct_mean_demand        RMS of the band-passed series, % of mean demand
    The band series add up to the mean-removed residual; the DC part (the surplus from
    overbuilding) is left out."""
    v = np.asarray(x, dtype=float)
    v = v - v.mean()
    n = len(v)
    X = np.fft.rfft(v)
    rows = {}
    for band, mask in masks.items():
        b = np.fft.irfft(X * mask, n=n)
        rows[band] = {"shifted_pct_annual_demand": 100 * b.clip(0).sum() / n,
                      "rms_pct_mean_demand": 100 * np.sqrt(np.mean(b ** 2))}
    return pd.DataFrame(rows).T


def radar(ax, series: list[dict], labels, ranges, step: float = 10, member_label: str | None = None):
    """Three-axis radar on a polar axes with a polygonal grid.
    series: dicts with label, colour, mean (3 values in band order), optional members (list of
    3-vectors drawn thin and translucent), optional ls (line style) and lw.
    Returns legend handles."""
    ang = np.pi / 2 + np.arange(3) * 2 * np.pi / 3          # top, lower left, lower right
    close = lambda a: np.append(a, a[0])  # noqa: E731
    vmax = max(np.max([s["mean"], *s.get("members", [])]) for s in series)
    rmax = step * np.ceil(vmax / step)
    ax.set_ylim(0, rmax * 1.45)                             # room for the axis labels inside the axes
    ax.spines["polar"].set_visible(False)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    for r in np.arange(step, rmax + 1e-9, step):
        ax.plot(close(ang), np.full(4, r), color="0.86", lw=0.6, zorder=0)
        if round(r / step) % 2 == 0:                        # ring labels at the bottom edge of every other ring
            ax.text(3 * np.pi / 2, r / 2, f"{r:.0f} %", fontsize=6.5, color="0.5", ha="center", va="bottom",
                    bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.85), zorder=4)
    for a, lab, rng in zip(ang, labels, ranges):
        ax.plot([a, a], [0, rmax], color="0.75", lw=0.8, zorder=0)
        ax.text(a, rmax * 1.22, f"{lab}\n{rng}", ha="center", va="center", fontsize=8.5, color="0.2", linespacing=1.3)
    handles = []
    for s in series:
        for m in s.get("members", []):
            ax.plot(close(ang), close(np.asarray(m)), color=s["colour"], lw=0.7, alpha=0.3)
        ls, lw = s.get("ls", "-"), s.get("lw", 2)
        ax.plot(close(ang), close(np.asarray(s["mean"])), color=s["colour"], lw=lw, ls=ls)
        ax.fill(close(ang), close(np.asarray(s["mean"])), color=s["colour"], alpha=0.10)
        handles.append(Line2D([], [], color=s["colour"], lw=lw, ls=ls, label=s["label"]))
    if member_label:
        handles.append(Line2D([], [], color="0.4", lw=0.7, alpha=0.5, label=member_label))
    return handles
