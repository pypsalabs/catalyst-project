"""Download and parse the open Schmidt et al. experience-curve dataset.

Schmidt, Hawkes, Gambhir & Staffell, "The future cost of electrical energy
storage based on experience rates", Nature Energy 2 (2017) 17110,
doi:10.1038/nenergy.2017.110; dataset update of 27 Aug 2018 (figshare 7012202,
CC BY 4.0). The xlsx is cached under data/learning/ and committed; the
download is skipped when it is present (as for technology-data).

The "Data" sheet holds 17 blocks. Each block: a title row in column B
("Vanadium redox-flow (Utility, 13±3%)"), a header row (Year | Cum GWh |
USD2015/kWh | Cum GW | USD2015/kW; some blocks carry only one pair), data rows,
and a "Data Source" row whose [n] references sit under the pair that was
actually collected. The other pair is that series times a constant
energy-to-power ratio in hours (USD/kW = USD/kWh x h; the regression
parameters in H:J are identical for both), so it is
NOT independent data: it is written with `derived = True` and is only ever
drawn as context, never fitted. The published regression parameters (A, b, σ,
ER) are written to a second file and used as a cross-check of our own fit.

No xlsx library is available in the environment; the file is read with the
standard library (zipfile + ElementTree).

Outputs
  data/learning/schmidt2018.xlsx            cached download
  data/learning/schmidt2018.csv             observations in the common schema
  data/learning/schmidt2018_published.csv   block, series, component, A, b, sigma, ER, n

Run standalone:  python retrieve_schmidt.py
"""

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

if "snakemake" in globals():
    CFG = snakemake.config
    XLSX = Path(snakemake.output.xlsx)
    OUT_CSV = Path(snakemake.output.csv)
    OUT_PUB = Path(snakemake.output.published)
    URL = snakemake.params.url
else:
    _HERE = Path(__file__).parent
    CFG = yaml.safe_load((_HERE / "config.yaml").read_text())
    XLSX = _HERE / "data" / "learning" / "schmidt2018.xlsx"
    OUT_CSV = _HERE / "data" / "learning" / "schmidt2018.csv"
    OUT_PUB = _HERE / "data" / "learning" / "schmidt2018_published.csv"
    URL = CFG["learning"]["schmidt"]["url"]
XLSX.parent.mkdir(parents=True, exist_ok=True)

MAP = CFG["learning"]["schmidt_map"]
COLUMNS = ["technology", "component", "year", "value", "unit", "currency", "currency_year",
           "capacity", "capacity_unit", "scope", "series", "derived", "context", "source", "url", "note"]
CITATION = "Schmidt, Hawkes, Gambhir & Staffell, Nat. Energy 2017, dataset update 2018 (figshare 7012202)"
DOI_URL = "https://doi.org/" + CFG["learning"]["schmidt"]["doi"]

# --- download -------------------------------------------------------------------------

if XLSX.exists() and XLSX.stat().st_size > 0:
    print(f"{XLSX} present, skipping download")
else:
    r = requests.get(URL, timeout=120, allow_redirects=True)
    r.raise_for_status()
    assert r.content[:4] == b"PK\x03\x04", f"{URL} did not return an xlsx (zip) file"
    XLSX.write_bytes(r.content)
    print(f"downloaded {URL} -> {XLSX} ({len(r.content) / 1e6:.1f} MB)")

# --- minimal xlsx reader ----------------------------------------------------------------

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def read_sheet(z, name):
    """Rows of sheet `name` as {column letter: value}; strings resolved, numbers as float."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    target = None
    for s in wb.find("m:sheets", NS):
        if s.get("name") == name:
            target = rels[s.get(f"{{{NS['r']}}}id")]
    assert target, f"sheet {name!r} not found"
    target = target if target.startswith("xl/") else "xl/" + target
    shared = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    rows = []
    for row in ET.fromstring(z.read(target)).iter(f"{{{NS['m']}}}row"):
        d = {}
        for c in row.findall("m:c", NS):
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            v = c.find("m:v", NS)
            if c.get("t") == "s" and v is not None:
                d[col] = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                d[col] = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
            elif v is not None:
                try:
                    d[col] = float(v.text)
                except ValueError:
                    d[col] = v.text
        if d:
            rows.append(d)
    return rows


# --- parse ---------------------------------------------------------------------------------

z = zipfile.ZipFile(XLSX)
data = read_sheet(z, "Data")
sources = {}
for d in read_sheet(z, "Data Sources"):
    m = re.fullmatch(r"\[(\d+)\]\s*", str(d.get("B", "")))
    if m and "C" in d:
        sources[int(m.group(1))] = str(d["C"]).strip()


def expand_refs(text):
    """'[2] - [5]' -> [2, 3, 4, 5]; '[7], [8], [38]' -> [7, 8, 38]."""
    text = str(text)
    out = []
    for a, b in re.findall(r"\[(\d+)\]\s*-\s*\[(\d+)\]", text):
        out.extend(range(int(a), int(b) + 1))
    text = re.sub(r"\[(\d+)\]\s*-\s*\[(\d+)\]", "", text)
    out.extend(int(n) for n in re.findall(r"\[(\d+)\]", text))
    return sorted(set(out))


def cite(nums):
    missing = [n for n in nums if n not in sources]
    assert not missing, f"unresolved data-source references {missing}"
    return "; ".join(f"[{n}] {sources[n]}" for n in nums)


def slug(title):
    """'Lithium-ion (EV, 19±5%)' -> 'lithium-ion-ev-19'; the rate keeps same-named blocks apart."""
    head, _, rate = title.partition(",")
    rate = re.sub(r"[^0-9-]", "", rate.split("±")[0])
    return re.sub(r"[^a-z0-9]+", "-", f"{head} {rate}".lower()).strip("-")


PAIRS = {"energy": ("C", "D", "GWh", "USD/kWh"), "power": ("E", "F", "GW", "USD/kW")}
PARAM_COL = {"energy": "I", "power": "J"}

blocks = []
i = 0
while i < len(data):
    d = data[i]
    title = d.get("B")
    is_title = (isinstance(title, str) and "(" in title and i + 1 < len(data)
                and data[i + 1].get("B") == "Year")
    if not is_title:
        i += 1
        continue
    header = data[i + 1]
    pairs = {k: v for k, v in PAIRS.items() if header.get(v[0]) and header.get(v[1])}
    obs, params, source_row, dropped = [], {}, None, 0
    if header.get("H") == "A":            # the 'A' parameter shares the header row
        params["A"] = {k: header.get(PARAM_COL[k]) for k in pairs}
    j = i + 2
    while j < len(data) and data[j].get("B") != "Data Source":
        row = data[j]
        if isinstance(row.get("B"), float):
            obs.append(row)
        elif row.get("B") is not None:
            dropped += 1
            print(f"  {title}: skipping row with year {row.get('B')!r}")
        if row.get("H") in ("A", "b", "σ", "ER"):
            params[row["H"]] = {k: row.get(PARAM_COL[k]) for k in pairs}
        j += 1
    assert j < len(data), f"no 'Data Source' row for block {title!r}"
    source_row = data[j]
    blocks.append({"title": title, "pairs": pairs, "obs": obs, "params": params,
                   "source_row": source_row, "dropped": dropped})
    i = j + 1

assert len(blocks) == 17, f"expected 17 blocks, found {len(blocks)}"

records, published = [], []
for blk in blocks:
    title, pairs = blk["title"], blk["pairs"]
    native = [k for k, (ccol, vcol, *_) in pairs.items()
              if blk["source_row"].get(ccol) or blk["source_row"].get(vcol)]
    assert len(native) == 1, f"{title}: cannot identify the collected series from the Data Source row"
    native = native[0]
    cap_refs = expand_refs(blk["source_row"].get(pairs[native][0], ""))
    price_refs = expand_refs(blk["source_row"].get(pairs[native][1], ""))
    mapping = next((v for k, v in MAP.items() if title.startswith(k)), {})
    tech = mapping.get("technology", "")
    series = f"schmidt2018:{slug(title)}"
    # a constant C-rate between the pairs means the second pair is derived, not measured
    if len(pairs) == 2:
        ratio = np.array([r["F"] / r["D"] for r in blk["obs"] if r.get("D") and r.get("F")])
        derived_note = (f"derived from the {native} series with a constant energy-to-power ratio "
                        f"({np.mean(ratio):.3g} h, i.e. USD/kW = USD/kWh x {np.mean(ratio):.3g}); not independent data")
        assert ratio.std() / ratio.mean() < 1e-6, f"{title}: pairs are not a constant multiple"
    for comp, (ccol, vcol, cunit, vunit) in pairs.items():
        is_native = comp == native
        if "component" in mapping and not is_native:
            continue                      # only the collected series enters the palette component
        component = mapping.get("component", comp) if is_native else comp
        note = f"{title}. " + (f"capacity: {cite(cap_refs)}. price: {cite(price_refs)}"
                               if is_native else derived_note)
        if mapping.get("note"):
            note = mapping["note"] + ". " + note
        for r in blk["obs"]:
            if r.get(ccol) is None or r.get(vcol) is None:
                continue
            records.append({
                "technology": tech, "component": component, "year": int(r["B"]),
                "value": r[vcol], "unit": vunit, "currency": "USD", "currency_year": 2015,
                "capacity": r[ccol], "capacity_unit": cunit, "scope": mapping.get("scope", ""),
                "series": series, "derived": not is_native, "context": bool(mapping.get("context", False)),
                "source": CITATION,
                "url": DOI_URL, "note": note,
            })
        p = blk["params"]
        if p.get("b", {}).get(comp) is not None:
            published.append({
                "block": title, "series": series, "component": component, "native": is_native,
                "A": p["A"][comp], "b": p["b"][comp], "sigma": p["σ"][comp], "ER": p["ER"][comp],
                "n": sum(1 for r in blk["obs"] if r.get(ccol) is not None and r.get(vcol) is not None),
                "rows_dropped": blk["dropped"],
            })

obs = pd.DataFrame.from_records(records, columns=COLUMNS)
pub = pd.DataFrame.from_records(published)
obs.to_csv(OUT_CSV, index=False)
pub.to_csv(OUT_PUB, index=False)

# --- cross-check: our log-log slope must reproduce the published b ------------------------

print(f"{len(blocks)} blocks, {len(obs)} observations ({obs['derived'].sum()} derived), "
      f"{obs['technology'].ne('').sum()} mapped to the palette")
bad = []
for _, p in pub[pub["native"]].iterrows():
    s = obs[(obs["series"] == p["series"]) & (~obs["derived"])]
    if len(s) < 2:
        continue
    b = -np.polyfit(np.log(s["capacity"]), np.log(s["value"]), 1)[0]
    if p["rows_dropped"]:
        flag = f"  (published fit used {p['rows_dropped']} more rows without a year; not compared)"
    else:
        flag = "" if abs(b - p["b"]) < 1e-3 else "  <-- MISMATCH"
    if "MISMATCH" in flag:
        bad.append(p["block"])
    print(f"  {p['block']:<40} n={len(s):>2}  b_ours={b:.4f}  b_published={p['b']:.4f}  ER={p['ER']}{flag}")
assert not bad, f"published slope not reproduced for {bad}"
