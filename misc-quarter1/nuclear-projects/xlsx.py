"""Minimal xlsx reader (standard library only; the pixi env has no openpyxl).

Unlike ../geothermal/build_hydro.py::read_xlsx it places every value by its
cell reference, so empty cells do not shift the row.
"""

import re
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheet(path, sheet, header=0):
    """Return one sheet as a DataFrame of strings ('' for empty cells)."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.find("m:sheets", NS)]
    files = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)),
                   key=lambda n: int(re.findall(r"\d+", n)[0]))
    f = dict(zip(names, files))[sheet]
    rows = []
    for row in ET.fromstring(z.read(f)).iter("{%s}row" % NS["m"]):
        vals = {}
        for c in row.findall("m:c", NS):
            v = c.find("m:v", NS)
            val = v.text if v is not None else ""
            if c.get("t") == "s" and val:
                val = shared[int(val)]
            elif c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
            vals[_col(c.get("r"))] = val
        rows.append(vals)
    width = max(max(r) for r in rows if r) + 1
    table = [[r.get(i, "") for i in range(width)] for r in rows]
    df = pd.DataFrame(table[header + 1:], columns=table[header])
    return df.loc[:, [c for c in df.columns if c != ""]]
