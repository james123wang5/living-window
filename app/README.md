# 实时窗景 网页原型

左边全屏是壁纸，右边面板输入要求（如“我想看特别大的雨，雾气弥漫”）。画面从当前状态逐渐变过去，变完自动暂停、定住最后一帧；下一次要求从这个状态继续。

## 结构

```
浏览器 (http://127.0.0.1:8765)
  ⇅  本地桥接服务 app/server.py（Mac，Python 标准库 + ffmpeg）
  ⇅  SSH 隧道 Mac:18000 → TC2N01:8000
集群计算节点上的 Scope（LongLive + VACE；深度图 + 原图参考图）
```

- `server.py`：开会话、把用户要求交给提示词层、发给 Scope、过渡完成后自动暂停；用 ffmpeg 把 Scope 的视频流解成 JPEG 推给浏览器。
- `prompt_layer.py`：提示词层 v0（关键词规则）。以后换成 LLM；场景描述 `BASE` 以后由视觉语言模型自动生成。
- `index.html`：壁纸画布（把成批到达的帧均匀播出，帧间淡入淡出）+ 输入面板；自动测“收到新帧 / 开始变化 / 定住”三个时间。

## 启动

1. 集群上提交 Scope 作业（`sbatch ~/run_scope_job.sh`），等 LongLive 加载完成。
2. 建隧道（复用已登录的主连接，不用再输密码；节点名用 `squeue -u $USER` 查）：

```bash
ssh -O forward -L 18000:TC2N01:8000 -o ControlPath=$HOME/.ssh/cm-tc2 <user>@<head-node>
```

3. 启动桥接服务：

```bash
cd /Volumes/Lexar/桌面项目归档/realtime-video-wallpaper/app && python3 server.py
```

4. 浏览器打开 http://127.0.0.1:8765

## 依赖的集群文件

- `~/assets/moraine_576x320_depth.mp4`（深度图循环视频）、`~/assets/moraine_576x320.png`（参考图）
- Scope 本地补丁 `scripts/scope_local_patches.patch`：遮罩单通道；视频流编码改为 zerolatency（去掉约 40 帧缓冲）。
