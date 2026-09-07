"""Slide figure from the priam-myopic prototype: capacity built and learning curves.

Left: annual added capacity per carrier (world, GW(h)/a) from the per-year
summaries of the run/scenario named in the model's config.yaml. Right: the
model's "capital cost versus cumulative capacity" plot from the per-year cost
ledgers (results/<run>/<scenario>/costs/<year>.csv). Same 16:9 slide layout as
the cost-baseline figures (15.2 x 5.5 cm at 1:1, legend to the right); labels
carry the learning rate from the model config. Runs standalone or from the
Snakefile.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter  # noqa: E402

MODEL = Path(__file__).resolve().parents[3] / "models" / "priam-myopic"

if "snakemake" in globals():
    COSTS = [Path(p) for p in snakemake.input.costs]
    SUMMARIES = [Path(p) for p in snakemake.input.summaries]
    MODEL_CFG = Path(snakemake.input.config)
    OUTPUTS = [Path(p) for p in snakemake.output]
else:
    MODEL_CFG = MODEL / "config.yaml"
    _c = yaml.safe_load(MODEL_CFG.read_text())
    _res = MODEL / "results" / _c["run"] / _c["scenarios"][0]
    COSTS = sorted((_res / "costs").glob("*.csv"))
    SUMMARIES = sorted((_res / "summaries").glob("*.csv"))
    OUTPUTS = [Path(__file__).parent / "figures" / f"learning_curve.{f}" for f in ("pdf", "png")]
OUTPUTS[0].parent.mkdir(exist_ok=True)

cfg = yaml.safe_load(MODEL_CFG.read_text())
styles = cfg["plotting"]["carriers"]
learning = cfg["plotting"]["metrics"]["capital_cost_vs_cumulative_capacity"]
added = cfg["plotting"]["metrics"]["added_capacity"]
step = cfg["year_step"]
lr = {c: cfg["learning"][c]["learning_rate"] for c in cfg.get("learning", {})}

DROP_LAST = 2      # end-of-horizon years are distorted by the finite horizon: not shown

costs = pd.concat([pd.read_csv(p).assign(year=int(p.stem)) for p in COSTS], ignore_index=True)
costs = costs[costs.year.isin(sorted(costs.year.unique())[:-DROP_LAST])]
summ = pd.concat([pd.read_csv(p) for p in SUMMARIES], ignore_index=True)
summ = summ[summ.year.isin(sorted(summ.year.unique())[:-DROP_LAST])]
world = summ[(summ.region == "world") & (summ.carrier.isin(added["carriers"]))]
new = (world.pivot_table(index="year", columns="carrier", values="new_capacity", aggfunc="sum")
       .reindex(columns=added["carriers"]).fillna(0.0) * added["scale"] / step)   # GW(h)/a
new = new[new.sum(axis=1) > 0]                                                   # drop seed year


def label(c):
    return styles[c]["label"] + (f" (LR {lr[c]:.0%})" if c in lr else "")


plt.rcParams.update({"axes.labelsize": 7.5, "xtick.labelsize": 6.8, "ytick.labelsize": 6.8})
fig, (axl, axr) = plt.subplots(1, 2, figsize=(15.2 / 2.54, 5.5 / 2.54), layout="constrained",
                               width_ratios=[1, 1.15])

# left: annual added capacity, stacked by carrier
bottom = np.zeros(len(new.index))
for c in new.columns:
    axl.bar(new.index, new[c], bottom=bottom, width=step * 0.8, color=styles[c]["color"],
            label=label(c))
    bottom += new[c].to_numpy()
axl.set_xlabel("Investment year")
axl.set_ylabel(f"Added capacity [{added['y_label']}]")
axl.set_xticks([y for y in new.index if y % 10 == 0])
axl.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
axl.set_axisbelow(True)
axl.grid(axis="y", color="0.85", linewidth=0.6)
axl.spines[["top", "right"]].set_visible(False)

# right: capital cost versus cumulative capacity (the learning curves)
for c in learning["carriers"]:
    curve = costs[(costs.carrier == c) & (costs.cumulative_capacity > 0)
                  & (costs.capital_cost > 0)].sort_values("cumulative_capacity")
    axr.plot(curve.cumulative_capacity * learning["x_scale"], curve.capital_cost,
             color=styles[c]["color"], marker="o", markersize=3.2, lw=1.4)
axr.set_xscale("log")
axr.set_yscale("log")
for axis in (axr.xaxis, axr.yaxis):
    axis.set_major_locator(LogLocator(base=10, numticks=12))
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    axis.set_minor_formatter(NullFormatter())
axr.set_axisbelow(True)
axr.grid(which="major", color="0.75", linewidth=0.7)
axr.grid(which="minor", color="0.88", linewidth=0.4)
axr.spines[["top", "right"]].set_visible(False)
axr.set_xlabel(learning["x_label"])
axr.set_ylabel(learning["y_label"])

handles = [Patch(facecolor=styles[c]["color"], label=label(c)) for c in new.columns]
handles.append(Line2D([0, 1], [0, 0], color="0.3", marker="o", markersize=3.2, lw=1.2,
                      label="cost after each investment year"))
fig.legend(handles=handles, loc="outside right upper", ncol=1, fontsize=6.5, frameon=False,
           handlelength=1.8, labelspacing=0.9)
for out in OUTPUTS:
    fig.savefig(out, dpi=200, bbox_inches="tight")
print("wrote", ", ".join(str(o) for o in OUTPUTS))
