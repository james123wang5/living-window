#!/bin/bash
# NTU CCDS GPU Cluster TC2：在 A40 计算节点上启动 Daydream Scope（预加载 LongLive）。
# 提交：sbatch run_scope_job.sh；节点名与端口见 output_ScopeLongLive_<jobid>.out。
# 注意：Scope 登记管线时会跳过“需要显存但没检测到 GPU”的管线，所以必须在 GPU 节点上跑，头节点上看不到 longlive。
# 没有构建前端（集群无 Node），第一轮用无界面 HTTP 接口测试，不依赖浏览器/WebRTC。
#SBATCH --partition=MGPU-TC2
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=10
#SBATCH --time=02:00:00
#SBATCH --mem=30G
#SBATCH --job-name=ScopeLongLive
#SBATCH --output=output_%x_%j.out
#SBATCH --error=error_%x_%j.err

export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/scope" || exit 1

echo "节点: $SLURMD_NODENAME  作业: $SLURM_JOB_ID  开始: $(date)"
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv

# 每 30 秒记录一次显存，方便事后查峰值
( while true; do
    echo "$(date +%T) $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader)" >> "$HOME/gpu_usage_$SLURM_JOB_ID.log"
    sleep 30
  done ) &
MON_PID=$!
trap 'kill $MON_PID 2>/dev/null' EXIT

# 监听所有网卡，便于从头节点经 SSH 隧道访问；端口 8000 此前确认为空闲
PIPELINE=longlive uv run daydream-scope --host 0.0.0.0 --port 8000
