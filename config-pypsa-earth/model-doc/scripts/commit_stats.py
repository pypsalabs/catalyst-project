"""Lines added and removed per fork commit cited in the document, as GitHub shows them (+X -Y over all files).

Scans the sections for \\commit{<hash>}, asks the fork's git (`git show --shortstat`) and writes one
\\commitstat{<hash>}{<added>}{<removed>} per commit; \\commit (doc/main.tex) prints the numbers after the hash.
A hash the fork does not know is skipped with a warning (the link then has no numbers).

Standalone (from config-pypsa-earth/model-doc):
    python3 scripts/commit_stats.py
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

TOP = Path(__file__).resolve().parents[1]
FORK = TOP.parent.parent / "models/pypsa-earth"


def stat(repo, sha):
    out = subprocess.run(["git", "-C", str(repo), "show", "--shortstat", "--format=", sha],
                         capture_output=True, text=True)
    if out.returncode:
        return None
    add = re.search(r"(\d+) insertion", out.stdout)
    rem = re.search(r"(\d+) deletion", out.stdout)
    return int(add.group(1)) if add else 0, int(rem.group(1)) if rem else 0


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--sections", nargs="*", default=sorted((TOP / "doc/sections").glob("*.tex")))
    p.add_argument("--repo", default=FORK)
    p.add_argument("--out", default=TOP / "build/commit_stats.tex")
    if "snakemake" in globals():
        a = p.parse_args(["--sections", *snakemake.input.sections, "--repo", snakemake.params.repo,
                          "--out", snakemake.output[0]])
    else:
        a = p.parse_args()

    shas = sorted({m for f in a.sections for m in re.findall(r"\\commit\{([0-9a-f]+)\}", Path(f).read_text())})
    lines = ["% written by scripts/commit_stats.py: lines added / removed per cited fork commit (git show --shortstat)"]
    for sha in shas:
        s = stat(a.repo, sha)
        if s is None:
            print(f"warning: {sha} not in {a.repo}", file=sys.stderr)
            continue
        lines.append(f"\\commitstat{{{sha}}}{{{s[0]:,}}}{{{s[1]:,}}}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"-> {a.out} ({len(lines) - 1} commits)")


if __name__ == "__main__" or "snakemake" in globals():
    main()
