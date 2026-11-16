"""The options the document quotes, cut out of the config files as YAML code blocks (build/yaml/<name>.yaml).

A fourth entry of a snippet part names a block of which only some keys are shown: the block's other keys are listed
in a closing comment, with the attributes each sets under `existing` (read from the file, like everything else).

Each snippet names config files of config-pypsa-earth/ and key paths in them; the keys are read from the file (so the
document shows what the model reads) and written as a small YAML block under a comment line with the file name.
`same` lists further files that must hold the same values (checked; named in the comment line). The options are
switches; TABLES names, per snippet, the table the rule then reads (resources/<run>/statistics/<name>.csv) and the
file of config-pypsa-earth/ that ../tables.smk copies there, as closing comment lines (the source must exist).
doc/main.tex: \\yamlblock{<name>}.

Standalone (from config-pypsa-earth/model-doc):
    ../../models/priam-myopic/.pixi/envs/default/bin/python scripts/yaml_snippets.py
"""

import argparse
from pathlib import Path

import yaml

TOP = Path(__file__).resolve().parents[1]
CONFIGS = TOP.parent
PREFIX = "../../config-pypsa-earth/"
ENVELOPE = [("electricity", "nuclear_p_max_pu"), ("electricity", "must_run_cap"), ("conventional", "nuclear"),
            ("conventional", "coal")]
REGIONS = ["config.US.yaml", "config.BR.yaml", "config.IN.yaml", "config.CN.yaml"]

# name -> [(file, [key paths], files that must agree)]
SNIPPETS = {
    "gas_mapping": [("statistics.yaml", [("electricity", "gas_technology_mapping")], [])],
    "plant_statistics": [("statistics.yaml", [("electricity", "powerplants_statistics")], [])],
    "plant_efficiency": [("statistics.yaml", [("electricity", "powerplants_efficiency")], [])],
    "envelope": [("statistics.yaml", ENVELOPE, [], ("conventional",))],   # the other carriers named in a comment
    "tranches": [("statistics.yaml", [("calibration", "efficiency_spread"), ("calibration", "tranches")], [])],
    "retirements": [("overlay.myopic.yaml", [("electricity", "powerplants_lifetimes"),
                                             ("electricity", "powerplants_filter")], [])],
    "drop_duplicate_ids": [("config.NWE.yaml", [("osm", "clean_osm_data", "drop_duplicate_ids")], REGIONS)],
    "fix_indirect_circuits": [("config.NWE.yaml", [("osm", "clean_osm_data", "fix_indirect_circuits")], REGIONS)],
    "geodesic_length": [("config.NWE.yaml", [("osm", "build_osm_network", "geodesic_length")], REGIONS)],
    "dc_ratings": [("statistics.yaml", [("links", "dc_ratings")], [])],
    "dc_projects": [("config.NWE.yaml", [("links", "dc_projects")], REGIONS)],
    "isolated": [("config.NWE.yaml", [("cluster_options", "simplify_network", "p_threshold_merge_isolated"),
                                      ("cluster_options", "simplify_network", "s_threshold_fetch_isolated")],
                  ["config.IN.yaml", "config.CN.yaml"])],
}


# snippet -> [(table of resources/<run>/statistics/, its source in config-pypsa-earth/ as wired in ../tables.smk)]
TABLES = {
    "plant_statistics": [("capacity.csv", "calibration/2024/capacity.csv")],
    "plant_efficiency": [("efficiency.csv", "calibration/2024/efficiency.csv")],
    "envelope": [("conventional_<carrier>_<attr>.csv", "calibration/2024/envelope/floor/<carrier>_<attr>.csv")],
    "dc_ratings": [("dc_ratings.csv", "data/hvdc/hvdc_ratings.csv")],
    "dc_projects": [("dc_projects.csv", "data/hvdc/hvdc_project_table.csv")],
}


def pick(cfg, paths, fn):
    out = {}
    for path in paths:
        src, dst = cfg, out
        for key in path[:-1]:
            src, dst = src[key], dst.setdefault(key, {})
        assert path[-1] in src, f"{fn}: no key {': '.join(path)}"
        dst[path[-1]] = src[path[-1]]
    return out


def strip(obj):
    """Table paths without the prefix of the config directory; returns (object, whether anything was stripped)."""
    if isinstance(obj, dict):
        parts = {k: strip(v) for k, v in obj.items()}
        return {k: v for k, (v, _) in parts.items()}, any(s for _, s in parts.values())
    if isinstance(obj, str) and obj.startswith(PREFIX):
        return obj[len(PREFIX):], True
    return obj, False


def render(parts, configs, tables=()):
    blocks = []
    for fn, paths, same, *elided in parts:
        cfg = yaml.safe_load((configs / fn).read_text())
        sub = pick(cfg, paths, fn)
        for other in same:
            assert pick(yaml.safe_load((configs / other).read_text()), paths, other) == sub, f"{other} differs from {fn}"
        sub, stripped = strip(sub)
        note = [f"the same in {', '.join(same)}"] if same else []
        note += ["paths relative to config-pypsa-earth/"] if stripped else []
        head = f"# {fn}" + (f" ({'; '.join(note)})" if note else "")
        text = head + "\n" + yaml.safe_dump(sub, sort_keys=False, default_flow_style=False, width=1000).rstrip()
        for block in elided:
            full, shown = cfg, sub
            for key in block:
                full, shown = full[key], shown[key]
            rest = [f"{k} ({', '.join(v['existing'])})" for k, v in full.items() if k not in shown]
            text += f"\n  # likewise: {', '.join(rest)}"
        blocks.append(text)
    text = "\n\n".join(blocks)
    for table, source in tables:
        probe = source.replace("<carrier>_<attr>", "coal_p_max_pu")
        assert (configs / probe).exists(), f"{source}: no such table"
        text += f"\n# table statistics/{table} = {source}"
    return text + "\n"


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--configs", default=CONFIGS)
    p.add_argument("--out", default=TOP / "build/yaml")
    if "snakemake" in globals():
        a = p.parse_args(["--configs", snakemake.params.configs, "--out", str(Path(snakemake.output[0]).parent)])
    else:
        a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, parts in SNIPPETS.items():
        (out / f"{name}.yaml").write_text(render(parts, Path(a.configs), TABLES.get(name, ())))
    print(f"-> {out} ({len(SNIPPETS)} snippets)")


if __name__ == "__main__" or "snakemake" in globals():
    main()
