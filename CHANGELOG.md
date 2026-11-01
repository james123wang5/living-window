# Changelog

## v0.2.0 — 2026-10-29 · Stage 2: depth + reference + gradual transition
- Compared six anchoring approaches; chose auto depth + original reference + prompt ramp (4/8 steps).
- Web prototype (bridge server, prompt layer v0, wallpaper page, weather overlay): change starts in 3.5–6.6 s, holds in 18–28 s.
- Local Scope patches (single-channel mask, zero-latency video encode). Project **paused** at end of day.

## v0.1.0 — 2026-10-28 → 10-29 · Stage 1: does it run?
- Surveyed the hardware (NTU TC2 cluster, A40) and tech options; Scope + LongLive on A40 ≈ 7.6 FPS @ 576×320, 17.9 GB VRAM.
- PNG-anchor experiments, strong-prompt weather/time switching, latency measurements.
