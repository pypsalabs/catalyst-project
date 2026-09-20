# SPDX-License-Identifier: CC0-1.0
# Catalyst validation rules for the pypsa-earth fork. Included through the fork's `custom_rules` config
# key (path relative to the fork root: ../../config-pypsa-earth/validation.smk), so the fork's Snakefile
# stays untouched; RDIR comes from the fork's Snakefile namespace. Script paths are relative to this file.
#
#   retrieve_validation_data   Ember yearly data + European prices, ECB annual FX -> config-pypsa-earth/data/validation/
#   build_validation_points    Ember, IRENA, EI Statistical Review, ECB, manual_points.csv -> resources/catalyst/validation_points.csv
#   plot_validation       one 16:9 dashboard per solved network (results/<run>/plots/validation_<stem>.png)
#   validation_dashboard  one 16:9 page per region, left <R>-now, right <R>-zero (results/catalyst/validation_<R>.png)
import os

import yaml

CATALYST_CFG = "../../config-pypsa-earth"   # relative to the fork root (Snakemake's working directory)
VALDATA = CATALYST_CFG + "/data/validation"
EMBER_URL = "https://storage.googleapis.com/emb-prod-bkt-publicdata/public-downloads/"
ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/A.USD+GBP+BRL+INR+SGD.EUR.SP00.A?format=csvdata&startPeriod=2015"


def _catalyst_yaml(name):
    with open(os.path.join(CATALYST_CFG, name)) as f:
        return yaml.safe_load(f)


def _scenario_network(region, scen):
    """Solved network of stage <region>-<scen> as run.sh builds it (first entry of every scenario list)."""
    base = _catalyst_yaml(f"config.{region}.yaml")["scenario"]
    over = _catalyst_yaml(f"overlay.{scen}.yaml")["scenario"]
    sc = {**base, **over}
    stem = "elec_s{}_{}_ec_l{}_{}".format(sc["simpl"][0], sc["clusters"][0], sc["ll"][0], sc["opts"][0])
    return f"results/{region}-{scen}/networks/{stem}.nc"


rule retrieve_validation_data:
    output:
        ember=VALDATA + "/yearly_full_release_long_format.csv",
        prices=VALDATA + "/european_wholesale_electricity_price_data_monthly.csv",
        fx=VALDATA + "/ecb_fx_annual.csv",
    log:
        "logs/catalyst/retrieve_validation_data.log",
    resources:
        mem_mb=500,
    shell:
        """
        curl -sSL --fail -m 900 -o {output.ember} {EMBER_URL}yearly_full_release_long_format.csv 2>> {log}
        curl -sSL --fail -m 300 -o {output.prices} {EMBER_URL}european_wholesale_electricity_price_data_monthly.csv 2>> {log}
        curl -sSL --fail -m 120 -o {output.fx} '{ECB_URL}' 2>> {log}
        """


rule build_validation_points:
    input:
        ember=VALDATA + "/yearly_full_release_long_format.csv",
        prices=VALDATA + "/european_wholesale_electricity_price_data_monthly.csv",
        fx=VALDATA + "/ecb_fx_annual.csv",
        irena="data/IRENA_Statistics_Extract_2025H2.xlsx",
        ei=VALDATA + "/EI-Stats-Review-ALL-data-2025.xlsx",        # browser download, kept in the repo (see README)
        manual=VALDATA + "/manual_points.csv",
        configs=[CATALYST_CFG + f"/config.{r}.yaml" for r in ("US", "BR", "IN", "SG", "NWE")],
    output:
        "resources/catalyst/validation_points.csv",
    log:
        "logs/catalyst/build_validation_points.log",
    resources:
        mem_mb=2000,
    script:
        "scripts/build_validation.py"


rule plot_validation:
    input:
        network="results/" + RDIR + "networks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc",
        points="resources/catalyst/validation_points.csv",
    output:
        "results/" + RDIR + "plots/validation_elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.png",
    log:
        "logs/" + RDIR + "plot_validation_elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.log",
    threads: 1
    resources:
        mem_mb=4000,
    script:
        "scripts/plot_validation.py"


rule validation_dashboard:
    input:
        now=lambda w: _scenario_network(w.region, "now"),
        zero=lambda w: _scenario_network(w.region, "zero"),
        points="resources/catalyst/validation_points.csv",
    output:
        "results/catalyst/validation_{region}.png",
    log:
        "logs/catalyst/validation_dashboard_{region}.log",
    threads: 1
    resources:
        mem_mb=6000,
    script:
        "scripts/plot_validation.py"
