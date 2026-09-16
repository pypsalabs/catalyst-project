#!/usr/bin/env python
"""Render parts of the land grid map page (land-grid-map/index.html) to PNG with headless Chrome.

The page has an export mode, ``?shot=map|archetypes|shares|tsne``, that shows only the requested part
(see the CSS block in index.html). This script opens it in headless Chrome, screenshots it and
crops: the map to its exact pixel size, the two legend blocks to their content. The kickoff deck's
Snakefile calls it so the slides pick up the current page on recompilation; it also runs standalone:

    python screenshot_map.py OUTDIR [NAME ...]        # names default to all of SHOTS

Needs google-chrome (or set CHROME=/path/to/chrome) and Pillow. The basemap tiles come from the
network; without it the map renders on a plain grey background but the script still succeeds.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image, ImageChops

PAGE = Path(__file__).resolve().parent / "land-grid-map" / "index.html"
LAYER = "clusters-v1"          # data version shown in the slides, pinned so a new default cannot change them
VIRTUAL_TIME_MS = 30000        # headless Chrome virtual time: enough for the population grid to decode
CHROME_CHROME_PX = 120         # window height lost to the (invisible) browser chrome in headless mode

# name -> how to render it. map: viewport of w x h CSS px at scale 1 (1767 x 651 as the slides expect,
# the .tex trims in px); the legend blocks are rendered at 2x for crisp text and trimmed to content.
SHOTS = {
    "map_screenshot": dict(shot="map", w=1767, h=651, scale=1, lat=10.5, lon=26, zoom=3),
    "archetypes": dict(shot="archetypes", w=400, h=1400, scale=2, trim=6),
    "shares": dict(shot="shares", w=400, h=1400, scale=2, trim=6),
    "tsne": dict(shot="tsne", w=1000, h=800, scale=2, trim=6),   # plot svg is 1000 x 760 plus the cluster key
}


def chrome_binary():
    for c in [os.environ.get("CHROME"), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
        if c and shutil.which(c):
            return shutil.which(c)
    sys.exit("no Chrome found: install google-chrome or set CHROME=/path/to/chrome")


def render(name, spec, out):
    params = {"shot": spec["shot"], "layer": LAYER, "w": spec["w"], "h": spec["h"]}
    for k in ("lat", "lon", "zoom"):
        if k in spec:
            params[k] = spec[k]
    url = PAGE.as_uri() + "?" + urlencode(params)
    with tempfile.TemporaryDirectory(prefix="shot-") as tmp:
        raw = Path(tmp) / "raw.png"
        cmd = [chrome_binary(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
               f"--user-data-dir={tmp}/profile",
               f"--window-size={spec['w']},{spec['h'] + CHROME_CHROME_PX}",
               f"--force-device-scale-factor={spec['scale']}",
               f"--virtual-time-budget={VIRTUAL_TIME_MS}",
               f"--screenshot={raw}", url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if not raw.exists():
            sys.exit(f"{name}: Chrome produced no screenshot\n{r.stderr[-2000:]}")
        im = Image.open(raw).convert("RGB")
    s = spec["scale"]
    if spec.get("trim"):
        # crop to the non-white content plus a margin
        bg = Image.new("RGB", im.size, (255, 255, 255))
        mask = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 8 else 0)
        box = mask.getbbox()
        if not box:
            sys.exit(f"{name}: screenshot is blank")
        pad = spec["trim"] * s
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad))
    else:
        box = (0, 0, spec["w"] * s, spec["h"] * s)
    im = im.crop(box)
    im.save(out, optimize=True)
    print(f"{out}: {im.width} x {im.height} px")


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    names = argv[2:] or list(SHOTS)
    for name in names:
        if name not in SHOTS:
            sys.exit(f"unknown shot {name!r}; known: {', '.join(SHOTS)}")
        render(name, SHOTS[name], outdir / f"{name}.png")


if __name__ == "__main__":
    main(sys.argv)
