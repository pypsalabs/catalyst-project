#!/usr/bin/env bash
# One Slurm job that runs config-pypsa-earth/run.sh with the given stages, one after the other (the same supervisor as
# on the laptop; no Snakemake profile, no job per rule). From the repo root on the cluster:
#   mkdir -p models/pypsa-earth/logs/catalyst
#   sbatch -A <account> config-pypsa-earth/cluster/run.sbatch USW-now USW-zero
#   tail -f models/pypsa-earth/logs/catalyst/status.log
# The values below are for the 3-hourly screening solves (laptop peak 20 GB; they used 1.1 cores on average, so 4 cores;
# the solver takes its thread count from --cpus-per-task, see merge_config.py);
# override per call, e.g.  sbatch -A <account> --mem=120G --time=2-00:00:00 config-pypsa-earth/cluster/run.sbatch ...
# Billed: cores x elapsed time, whatever the job uses (sacct -j <id> -X --format=JobID,Elapsed,AllocCPUS,CPUTimeRAW,State).
#SBATCH --job-name=catalyst
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --threads-per-core=1
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=models/pypsa-earth/logs/catalyst/slurm-%j.out
set -u
cd "${SLURM_SUBMIT_DIR:?submit with sbatch from the repo root}" || exit 1
[ -f config-pypsa-earth/run.sh ] || { echo "config-pypsa-earth/run.sh not found: submit from the repo root" >&2; exit 1; }
echo "job $SLURM_JOB_ID on $(hostname): ${SLURM_CPUS_PER_TASK:-?} cores, ${SLURM_MEM_PER_NODE:-?} MB, proxy ${https_proxy:-unset}, stages: $*"
exec bash config-pypsa-earth/run.sh "$@"
