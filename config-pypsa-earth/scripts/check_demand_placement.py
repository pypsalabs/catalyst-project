# SPDX-License-Identifier: CC0-1.0
"""
Where a run's electricity demand sits inside a country, against published statistics per GADM level-1 unit.

Read-only: sums resources/<run>/demand_profiles.csv per bus of the base network, puts every bus into the unit that
contains it (scripts/build_market_zones.py, unit_of_buses) and compares the units' demand with
calibration/2024/demand_shares.csv scaled to the run's national demand. Writes
model-doc/build/demand_placement/<label>.csv (key, name, published_twh, model_twh, ratio).

Usage (from config-pypsa-earth):
    ../models/pypsa-earth/.pixi/envs/default/bin/python scripts/check_demand_placement.py RUN [--label NAME] [--country CN]
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK = os.path.join(HERE, "..", "models", "pypsa-earth")
OUT = os.path.join(HERE, "model-doc", "build", "demand_placement")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def demand_per_bus(run):
    """Annual demand per base bus in TWh (the file is hours x buses, read in chunks)."""
    total = None
    for chunk in pd.read_csv(os.path.join(FORK, "resources", run, "demand_profiles.csv"), index_col=0, chunksize=1000):
        total = chunk.sum() if total is None else total + chunk.sum()
    return total / 1e6


def main():
    import pypsa
    import build_market_zones as bmz

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("run")
    p.add_argument("--label", default=None)
    p.add_argument("--country", default="CN")
    a = p.parse_args()

    load = demand_per_bus(a.run)
    base = pypsa.Network(os.path.join(FORK, "networks", a.run, "base.nc"))
    b = base.buses.loc[base.buses.index.intersection(load.index), ["x", "y", "country"]]
    b = b[b.country == a.country]
    unit = bmz.unit_of_buses(b, os.path.join(FORK, "resources", a.run, "shapes", "gadm_shapes.geojson"))
    model = load.reindex(b.index).groupby(unit).sum()

    pub = pd.read_csv(os.path.join(HERE, "calibration", "2024", "demand_shares.csv"))
    pub = pub[pub.country == a.country].set_index("key")
    out = pd.DataFrame({"name": pub.name, "share_published": pub.share, "published_twh": pub.share * model.sum(),
                        "model_twh": model.reindex(pub.index).fillna(0.0)})
    out["ratio"] = out.model_twh / out.published_twh
    out = out.sort_values("published_twh", ascending=False)
    os.makedirs(OUT, exist_ok=True)
    fn = os.path.join(OUT, f"{a.label or a.run}.csv")
    out.round(4).to_csv(fn)
    off = (out.model_twh - out.published_twh).abs().sum() / 2
    print(f"{a.run}: national {model.sum():.0f} TWh over {len(b)} buses; {off:.0f} TWh ({off / model.sum():.1%}) sit in the wrong unit; "
          f"model / published from {out.ratio.min():.2f} ({out.ratio.idxmin()}) to {out.ratio.max():.2f} ({out.ratio.idxmax()})")
    print(out.round(2).to_string())
    print(f"-> {fn}")


if __name__ == "__main__":
    main()
