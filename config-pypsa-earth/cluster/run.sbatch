#!/usr/bin/env bash
# One Slurm job that runs config-pypsa-earth/run.sh with the given stages, one after the other (the same supervisor as
# on the laptop; no Snakemake profile, no job per rule). From the repo root on the cluster:
#   mkdir -p models/pypsa-earth/logs/catalyst
#   sbatch -A <account> config-pypsa-earth/cluster/run.sbatch USW-now USW-zero
#   tail -f models/pypsa-earth/logs/catalyst/status.log
# The values below are for the small 3-hourly screening solves (USW-now: peak 8.2 GB; the solves used 1.1 cores on
# average, so 4 cores; the solver takes its thread count from --cpus-per-task, see merge_config.py);
# override per call, e.g.  sbatch -A <account> --mem=60G --time=2-00:00:00 config-pypsa-earth/cluster/run.sbatch ...
# Billed: allocated physical cores x elapsed time, whatever the job uses, at 4.3 ct per core-hour (2026-11). Slurm
# counts hardware threads, two per core, so cost = CPUTimeRAW / 3600 / 2 x 4.3 ct
# (sacct -j <id> -X --format=JobID,Elapsed,AllocCPUS,CPUTimeRAW,State). MEMORY BUYS CORES: the first job (6299758, 4 cores
# and --mem=32G, 10 min) was allocated 22 CPUs = 11 cores, i.e. one core per 3 GB requested, and cost 8 ct. So --mem
# stays at 3 GB per requested core unless a stage needs more, and then every further 3 GB costs one more core.
#SBATCH --job-name=catalyst
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --threads-per-core=1
#SBATCH --mem=12G
#SBATCH --time=12:00:00
#SBATCH --output=models/pypsa-earth/logs/catalyst/slurm-%j.out
set -u
cd "${SLURM_SUBMIT_DIR:?submit with sbatch from the repo root}" || exit 1
[ -f config-pypsa-earth/run.sh ] || { echo "config-pypsa-earth/run.sh not found: submit from the repo root" >&2; exit 1; }
echo "job $SLURM_JOB_ID on $(hostname): ${SLURM_CPUS_PER_TASK:-?} cores, ${SLURM_MEM_PER_NODE:-?} MB, proxy ${https_proxy:-unset}, stages: $*"
exec bash config-pypsa-earth/run.sh "$@"
