#!/usr/bin/env bash
# 只读检查：收集 A40 服务器的配置，用于判断能否运行 Daydream Scope。
# 不安装、不修改任何东西。
# 集群版用法：不要在 head node 直接运行（那里没有 GPU）；先 scp 到家目录，
# 再用 check_gpu_job.sh 通过 sbatch 在计算节点上运行。详见 技术选型-虚拟窗景.md §0。

section() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@" 2>&1 || echo "(失败或不可用: $*)"; }
has() { command -v "$1" >/dev/null 2>&1; }

section "基本信息"
run hostname
run whoami
run id
run date
run uname -a
[ -f /etc/os-release ] && run cat /etc/os-release

section "CPU / 内存 / 磁盘"
run nproc
run free -h
run df -h "$HOME"
run ulimit -a

section "GPU 概览（驱动、CUDA 上限、显存、占用）"
if has nvidia-smi; then
  run nvidia-smi
  run nvidia-smi -L
  run nvidia-smi --query-gpu=index,name,memory.total,memory.used,driver_version,compute_cap --format=csv
  section "GPU 互联（两张卡之间是否有 NVLink）"
  run nvidia-smi topo -m
  section "当前占用 GPU 的进程（别人是否在用）"
  run nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
else
  echo "未找到 nvidia-smi：当前不是 GPU 节点，或驱动不可用"
fi

section "CUDA 工具链"
has nvcc && run nvcc --version || echo "未找到 nvcc（只用 PyTorch 预编译包时可以没有）"

section "软件环境"
for c in python3 pip3 uv git docker node npm tmux screen ffmpeg; do
  if has "$c"; then printf '%s: ' "$c"; "$c" --version 2>&1 | head -n1; else echo "$c: 未安装"; fi
done

section "权限"
if has sudo; then sudo -n true 2>/dev/null && echo "sudo: 可免密使用" || echo "sudo: 存在但需要密码或无权限"; else echo "sudo: 未安装"; fi

section "网络（能否访问下载源，超时 8 秒）"
for u in https://github.com https://huggingface.co https://pypi.org https://astral.sh; do
  if has curl; then
    printf '%s -> ' "$u"; curl -s -o /dev/null -m 8 -w '%{http_code}\n' "$u" || echo "不通"
  else
    echo "curl 未安装，跳过 $u"
  fi
done

section "监听端口（Scope 默认用 8000）"
if has ss; then run ss -ltn; else echo "ss 不可用"; fi

section "完成"
echo "请把以上全部输出发给我。"
