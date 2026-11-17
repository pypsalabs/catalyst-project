"""One week of the hourly wind and solar profiles at a few buses (Renewables & Weather, standard procedure).

One panel per carrier (solar, onshore wind, offshore wind), one line per location: the profile of the bus of the base
network nearest to a named point that has potential for the carrier, as build_renewable_profiles writes it
(resources/<R>/renewable_profiles/profile_<carrier>.nc; ERA5 weather of 2013, before any adjustment of the fork). Solar
and onshore wind share their locations, offshore wind has coastal ones. The lines of a panel are shades of one colour, from
dark to light in the order of the legend. Time in UTC, as in the model. Bus coordinates from
networks/<R>/base.nc.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/plot_renew_timeseries.py
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

HERE = Path(snakemake.scriptdir) if "snakemake" in globals() else Path(__file__).resolve().parent
TOP = HERE.parent
sys.path.insert(0, str(next(p for p in TOP.parents if (p / "plotstyle").is_dir()) / "plotstyle"))
import studystyle as st  # noqa: E402

FORK = TOP / "../../models/pypsa-earth"
PERIOD = ("2013-06-03", "2013-06-09 23:00")
# label, run, (lon, lat)
LAND = [("West Texas, US", "US", (-101.9, 33.6)), ("Rio Grande do Norte, Brazil", "BR", (-36.5, -5.6)),
        ("Schleswig-Holstein, Germany", "NWE", (9.5, 54.3)), ("Inner Mongolia, China", "CN", (111.7, 40.8))]
COAST = [("Massachusetts, US", "US", (-70.6, 41.7)), ("Ceará, Brazil", "BR", (-38.5, -3.7)),
         ("German North Sea coast", "NWE", (8.6, 53.8)), ("Jiangsu, China", "CN", (120.9, 33.0))]
# carrier, title, locations, four shades of the carrier's colour (dark to light)
PANELS = [("solar", "Solar", LAND, ["#5c3d00", "#9a6700", "#d39200", "#efc55a"]),
          ("onwind", "Onshore wind", LAND, ["#0f4662", "#2586b8", "#56B4E9", "#a9daf6"]),
          ("offwind-ac", "Offshore wind (AC connection)", COAST, ["#0a2540", "#0072B2", "#5a9fd4", "#aacbe8"])]
RUNS = ["US", "BR", "NWE", "CN"]


def series(fork, run, carrier, point, coords):
    """Profile of the bus nearest to `point` that has potential for the carrier: (bus, hourly values, annual mean)."""
    with xr.open_dataset(fork / f"resources/{run}/renewable_profiles/profile_{carrier}.nc") as ds:
        buses = [b for b, p in zip(ds.bus.values.astype(str), ds["p_nom_max"].values) if p > 0 and b in coords]
        xy = np.array([coords[b] for b in buses])
        d = (xy[:, 0] - point[0]) ** 2 * np.cos(np.deg2rad(point[1])) ** 2 + (xy[:, 1] - point[1]) ** 2
        bus = buses[int(np.argmin(d))]
        s = ds["profile"].sel(bus=bus).to_pandas()
    return bus, s.loc[PERIOD[0]:PERIOD[1]], float(s.mean()), coords[bus]


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--fork", default=FORK)
    p.add_argument("--out", default=TOP / "build/figures/renew_timeseries.pdf")
    if "snakemake" in globals():
        a = p.parse_args(["--fork", snakemake.params.fork, "--out", snakemake.output[0]])
    else:
        a = p.parse_args()
    fork = Path(a.fork)
    coords = {}
    for run in RUNS:
        with xr.open_dataset(fork / f"networks/{run}/base.nc") as ds:
            coords[run] = dict(zip(ds["buses_i"].values.astype(str), zip(ds["buses_x"].values, ds["buses_y"].values)))

    st.use()
    fig, axes = plt.subplots(3, 1, figsize=(6.3, 6.0), sharex=True)
    for ax, (carrier, title, places, shades) in zip(axes, PANELS):
        for (label, run, point), colour in zip(places, shades):
            bus, s, mean, xy = series(fork, run, carrier, point, coords[run])
            ax.plot(s.index, s.values, color=colour, linewidth=1.0, label=f"{label} (annual mean {mean:.2f})")
            print(f"{carrier:10s} {label:28s} bus {bus:>6s} at {xy[0]:8.2f} {xy[1]:7.2f}  mean {mean:.3f}  week {s.mean():.3f}")
        ax.set_ylim(0, 1.0)
        ax.set_yticks([0, 0.5, 1.0])
        ax.set_title(title, loc="left", fontsize=8.5)
        ax.set_ylabel("Capacity factor")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=6.5, handlelength=1.4, columnspacing=1.6)
    axes[-1].set_xlim(s.index[0], s.index[-1])
    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=1))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%-d %b"))
    for ax in axes:
        ax.tick_params(axis="x", labelbottom=True, labelsize=6.5)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    fig.savefig(Path(a.out).with_suffix(".png"), dpi=200)
    print(f"-> {a.out}")


if __name__ == "__main__" or "snakemake" in globals():
    main()
