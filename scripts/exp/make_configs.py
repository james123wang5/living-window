"""生成阶段二实验配置。场景提示词集中在这里，方便以后交给提示词转化层。"""
import json

VIDEO = "/home/msai/<user>/assets/moraine_576x320.mp4"
BASE = ("A wide view of a mountain lake in the Canadian Rockies: a row of rugged rocky peaks across the back, "
        "a steep scree slope on the left, a dense conifer forest on the right shore, and a calm lake in the foreground "
        "reflecting the mountains, cinematic landscape photograph, photorealistic")
SCENES = {
    "summer": BASE + ", summer midday, clear blue sky, bright sunlight, turquoise water, green forest",
    "autumn": BASE + ", autumn, the forest full of golden yellow larches and orange foliage mixed with dark evergreens, "
              "a light dusting of fresh snow on the peaks, crisp clear autumn light, the lake reflecting the golden trees",
    "winter": BASE + ", deep winter, thick white snow covering the whole forest and the shoreline, snow-laden trees, "
              "the lake frozen and covered with ice and snow, the peaks fully white, soft overcast light, cold blue-white tones",
    "storm": BASE + ", violent rainstorm, heavy rain pouring down with visible rain streaks everywhere, dark black storm clouds, "
             "dim gloomy light, mist hanging in the valley, the lake surface rough and covered in raindrop ripples and splashes, "
             "desaturated cold grey tones",
    "sunset": BASE + ", sunset, the sky blazing orange pink and purple, warm golden alpenglow on the peaks, long shadows, "
              "the lake reflecting the fiery sky",
}


def prompt(name):
    return [{"text": SCENES[name], "weight": 1.0}]


def to(name, steps=0):
    return {"transition": {"target_prompts": prompt(name), "num_steps": steps}}


def depth_graph(source=VIDEO):
    return {
        "nodes": [
            {"id": "input", "type": "source", "source_mode": "video_file", "source_name": source},
            {"id": "depth", "type": "pipeline", "pipeline_id": "video-depth-anything"},
            {"id": "longlive", "type": "pipeline", "pipeline_id": "longlive"},
            {"id": "output", "type": "sink"},
        ],
        "edges": [
            {"from": "input", "from_port": "video", "to_node": "depth", "to_port": "video", "kind": "stream"},
            {"from": "depth", "from_port": "video", "to_node": "longlive", "to_port": "vace_input_frames", "kind": "stream"},
            {"from": "longlive", "from_port": "video", "to_node": "output", "to_port": "video", "kind": "stream"},
        ],
    }


exp1 = {
    "tag": "p2_exp1_depth",
    "session": {"input_mode": "video", "prompts": prompt("summer"), "graph": depth_graph()},
    "warmup": 25,
    "schedule": [{"label": n, "params": to(n, 0), "hold": 30} for n in ["autumn", "winter", "storm", "sunset", "summer"]],
}
json.dump(exp1, open("exp1_depth.json", "w"), indent=1, ensure_ascii=False)
print("ok")

MASK = "/home/msai/<user>/assets/moraine_576x320_mask.mp4"


def mask_graph(source=VIDEO, mask=MASK):
    """原图作为 VACE 输入帧，山体遮罩（黑=保留）决定哪些区域可以重新生成。"""
    return {
        "nodes": [
            {"id": "input", "type": "source", "source_mode": "video_file", "source_name": source},
            {"id": "mask", "type": "source", "source_mode": "video_file", "source_name": mask},
            {"id": "longlive", "type": "pipeline", "pipeline_id": "longlive"},
            {"id": "output", "type": "sink"},
        ],
        "edges": [
            {"from": "input", "from_port": "video", "to_node": "longlive", "to_port": "vace_input_frames", "kind": "stream"},
            {"from": "mask", "from_port": "video", "to_node": "longlive", "to_port": "vace_input_masks", "kind": "stream"},
            {"from": "longlive", "from_port": "video", "to_node": "output", "to_port": "video", "kind": "stream"},
        ],
    }


exp2 = {
    "tag": "p2_exp2_mask",
    "session": {"input_mode": "video", "prompts": prompt("summer"), "graph": mask_graph()},
    "warmup": 25,
    "schedule": [{"label": n, "params": to(n, 0), "hold": 30} for n in ["autumn", "winter", "storm", "sunset", "summer"]],
}
json.dump(exp2, open("exp2_mask.json", "w"), indent=1, ensure_ascii=False)
print("ok2")

# ---- 预先算深度视频（运行时不再跑深度节点）----
DEPTH = "/home/msai/<user>/assets/moraine_576x320_depth.mp4"
REF = "/home/msai/<user>/assets/moraine_576x320.png"

depthvid = {
    "tag": "p2_depthvid",
    "session": {"input_mode": "video", "graph": {
        "nodes": [
            {"id": "input", "type": "source", "source_mode": "video_file", "source_name": VIDEO},
            {"id": "depth", "type": "pipeline", "pipeline_id": "video-depth-anything"},
            {"id": "output", "type": "sink"},
        ],
        "edges": [
            {"from": "input", "from_port": "video", "to_node": "depth", "to_port": "video", "kind": "stream"},
            {"from": "depth", "from_port": "video", "to_node": "output", "to_port": "video", "kind": "stream"},
        ]}},
    "warmup": 30,
    "schedule": [],
}
json.dump(depthvid, open("exp_depthvid.json", "w"), indent=1, ensure_ascii=False)

SCHED = [{"label": n, "params": to(n, 0), "hold": 30} for n in ["autumn", "winter", "storm", "sunset", "summer"]]

# 组合 C：原图做 V2V 起点（保身份，噪声控制像不像），预算好的深度视频进 VACE（锁结构）
exp2c = {
    "tag": "p2_exp2c_rgb_depth",
    "session": {"input_mode": "video", "prompts": prompt("summer"), "parameters": {"noise_scale": 1.0},
                "graph": {
                    "nodes": [
                        {"id": "input", "type": "source", "source_mode": "video_file", "source_name": VIDEO},
                        {"id": "depth", "type": "source", "source_mode": "video_file", "source_name": DEPTH},
                        {"id": "longlive", "type": "pipeline", "pipeline_id": "longlive"},
                        {"id": "output", "type": "sink"},
                    ],
                    "edges": [
                        {"from": "input", "from_port": "video", "to_node": "longlive", "to_port": "video", "kind": "stream"},
                        {"from": "depth", "from_port": "video", "to_node": "longlive", "to_port": "vace_input_frames", "kind": "stream"},
                        {"from": "longlive", "from_port": "video", "to_node": "output", "to_port": "video", "kind": "stream"},
                    ]}},
    "warmup": 25,
    "schedule": SCHED,
}
json.dump(exp2c, open("exp2c_rgb_depth.json", "w"), indent=1, ensure_ascii=False)

# 组合 D：预算好的深度视频进 VACE（锁结构），原图做参考图（保身份/风格）
exp2d = {
    "tag": "p2_exp2d_ref_depth",
    "session": {"input_mode": "video", "prompts": prompt("summer"), "parameters": {"vace_ref_images": [REF]},
                "graph": {
                    "nodes": [
                        {"id": "depth", "type": "source", "source_mode": "video_file", "source_name": DEPTH},
                        {"id": "longlive", "type": "pipeline", "pipeline_id": "longlive"},
                        {"id": "output", "type": "sink"},
                    ],
                    "edges": [
                        {"from": "depth", "from_port": "video", "to_node": "longlive", "to_port": "vace_input_frames", "kind": "stream"},
                        {"from": "longlive", "from_port": "video", "to_node": "output", "to_port": "video", "kind": "stream"},
                    ]}},
    "warmup": 25,
    "schedule": SCHED,
}
json.dump(exp2d, open("exp2d_ref_depth.json", "w"), indent=1, ensure_ascii=False)
print("ok3")

# ---- 实验 3：渐变（num_steps 4 / 8，不触发硬切清缓存），分别在组合 C、D 上 ----
SMOOTH = [
    {"label": "autumn_s4", "params": to("autumn", 4), "hold": 30},
    {"label": "winter_s8", "params": to("winter", 8), "hold": 30},
    {"label": "sunset_s4", "params": to("sunset", 4), "hold": 30},
    {"label": "summer_s8", "params": to("summer", 8), "hold": 30},
]
exp3c = dict(exp2c, tag="p2_exp3c_smooth", schedule=SMOOTH)
exp3d = dict(exp2d, tag="p2_exp3d_smooth", schedule=SMOOTH)
json.dump(exp3c, open("exp3c_smooth.json", "w"), indent=1, ensure_ascii=False)
json.dump(exp3d, open("exp3d_smooth.json", "w"), indent=1, ensure_ascii=False)
print("ok4")

# ---- 实验 5：天气特征（雨幕、雨点涟漪、浓雾、暴雪），天气写在提示词最前；对比约束强度 ----
WEATHER = {
    "heavy_rain": "Torrential heavy rain pouring down. Dense sheets of rain fall in long diagonal streaks across the entire frame, "
                  "countless raindrops splash on the lake surface and create expanding circular ripples, the water is rough and grey, "
                  "low dark storm clouds hang over the peaks, mist rising from the wet forest, dim gloomy light. ",
    "dense_fog": "Thick dense fog fills the whole valley. Heavy white mist rolls across the lake and swallows the forest, "
                 "the mountain peaks fade into the fog and are barely visible, soft diffused grey light, very low visibility, damp quiet air. ",
    "snowstorm": "A heavy snowstorm. Large snowflakes fall densely across the whole frame, swirling in the wind, "
                 "thick fresh snow piles on the trees and the shore, the lake is partly frozen, white hazy air, cold blue-grey light. ",
}


def wprompt(name):
    return [{"text": WEATHER[name] + BASE, "weight": 1.0}]


exp5 = dict(exp2d, tag="p2_exp5_weather", schedule=[
    {"label": "rain_scale1.0", "params": {"transition": {"target_prompts": wprompt("heavy_rain"), "num_steps": 4}}, "hold": 30},
    {"label": "rain_scale0.6", "params": {"vace_context_scale": 0.6}, "hold": 25},
    {"label": "fog_scale0.6", "params": {"transition": {"target_prompts": wprompt("dense_fog"), "num_steps": 4}}, "hold": 30},
    {"label": "snow_scale0.6", "params": {"transition": {"target_prompts": wprompt("snowstorm"), "num_steps": 4}}, "hold": 30},
])
json.dump(exp5, open("exp5_weather.json", "w"), indent=1, ensure_ascii=False)
print("ok5")

# ---- 实验 6：更大胆——约束降到 0.3，并降低对过去帧的依赖（雨丝是随时间运动的东西）----
exp6 = dict(exp2d, tag="p2_exp6_bold", schedule=[
    {"label": "rain_s0.3", "params": {"vace_context_scale": 0.3, "transition": {"target_prompts": wprompt("heavy_rain"), "num_steps": 4}}, "hold": 28},
    {"label": "rain_s0.3_kv0.3", "params": {"kv_cache_attention_bias": 0.3}, "hold": 22},
    {"label": "fog_s0.3_kv0.3", "params": {"transition": {"target_prompts": wprompt("dense_fog"), "num_steps": 4}}, "hold": 28},
    {"label": "snow_s0.3_kv0.3", "params": {"transition": {"target_prompts": wprompt("snowstorm"), "num_steps": 4}}, "hold": 28},
])
json.dump(exp6, open("exp6_bold.json", "w"), indent=1, ensure_ascii=False)
print("ok6")
