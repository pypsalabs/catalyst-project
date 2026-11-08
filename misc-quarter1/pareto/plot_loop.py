"""Figures of the learning loop (misc-quarter1/pareto).

  figures/loop_<dataset>    one row of stacked bars per round: power capacity built per technology
                            in multiples of the system's peak load (GW annotated), storage energy in
                            hours of peak load, LCOE under each bar; a legend table on top with the
                            CAPEX, FOM, learning rate and reference capacity of every component
  figures/energy_<dataset>  the same grid with energy: generation of every generator and discharge of
                            every storage technology as a share of annual demand
  figures/capex_<dataset>   capex per component over the rounds, one line per series

Standalone: python plot_loop.py <dataset>
"""

import logging
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if "snakemake" in globals():  # Snakemake runs a copy of this file; make the sibling modules importable
    sys.path.insert(0, str(Path(snakemake.input.config).resolve().parent))  # noqa: F821
from techs import load_components, load_config, world_shares

matplotlib.use("Agg")
log = logging.getLogger("plot")

if "snakemake" in globals():
    CFG = load_config(snakemake.input.config)  # noqa: F821
    DATASET = snakemake.wildcards.dataset  # noqa: F821
    LOOP = Path(snakemake.input.loop)  # noqa: F821
    OUTPUTS = [Path(p) for p in snakemake.output]  # noqa: F821
else:
    CFG = load_config()
    DATASET = sys.argv[1] if len(sys.argv) > 1 else "sites"
    LOOP = CFG["_dir"] / "build" / f"loop_{DATASET}.csv"
    OUTPUTS = [CFG["_dir"] / "figures" / f"{fig}_{DATASET}.{fmt}" for fig in ("loop", "energy", "capex") for fmt in CFG["plotting"]["formats"]]

INK, INK2, MUTED, GRID = "#1f1f1f", "#4d4d4d", "#8a8a8a", "#e6e6e6"
plt.rcParams.update({"font.size": 8, "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "text.color": INK, "axes.spines.top": False, "axes.spines.right": False})
POWER_COMPONENTS = ["plant", "power", "sofc"]          # components whose `built` is a power capacity to stack
SHORT = {"battery-liion": "Li", "vrfb": "VRFB", "co2-battery": "CO2", "iron-air": "Fe-air", "h2": "H2"}


def short_series(name: str, dataset: str) -> str:
    return name.replace(" · ", "\n") if dataset == "sites" else name


def interpretation(cfg: dict) -> str:
    lb = cfg["learning_base"]
    shares = " → ".join(f"{x * 100:.0f} %" for x in world_shares(cfg))
    how = ("each round's build is counted for the growth of the sub-system since the previous round"
           if lb.get("counting", "increment") == "increment" else "each round's whole fleet is counted at that share")
    return (f"Learning base: global cumulative capacity. The system is a clean sub-system of the world growing from {shares} of world "
            f"demand ({lb['world_demand_twh']:,.0f} TWh) over the rounds; {how}, scaled by (share × world demand / site demand). "
            "Greenfield rounds; no exchange between systems.")


def save(fig: plt.Figure, stem: str) -> None:
    for out in OUTPUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.stem == f"{stem}_{DATASET}":
            fig.savefig(out, dpi=CFG["plotting"]["dpi"], bbox_inches="tight")
            log.info("wrote %s", out)
    plt.close(fig)


def money(x: float, unit: str) -> str:
    return "–" if x == 0 else f"{x:,.0f} $/k{unit[1:]}" if x >= 10 else f"{x:.1f} $/k{unit[1:]}"


def base_text(mw: float, unit: str) -> str:
    """MW / MWh -> a readable GW / GWh or MW / MWh string."""
    if mw >= 1e3:
        return f"{mw / 1e3:,.0f} G{unit[1:]}" if mw >= 1e4 else f"{mw / 1e3:,.2g} G{unit[1:]}"
    return f"{mw:,.0f} {unit}"


def site_cost_text(df: pd.DataFrame, tech: str) -> str:
    """Cheapest tranche across the series, from the loop output."""
    col = f"cheapest_{tech}_usd_kw"
    if col in df:
        vals = df.loc[df.step == 0, col].dropna()
        if len(vals):
            rng = f"{vals.min():,.0f}" if abs(vals.max() - vals.min()) < 1 else f"{vals.min():,.0f}–{vals.max():,.0f}"
            return f"per site; cheapest tranche {rng} $/kW"
    return "per site (supply-curve tranches)"


def legend_table(ax: plt.Axes, comps: pd.DataFrame, order: list, df: pd.DataFrame) -> None:
    """Swatch, technology, and one line per component: capex, FOM, learning rate, reference base."""
    ax.axis("off")
    rows, colours = [], []
    for tech in order:
        sub = comps.xs(tech, level="tech")
        label = sub["tech_label"].iloc[0]
        for k, (comp, c) in enumerate(sub.iterrows()):
            cname = "" if len(sub) == 1 else comp
            unit = "MW" if c["unit"] == "MW" else "MWh"
            if c["site_specific"]:
                capex_text = site_cost_text(df, tech) if comp == "plant" else "well share of the tranche CAPEX"
                fom_text = "per tranche" if comp == "plant" else ""
            else:
                capex_text, fom_text = money(c["capex0"], unit), f"{c['fom_frac'] * 100:.1f} %/a"
            rows.append(["", label if k == 0 else "", cname, capex_text, fom_text, f"{c['lifetime']:.0f} a",
                         f"{c['learning_rate'] * 100:.0f} %" if c["learning_rate"] else "–",
                         base_text(c["cref_global"], unit) + (f" (floor one unit: {base_text(c['floor'], unit)})" if c["floor"] > c["cref_global"] else "")])
            colours.append(sub["colour"].iloc[0] if k == 0 else "white")
    header = ["", "technology", "component", "CAPEX (USD2024)", "FOM", "life", "learning rate", "global reference base"]
    table = ax.table(cellText=rows, colLabels=header, loc="center", cellLoc="left", colLoc="left",
                     colWidths=[0.02, 0.17, 0.08, 0.27, 0.07, 0.05, 0.09, 0.25])
    table.auto_set_font_size(False)
    table.set_fontsize(6.6)
    for (r, cidx), cell in table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_linewidth(0.4)
        if r == 0:
            cell.set_text_props(color=INK2, weight="bold")
            cell.set_facecolor("white")
        elif cidx == 0:
            cell.set_facecolor(colours[r - 1])
            cell.set_edgecolor(colours[r - 1] if colours[r - 1] != "white" else GRID)
        cell.PAD = 0.03


def stacked_rows(df: pd.DataFrame, comps: pd.DataFrame, order: list, value_fn, ylabel: str, title: str,
                 annotate_fn=None, ylim=None) -> plt.Figure:
    """steps rows x one stacked bar per series."""
    series = list(dict.fromkeys(df["series"]))
    steps = sorted(df["step"].unique())
    fig = plt.figure(figsize=(13, 2.3 * len(steps) + 5.0))
    gs = fig.add_gridspec(len(steps) + 1, 1, height_ratios=[3.6] + [2.2] * len(steps), hspace=0.5, top=0.935, bottom=0.06)
    legend_table(fig.add_subplot(gs[0]), comps, order, df)
    x = np.arange(len(series))
    colours = {t: comps.xs(t, level="tech")["colour"].iloc[0] for t in order}
    axes = []
    for step in steps:
        ax = fig.add_subplot(gs[step + 1], sharex=axes[0] if axes else None)
        axes.append(ax)
        bottom = np.zeros(len(series))
        for tech in order:
            vals = np.array([value_fn(df[(df.series == s) & (df.step == step)], tech) for s in series])
            ax.bar(x, vals, 0.62, bottom=bottom, color=colours[tech], edgecolor="white", linewidth=0.6, label=tech)
            bottom += vals
        if annotate_fn is not None:
            for xi, s in zip(x, series):
                text = annotate_fn(df[(df.series == s) & (df.step == step)])
                ax.text(xi, bottom[xi] + (ylim[1] if ylim else bottom.max()) * 0.02, text, ha="center", va="bottom",
                        fontsize=5.8, color=INK2, linespacing=1.1)
        ax.set_ylabel(ylabel, fontsize=7.5)
        share = world_shares(CFG)[step] * 100
        ax.set_title(f"round {step} — {share:.0f} % of world demand" + ("  (2025 baseline costs)" if step == 0 else f"  (costs after learning from the build of round {step - 1})"),
                     loc="left", fontsize=8, weight="bold", color=INK2, pad=3)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        if ylim:
            ax.set_ylim(*ylim)
        else:
            ax.set_ylim(0, bottom.max() * 1.42)
        ax.set_xlim(-0.6, len(series) - 0.4)
        if step != steps[-1]:
            ax.tick_params(labelbottom=False)
    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels([short_series(s, DATASET) for s in series], fontsize=7)
    axes[-1].set_xlabel(CFG["datasets"][DATASET]["column_label"], fontsize=8)
    fig.suptitle(title, x=0.01, ha="left", fontsize=10, weight="bold", y=0.99)
    import textwrap
    fig.text(0.01, 0.972, "\n".join(textwrap.wrap(interpretation(CFG), 175)), ha="left", va="top", fontsize=7.5, color=INK2, linespacing=1.3)
    return fig


def power_built(sub: pd.DataFrame, tech: str) -> float:
    """Power capacity in multiples of peak load: generators, storage dischargers, SOFC, geothermal plant."""
    peak = sub["peak_mw"].iloc[0]
    rows = sub[(sub.tech == tech) & (sub.component.isin(POWER_COMPONENTS))]
    return rows["built"].sum() / peak


def energy_share(sub: pd.DataFrame, tech: str) -> float:
    demand = sub["demand_mwh"].iloc[0]
    return sub[(sub.tech == tech)]["energy_served_mwh"].sum() / demand


def annotate_capacity(sub: pd.DataFrame) -> str:
    peak = sub["peak_mw"].iloc[0]
    gw = sub[sub.component.isin(POWER_COMPONENTS)]["built"].sum() / 1e3
    stores = sub[sub.component.isin(["energy", "tank", "cavern"]) & (sub.built > 1)]
    stores = stores[stores.built / peak >= 0.05]
    hours = " ".join(f"{SHORT[t]} {b / peak:.0f}h" if b / peak >= 2 else f"{SHORT[t]} {b / peak:.1f}h" for t, b in zip(stores.tech, stores.built))
    return f"{gw:.0f} GW · {sub['lcoe'].iloc[0]:.0f} $/MWh\n{hours}"


def annotate_energy(sub: pd.DataFrame) -> str:
    demand = sub["demand_mwh"].iloc[0]
    curt = sub["curtailed_mwh"].fillna(0).sum() / demand if "curtailed_mwh" in sub else float("nan")
    return f"curtailed {curt * 100:.0f} %"


def capex_figure(df: pd.DataFrame, comps: pd.DataFrame, order: list) -> plt.Figure:
    learning = comps[comps["learning_rate"] > 0]
    n = len(learning)
    ncol = 5
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(13, 2.6 * nrow), squeeze=False)
    series = list(dict.fromkeys(df["series"]))
    steps = sorted(df["step"].unique())
    for ax, ((tech, comp), c) in zip(axes.flat, learning.iterrows()):
        for k, s in enumerate(series):
            sub = df[(df.series == s) & (df.tech == tech) & (df.component == comp)].sort_values("step")
            y = list(sub["capex_used"]) + [sub["capex_next"].iloc[-1]]
            ax.plot(steps + [steps[-1] + 1], y, color=c["colour"], alpha=0.35 + 0.5 * k / max(len(series) - 1, 1), linewidth=1.4,
                    marker="o", markersize=3, label=short_series(s, DATASET).replace("\n", " "))
        label = c["tech_label"].split(" (")[0]
        ax.set_title(label + (f" — {comp}" if comp != "plant" else "") + f"  (LR {c['learning_rate'] * 100:.0f} %)", fontsize=8, loc="left")
        ax.set_ylim(0, c["capex0"] * 1.1)
        ax.set_xticks(steps + [steps[-1] + 1])
        ax.set_xticklabels([str(s) for s in steps] + ["next"], fontsize=7)
        ax.set_ylabel("cost factor" if c["site_specific"] else f"USD/k{c['unit'][1:]}", fontsize=7)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
    for ax in axes.flat[n:]:
        ax.axis("off")
    axes.flat[0].legend(fontsize=6, frameon=False, ncol=2, loc="lower left")
    fig.suptitle(f"CAPEX applied in each round after learning from the system's own build — {CFG['datasets'][DATASET]['title']}",
                 x=0.01, ha="left", fontsize=10, weight="bold")
    fig.supxlabel("round", fontsize=8)
    fig.tight_layout()
    return fig


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    comps = load_components(CFG)
    order = [t for t in CFG["plotting"]["order"] if t in comps.index.get_level_values("tech")]
    df = pd.read_csv(LOOP)
    df["series"] = df["series"].astype(str)
    title = CFG["datasets"][DATASET]["title"]
    fig = stacked_rows(df, comps, order, power_built, "capacity / peak load", f"Power capacity built in each round — {title}",
                       annotate_fn=annotate_capacity)
    save(fig, "loop")
    fig = stacked_rows(df, comps, order, energy_share, "energy / annual demand", f"Generation and storage discharge per round, as a share of annual demand — {title}",
                       annotate_fn=annotate_energy)
    save(fig, "energy")
    save(capex_figure(df, comps, order), "capex")


if __name__ == "__main__":
    main()
