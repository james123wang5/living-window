#!/bin/bash
# NTU CCDS GPU Cluster TC2：在计算节点上运行只读的环境检查。
# 提交：sbatch check_gpu_job.sh（需和 check_server.sh 放在家目录同一位置）
# 参数格式依据《CCDSGPU-TC2-Masters-UserGuide》：必须带 partition/qos/gres/time/mem/job-name/output/error。
#SBATCH --partition=MGPU-TC2
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --time=00:10:00
#SBATCH --mem=4G
#SBATCH --job-name=GpuCheck
#SBATCH --output=output_%x_%j.out
#SBATCH --error=error_%x_%j.err

echo "===== Slurm 作业信息 ====="
echo "节点: $SLURMD_NODENAME"
echo "作业ID: $SLURM_JOB_ID"
scontrol show node "$SLURMD_NODENAME"

echo
echo "===== module 环境 ====="
module load cuda/12.8.0 2>&1 || echo "cuda/12.8.0 加载失败"
module list 2>&1
module avail 2>&1 | head -n 60

bash "$HOME/check_server.sh"
