#!/usr/bin/env bash
# Read-only probe of a cluster login node: answers the open questions before the pypsa-earth fork is moved there.
#   ssh z3 'bash -s' < config-pypsa-earth/cluster/probe.sh | tee z3-probe.txt
# Writes nothing, submits no job. The one question it cannot answer (internet on the compute nodes) needs a job:
#   srun -n1 -t 2 curl -sI -m 20 https://raw.githubusercontent.com | head -1
h() { echo; echo "==== $* ===="; }
have() { command -v "$1" >/dev/null 2>&1; }

h host; hostname -f; grep -E "^(PRETTY_NAME)=" /etc/os-release; uname -r; ldd --version 2>&1 | head -1
echo "cores $(nproc), RAM $(awk '/MemTotal/ {printf "%d GB", $2/1048576}' /proc/meminfo)"

h scheduler
for c in sbatch qsub bsub condor_submit; do have $c && echo "found $c: $(command -v $c)"; done
if have sinfo; then
  sinfo -o "%P %a %l %D %c %m %G" 2>&1 | head -30                       # partition, time limit, nodes, cores, MB, gres
  scontrol show config 2>/dev/null | grep -E "^(SelectTypeParameters|TaskPlugin|ProctrackType|JobAcctGatherType|DefMemPerCPU|MaxMemPerNode|MaxArraySize|MaxJobCount)"
  sacctmgr -nP show assoc user="$USER" format=account,partition,qos,maxjobs,maxsubmit,grptres 2>&1 | head
  squeue -u "$USER" 2>&1 | head -5
fi

h storage
df -h "$HOME" 2>&1 | tail -1
for d in /scratch /scratch/"$USER" /work /work/"$USER" /data /data/"$USER" /nfs /local /tmp "${TMPDIR:-}"; do
  [ -n "$d" ] && [ -d "$d" ] && { printf "%-22s " "$d"; df -h "$d" 2>/dev/null | tail -1 | awk '{print $2, "total,", $4, "free,", $1}'; [ -w "$d" ] && echo "    writable"; }
done
quota -s 2>&1 | head -8
have lfs && lfs quota -h -u "$USER" "$HOME" 2>&1 | head -5
echo "home in use: $(du -sh "$HOME" 2>/dev/null | cut -f1)"

h "internet from the login node"
for u in https://raw.githubusercontent.com https://conda.anaconda.org/conda-forge/noarch/repodata.json https://github.com https://zenodo.org https://download.geofabrik.de https://pixi.sh; do
  printf "%-70s %s\n" "$u" "$(curl -sI -m 15 -o /dev/null -w '%{http_code}' "$u" 2>&1)"
done
env | grep -i -E "^(https?|no)_proxy=" || echo "no proxy variables"

h "solver / gurobi"
echo "GRB_LICENSE_FILE=${GRB_LICENSE_FILE:-unset} GUROBI_HOME=${GUROBI_HOME:-unset}"
ls -d /opt/gurobi* /sw/*/gurobi* /usr/local/gurobi* 2>/dev/null
ls -la "$HOME/gurobi.lic" /opt/gurobi/gurobi.lic 2>/dev/null
for f in "${GRB_LICENSE_FILE:-}" "$HOME/gurobi.lic" /opt/gurobi/gurobi.lic; do   # licence type and server only, never the key
  [ -n "$f" ] && [ -r "$f" ] && { echo "$f:"; grep -E "^(TYPE|VERSION|TOKENSERVER|PORT|EXPIRATION|HOSTNAME)=" "$f"; }
done
have gurobi_cl && gurobi_cl --version
if type module >/dev/null 2>&1; then module avail 2>&1 | grep -i -E "gurobi|cplex|highs|conda|mamba|pixi|osmium|python" | head -20; else echo "no environment modules"; fi

h tools
for c in git rsync wget curl tmux screen pixi micromamba conda mamba osmium unzip systemd-run python3; do
  printf "%-12s %s\n" "$c" "$(command -v $c 2>/dev/null || echo -)"
done
git --version 2>/dev/null; rsync --version 2>/dev/null | head -1

h "memory cap mechanism"
echo "cgroup fs: $(stat -fc %T /sys/fs/cgroup 2>/dev/null)   (cgroup2fs = v2)"
echo "own cgroup: $(cut -d: -f3 /proc/self/cgroup | tail -1)"
systemctl --user is-system-running 2>&1 | head -1
loginctl show-user "$USER" -p Linger 2>&1 | head -1
ulimit -a | grep -E "max memory|virtual memory|open files|max user processes"

h "github through the forwarded agent"
ssh-add -l 2>&1 | head -3
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 | head -1
