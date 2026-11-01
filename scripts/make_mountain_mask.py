"""从底图粗分出山体，生成 VACE 遮罩（黑=保留山体，白=允许重新生成）。
按列找边界：从上往下第一个“非蓝天”的位置是山脊线；山脊线以下第一段持续“暗且偏绿”的位置是林线；
山体 = 山脊线到 min(林线, 湖岸线) 之间。背阴岩石偏蓝灰（蓝>绿），森林偏暗绿（绿>蓝），靠这一点区分。
用法：python make_mountain_mask.py 底图.png 输出前缀 [湖岸线高度比例，默认 0.72]
输出：<前缀>_mask.png 与 <前缀>_overlay.png（山体染红，便于检查）
"""
import sys

import numpy as np
from PIL import Image, ImageFilter

src, out = sys.argv[1], sys.argv[2]
shore = float(sys.argv[3]) if len(sys.argv) > 3 else 0.72

img = Image.open(src).convert("RGB")
a = np.asarray(img).astype(np.float32)
r, g, b = a[..., 0], a[..., 1], a[..., 2]
mx = a.max(axis=2)
h, w = r.shape
shore_y = int(h * shore)

# 纹理强度：亮度的横纵相邻差，5×5 平均；天空平滑，岩石和雪有纹理
lum = a.mean(axis=2)
grad = np.zeros_like(lum)
grad[:, 1:] += np.abs(np.diff(lum, axis=1))
grad[1:, :] += np.abs(np.diff(lum, axis=0))
tex = np.asarray(Image.fromarray(np.clip(grad * 4, 0, 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(2))).astype(np.float32) / 4
# 天空：明显偏蓝、亮、平滑（背阴的雪/岩石也可能很蓝，但有纹理）
sky_like = (b > r + 45) & (mx > 150) & (tex < 4)
forest_like = (g > b + 2) & (g > r) & (mx < 130)


def first_run(col_mask, start, run):
    cnt = 0
    for y in range(start, len(col_mask)):
        cnt = cnt + 1 if col_mask[y] else 0
        if cnt >= run:
            return y - run + 1
    return None


def median_smooth(v, k=9):
    p = k // 2
    vp = np.pad(v, p, mode="edge")
    return np.array([np.median(vp[i : i + k]) for i in range(len(v))]).astype(int)


ridge = np.array([first_run(~sky_like[:, x], 0, 3) or 0 for x in range(w)])
ridge = median_smooth(ridge)
treeline = np.array([first_run(forest_like[:, x], min(ridge[x] + 5, h - 1), 4) or shore_y for x in range(w)])
treeline = median_smooth(np.minimum(treeline, shore_y), 15)

yy = np.arange(h)[:, None]
mountain = (yy >= ridge[None, :]) & (yy < treeline[None, :])

mask = np.where(mountain, 0, 255).astype(np.uint8)
Image.fromarray(mask).convert("RGB").save(f"{out}_mask.png")
ov = a.copy()
ov[mountain] = ov[mountain] * 0.4 + np.array([255, 0, 0]) * 0.6
Image.fromarray(ov.astype(np.uint8)).save(f"{out}_overlay.png")
print("mountain fraction", round(float(mountain.mean()), 3))
