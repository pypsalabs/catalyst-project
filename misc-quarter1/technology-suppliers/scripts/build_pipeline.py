"""Cumulative capacity per technology, company and layer (operating / construction / announced / target).

Reads the hand-curated data/projects.csv, data/targets.csv and data/companies.csv, adds the Gen IV units of the
GEM nuclear tracker (../nuclear-projects) through data/gen4_vendor_map.csv, and writes

    build/pipeline.csv        tech, company, continent, layer, year, mw (cumulative, by layer, not stacked)
    build/companies.csv       per tech and company: continent, colour rank, MW per layer, undated MW, targets
    build/summary.csv         per tech and layer: GW in 2025, 2030, 2035, 2040; storage duration used
    build/crosscheck.csv      operating end-2025 and construction totals vs technology_assumptions.csv

Layers (each stacked on the previous one in the charts):
    operating     online, at its actual first-power year
    construction  under construction / post-FID / firm contract, at its stated online year
    announced     pre-FID projects at their stated online year (undated ones are counted but not drawn)
    target        the gap between the company's projects and its stated targets: offtake deals and corporate
                  goals (straight line from the project total today to the stated value at the stated year,
                  flat afterwards) and stated factory capacity run at nameplate until `factory_until`

    python scripts/build_pipeline.py            (from misc-quarter1/technology-suppliers)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1]
LAYERS = ["operating", "construction", "announced", "target"]


def load_config():
    with open(HERE / "config.yaml") as f:
        return yaml.safe_load(f)


def read(name):
    p = HERE / "data" / name
    return pd.read_csv(p, comment=None, dtype=str, keep_default_na=False).replace({"": np.nan})


def num(s):
    return pd.to_numeric(s, errors="coerce")


def gem_continent(row):
    if row["region"] == "Americas":
        return "NAM" if row["subregion"] == "Northern America" else "SAM"
    return {"Europe": "EUR", "Asia": "ASI", "Africa": "AFR", "Oceania": "OCE"}.get(row["region"], np.nan)


def gen4_from_gem(cfg, projects):
    """GEM units of the Gen IV families as project rows, vendor from the map, corrections applied."""
    units = pd.read_csv(HERE / cfg["gem_units"], dtype={"unit": str})
    units = units[units.family.isin(cfg["gen4_families"]) & units.status.isin(cfg["gem_status"])].copy()
    vmap = read("gen4_vendor_map.csv")
    vmap["model"] = vmap["model"].fillna("unknown")
    units["model"] = units["model"].fillna("unknown")
    units = units.merge(vmap[["project", "model", "vendor", "include"]], on=["project", "model"], how="left")
    missing = units[units.vendor.isna()]
    if len(missing):
        print("gen4: GEM units without a vendor-map row (dropped):", file=sys.stderr)
        print(missing[["project", "unit", "model", "status"]].to_string(index=False), file=sys.stderr)
    units = units[units.include.str.lower().eq("yes")]
    rows = pd.DataFrame({
        "technology": "nuclear-gen4",
        "company": units.vendor,
        "project": units.project + " " + units.unit.astype(str),
        "country": units.country,
        "continent": units.apply(gem_continent, axis=1),
        "power_mw": units.capacity_mw,
        "status": units.status.map(cfg["gem_status"]),
        "online_year": units.start_year,
        "source_url": units.wiki_url,
        "note": "GEM Global Nuclear Power Tracker, Aug 2026 (" + units.status + ")",
    })
    # rows of projects.csv whose note starts with "CORRECTS GEM:" replace the GEM unit of the same name
    corr = projects[(projects.technology == "nuclear-gen4")
                    & projects.note.fillna("").str.startswith("CORRECTS GEM")]
    rows = rows[~rows.project.isin(corr.project)]
    return rows


def tidy_projects(cfg):
    p = read("projects.csv")
    gem = gen4_from_gem(cfg, p)
    p = pd.concat([p, gem], ignore_index=True)
    for c in ["power_mw", "energy_mwh", "duration_h", "online_year"]:
        p[c] = num(p[c])
    p["status"] = p.status.str.strip().str.lower()
    bad = p[~p.status.isin(LAYERS[:3])]
    if len(bad):
        raise ValueError(f"unknown status in projects: {bad.status.unique()}")
    # storage: fill power from energy / duration where only energy is given
    dur = {}
    for tech, spec in cfg["technologies"].items():
        sel = p.technology == tech
        if not spec.get("storage"):
            continue
        d = p.loc[sel, "duration_h"].fillna(p.loc[sel, "energy_mwh"] / p.loc[sel, "power_mw"])
        p.loc[sel, "duration_h"] = d
        both = sel & p.power_mw.notna() & p.duration_h.notna()
        dur[tech] = spec.get("duration_h") or float(
            (p.loc[both, "power_mw"] * p.loc[both, "duration_h"]).sum() / p.loc[both, "power_mw"].sum())
        nopow = sel & p.power_mw.isna() & p.energy_mwh.notna()
        p.loc[nopow, "power_mw"] = p.loc[nopow, "energy_mwh"] / p.loc[nopow, "duration_h"].fillna(dur[tech])
    p = p[p.technology.isin(cfg["technologies"])]
    # rows kept in the data for reference but outside the technology (conventional geothermal, research tests)
    drop = p.note.fillna("").str.upper().str.startswith(tuple(cfg["exclude_note_prefixes"]))
    p = p[~drop]
    nopow = p.power_mw.isna()
    if nopow.any():
        print(f"{nopow.sum()} project rows without capacity dropped:", file=sys.stderr)
        print(p.loc[nopow, ["technology", "company", "project"]].to_string(index=False), file=sys.stderr)
    p = p[~nopow].copy()
    # late projects: construction / announced with a past online year move to next year
    late = p.status.isin(["construction", "announced"]) & (p.online_year <= cfg["today"])
    p.loc[late, "online_year"] = cfg["today"] + 1
    # under construction without a stated year: next year (being built, date not reported)
    p.loc[(p.status == "construction") & p.online_year.isna(), "online_year"] = cfg["today"] + 1
    p.loc[(p.status == "operating") & p.online_year.isna(), "online_year"] = cfg["years"][0]
    return p, dur


def company_table(cfg, projects, targets):
    comp = read("companies.csv")
    comp = comp[comp.technology.isin(cfg["technologies"])].drop_duplicates(["technology", "company"])
    seen = pd.concat([projects[["technology", "company"]], targets[["technology", "company"]]]).drop_duplicates()
    extra = seen.merge(comp[["technology", "company"]], how="left", indicator=True)
    extra = extra[extra._merge == "left_only"].drop(columns="_merge")
    if len(extra):
        # continent of companies not described in companies.csv: where their MW go
        w = projects.groupby(["technology", "company", "continent"]).power_mw.sum().reset_index()
        w = w.sort_values("power_mw").drop_duplicates(["technology", "company"], keep="last")
        extra = extra.merge(w[["technology", "company", "continent"]], how="left")
        extra = extra.rename(columns={"continent": "main_continent"})
        extra["continent_basis"] = "largest MW share of its projects (not in companies.csv)"
        comp = pd.concat([comp, extra], ignore_index=True)
    return comp


def series(cfg, projects, targets, comp):
    y0, y1 = cfg["years"]
    years = np.arange(y0, y1 + 1)
    today = cfg["today"]
    out = []
    for (tech, company), grp in projects.groupby(["technology", "company"]):
        cum = {}
        for layer in LAYERS[:3]:
            g = grp[(grp.status == layer) & grp.online_year.notna()]
            cum[layer] = np.array([g.loc[g.online_year <= t, "power_mw"].sum() for t in years])
        base = cum["operating"] + cum["construction"] + cum["announced"]
        t_rows = targets[(targets.technology == tech) & (targets.company == company)]
        cum["target"], cum["factory"] = target_layers(years, base, t_rows, today, cfg["factory_until"])
        for layer in LAYERS + ["factory"]:
            out.append(pd.DataFrame({"technology": tech, "company": company, "layer": layer,
                                     "year": years, "mw": cum[layer]}))
    # companies with targets but no projects
    have = set(map(tuple, projects[["technology", "company"]].drop_duplicates().values))
    for (tech, company), t_rows in targets.groupby(["technology", "company"]):
        if (tech, company) in have:
            continue
        zero = np.zeros(len(years))
        tgt, fac = target_layers(years, zero, t_rows, today, cfg["factory_until"])
        for layer, v in zip(LAYERS + ["factory"], [zero, zero, zero, tgt, fac]):
            out.append(pd.DataFrame({"technology": tech, "company": company, "layer": layer, "year": years,
                                     "mw": v}))
    df = pd.concat(out, ignore_index=True)
    return df.merge(comp[["technology", "company", "main_continent"]], how="left").rename(
        columns={"main_continent": "continent"})


def target_layers(years, base, t_rows, today, factory_until):
    """target = stated deals and goals above the projects; factory = stated factories at nameplate above
    that (drawn as a ceiling line, not stacked: a factory says what could be made, not what is deployed)."""
    goals = t_rows[t_rows.kind.isin(["offtake", "corporate_goal"])]
    fac = t_rows[t_rows.kind == "factory_capacity"]
    env_goal = np.maximum.accumulate(np.maximum(base, envelope(years, base, goals, today, factory_until)))
    env_fac = np.maximum.accumulate(np.maximum(env_goal, envelope(years, base, fac, today, factory_until)))
    return env_goal - base, env_fac - env_goal


def envelope(years, base, t_rows, today, factory_until):
    """Largest of: each dated offtake deal or corporate goal (a straight line from today's project total to
    the stated MW at the stated year, flat afterwards; statements beyond the x-axis are cut at its end), and
    each stated factory run at nameplate. Statements are never summed: deals of one company overlap (an
    option inside a framework, a framework containing PPAs, a named project behind a deal), so the maximum
    is the conservative reading. Undated statements are listed in build/companies.csv only."""
    env = np.zeros(len(years))
    base_today = np.interp(today, years, base)
    goals = t_rows[t_rows.kind.isin(["offtake", "corporate_goal"])].dropna(subset=["year", "cumulative_mw"])
    goals = goals[goals.year > today].sort_values("year")
    for _, r in goals.iterrows():
        # straight line from today's project total to the stated cumulative value, flat afterwards
        line = np.interp(years, [today, r.year], [base_today, max(r.cumulative_mw, base_today)])
        env = np.maximum(env, np.where(years >= today, line, 0))
    for _, r in t_rows[t_rows.kind == "factory_capacity"].dropna(subset=["annual_mw"]).iterrows():
        # an undated capacity statement describes the factory as it is now: it runs from next year
        start = today + 1 if pd.isna(r.year) else max(r.year, today + 1)
        prior = np.interp(start - 1, years, base)
        n = np.clip(np.minimum(years, factory_until) - start + 1, 0, None)
        env = np.maximum(env, np.where(years >= start, prior + r.annual_mw * n, 0))
    return env


def rank(df, cfg, projects):
    """Colour rank by everything the company has on the table: its 2040 envelope incl. targets plus its
    announced projects without an online year (not drawn). The biggest areas get the colours; rank > top_n
    folds into the rest band."""
    last = df[(df.year == cfg["years"][1]) & (df.layer != "factory")]
    tot = last.groupby(["technology", "company"]).mw.sum().rename("total_2040_mw").to_frame()
    und = projects[projects.online_year.isna()].groupby(["technology", "company"]).power_mw.sum()
    tot["rank_score_mw"] = tot.total_2040_mw.add(und, fill_value=0)
    tot = tot.reset_index().sort_values(["technology", "rank_score_mw"], ascending=[True, False])
    tot["rank"] = tot.groupby("technology").cumcount() + 1
    return tot


def main():
    cfg = load_config()
    (HERE / "build").mkdir(exist_ok=True)
    projects, dur = tidy_projects(cfg)
    targets = read("targets.csv")
    targets = targets[targets.technology.isin(cfg["technologies"])].copy()
    for c in ["year", "cumulative_mw", "annual_mw"]:
        targets[c] = num(targets[c])
    nourl = pd.concat([projects[projects.source_url.isna()][["technology", "company", "project"]],
                       targets[targets.source_url.isna()][["technology", "company", "description"]]])
    if len(nourl):
        print("rows without source_url:\n" + nourl.to_string(index=False), file=sys.stderr)
    comp = company_table(cfg, projects, targets)
    df = series(cfg, projects, targets, comp)
    ranks = rank(df, cfg, projects)
    df = df.merge(ranks[["technology", "company", "rank"]], how="left")
    df.to_csv(HERE / "build/pipeline.csv", index=False)
    projects.to_csv(HERE / "build/projects_tidy.csv", index=False)

    # company table
    agg = projects.pivot_table(index=["technology", "company"], columns="status", values="power_mw",
                               aggfunc="sum", fill_value=0).reindex(columns=LAYERS[:3], fill_value=0)
    agg.columns = [f"{c}_mw" for c in agg.columns]
    und = projects[projects.online_year.isna()].groupby(["technology", "company"]).power_mw.sum()
    agg["undated_mw"] = und
    t_und = targets[targets.year.isna()]
    agg = agg.join(t_und.groupby(["technology", "company"]).cumulative_mw.max().rename("undated_target_max_mw"),
                   how="outer")
    agg = agg.join(targets.groupby(["technology", "company"]).description.apply(
        lambda s: " | ".join(s.dropna().str.slice(0, 120))).rename("targets"), how="outer")
    ct = comp.merge(ranks, how="right").merge(agg.reset_index(), how="left").fillna({"undated_mw": 0})
    for y in (2030, 2035, 2040):
        e = df[(df.year == y) & (df.layer != "factory")].groupby(["technology", "company"]).mw.sum().rename(f"envelope_{y}_mw")
        ct = ct.merge(e.reset_index(), how="left")
    f40 = df[(df.year == 2040) & (df.layer == "factory")].groupby(["technology", "company"]).mw.sum()
    ct = ct.merge(f40.rename("factory_ceiling_extra_2040_mw").reset_index(), how="left")
    ct.sort_values(["technology", "rank"]).to_csv(HERE / "build/companies.csv", index=False)

    # summary per tech and layer
    s = df[df.year.isin([2025, 2030, 2035, 2040])].groupby(["technology", "layer", "year"]).mw.sum() / 1e3
    s = s.unstack("year").reindex(pd.MultiIndex.from_product([list(cfg["technologies"]), LAYERS + ["factory"]]))
    s.columns = [f"gw_{c}" for c in s.columns]
    s = s.reset_index().rename(columns={"level_0": "technology", "level_1": "layer"})
    s["duration_h"] = s.technology.map(dur)
    s.to_csv(HERE / "build/summary.csv", index=False, float_format="%.3f")

    # cross-check against technology_assumptions.csv
    ta = pd.read_csv(HERE / cfg["technology_assumptions"]).set_index("technology")
    rows = []
    for tech in cfg["technologies"]:
        g = projects[projects.technology == tech]
        op25 = g[(g.status == "operating") & (g.online_year <= 2025)].power_mw.sum() / 1e3
        con = g[g.status == "construction"].power_mw.sum() / 1e3
        ex, pi = (ta.loc[tech, "existing_gw"], ta.loc[tech, "pipeline_gw"]) if tech in ta.index else (np.nan,) * 2
        rows.append(dict(technology=tech, operating_end2025_gw=op25, existing_gw_csv=ex,
                         construction_gw=con, pipeline_gw_csv=pi,
                         announced_gw=g[g.status == "announced"].power_mw.sum() / 1e3,
                         announced_undated_gw=g[(g.status == "announced") & g.online_year.isna()].power_mw.sum() / 1e3))
    cc = pd.DataFrame(rows)
    cc.to_csv(HERE / "build/crosscheck.csv", index=False, float_format="%.4f")
    print(cc.to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
