"""提示词层 v0：把用户的中文要求转成 LongLive 的英文提示词和运行参数。

这是关键词规则版，用来先跑通网页；以后换成 LLM（读用户原话 + 场景元素清单 + 当前状态）。
场景描述 BASE 目前是为 Moraine Lake 手写的，以后由视觉语言模型自动生成。
"""
import re

BASE = (
    "A wide view of a mountain lake in the Canadian Rockies: a row of rugged rocky peaks across the back, "
    "a steep scree slope on the left, a dense conifer forest on the right shore, and a calm lake in the foreground "
    "reflecting the mountains, cinematic landscape photograph, photorealistic, highly detailed"
)

# 天气各分量：(等级 → (描述, 约束强度上限))。天气写在提示词最前面，模型更重视。
RAIN = {
    1: ("Light rain is falling, fine raindrops dot the lake surface with small rings of ripples, soft grey overcast sky, damp air. ", 0.85),
    2: ("Steady rain is falling, visible rain streaks across the frame, raindrops create many ripples on the lake, "
        "grey clouds cover the peaks, wet glistening rocks and trees. ", 0.75),
    3: ("Torrential heavy rain pouring down. Dense sheets of rain fall in long diagonal streaks across the entire frame, "
        "countless raindrops splash on the lake surface and create expanding circular ripples, the water is rough and grey, "
        "low dark storm clouds hang over the peaks, dim gloomy light. ", 0.65),
}
FOG = {
    1: ("Light mist drifts over the lake and between the trees, soft hazy air. ", 0.85),
    2: ("Thick dense fog fills the whole valley. Heavy white mist rolls across the lake and swallows the forest, "
        "the mountain peaks fade into the fog and are barely visible, soft diffused grey light, very low visibility. ", 0.6),
}
SNOW = {
    1: ("Gentle snowfall, soft snowflakes drift down through the air, a fresh layer of snow on the trees and shore. ", 0.85),
    2: ("A heavy snowstorm. Large snowflakes fall densely across the whole frame, swirling in the wind, thick fresh snow "
        "piles on the trees and the shore, the lake is partly frozen, white hazy air, cold blue-grey light. ", 0.6),
}
THUNDER = ("A violent thunderstorm, a bright lightning bolt flashes in the black clouds above the peaks. ", 0.65)
TIME = {
    "day": "",
    "sunrise": "At sunrise, soft pink and golden light touches the tips of the peaks, a pastel morning sky, calm cool air. ",
    "sunset": "At sunset, the sky blazes orange, pink and purple, warm golden alpenglow lights the peaks, "
              "long shadows, the lake reflects the fiery sky. ",
    "night": "At night, a dark navy sky full of bright stars and a bright moon, moonlit pale-blue snow on the peaks, "
             "a very dark forest, the lake reflects stars and moonlight. ",
}
SEASON = {
    "summer": "Summer, green forest, turquoise water. ",
    "spring": "Spring, fresh light-green foliage, patches of melting snow, wildflowers along the shore. ",
    "autumn": "Autumn, the forest full of golden yellow larches and orange foliage mixed with dark evergreens, "
              "a light dusting of fresh snow on the peaks. ",
    "winter": "Deep winter, thick white snow covers the forest and the shoreline, the lake is frozen and covered with ice and snow. ",
}

INITIAL_STATE = {"rain": 0, "fog": 0, "snow": 0, "thunder": False, "time": "day", "season": "summer"}

STRONG = r"(特别|超级|非常|很大|好大|巨|暴|倾盆|猛|浓|密|厚|弥漫)"
WEAK = r"(一点|小|毛毛|细|微|淡|薄|轻)"


def _level(text, word, strong_max, default):
    """在关键词附近找强弱修饰词，返回等级。"""
    for m in re.finditer(word, text):
        window = text[max(0, m.start() - 6): m.end() + 4]
        if re.search(STRONG, window):
            return strong_max
        if re.search(WEAK, window):
            return 1
        return default
    return 0


def plan(text, state):
    """返回 (新状态, 提示词, Scope 参数, 说明)。"""
    t = text.strip()
    s = dict(state)
    notes = []
    tl = t.lower()
    probe = t.replace("雪山", "")  # “雪山”不是下雪

    weather_mentioned = False
    rain = _level(probe, r"雨", 3, 2) or (3 if "storm" in tl else 2 if "rain" in tl else 0)
    fog = _level(probe, r"雾|霾|雾气", 2, 1) or (2 if "fog" in tl else 1 if "mist" in tl else 0)
    snow = _level(probe, r"雪", 2, 1) or (1 if "snow" in tl else 0)
    thunder = bool(re.search(r"雷|闪电|thunder|lightning", tl))
    clear = bool(re.search(r"晴|雨停|停雨|雾散|不下|阳光|clear|sunny", tl))
    if re.search(r"雨停|停雨|不下雨", t):
        rain = 0
    if rain or fog or snow or thunder or clear:
        weather_mentioned = True
        s.update(rain=rain, fog=fog, snow=snow, thunder=thunder)
        if thunder and not rain:
            s["rain"] = 3
        notes.append(f"天气 → 雨{s['rain']} 雾{s['fog']} 雪{s['snow']}{' 雷' if s['thunder'] else ''}")

    for key, pat in (("sunrise", r"日出|清晨|早晨|朝霞|sunrise"), ("sunset", r"日落|黄昏|夕阳|傍晚|晚霞|sunset|dusk"),
                     ("night", r"夜|晚上|星空|月亮|星星|night"), ("day", r"白天|中午|正午|daytime|noon")):
        if re.search(pat, tl):
            s["time"] = key
            notes.append(f"时间 → {key}")
            break
    for key, pat in (("spring", r"春|spring"), ("summer", r"夏|summer"), ("autumn", r"秋|autumn|fall"), ("winter", r"冬|winter")):
        if re.search(pat, tl):
            s["season"] = key
            notes.append(f"季节 → {key}")
            break

    parts, scale = [], 1.0
    if s["thunder"]:
        parts.append(THUNDER[0]); scale = min(scale, THUNDER[1])
    for table, k in ((RAIN, "rain"), (FOG, "fog"), (SNOW, "snow")):
        if s[k]:
            d, sc = table[s[k]]
            parts.append(d); scale = min(scale, sc)
    parts.append(TIME[s["time"]])
    parts.append(SEASON[s["season"]])
    matched = bool(notes)
    if not matched and t:
        # 规则没认出来：原话直接交给模型（Wan 的 umT5 文本编码器支持中文）
        parts.append(t + "。")
        notes.append("未识别关键词，原话直接交给模型")
    prompt = "".join(parts) + BASE

    steps = 4
    if re.search(r"快|立刻|马上|瞬间", t):
        steps = 2
    elif re.search(r"慢慢|缓缓|渐渐|逐渐", t):
        steps = 8
    params = {
        "transition": {"target_prompts": [{"text": prompt, "weight": 1.0}], "num_steps": steps},
        "vace_context_scale": scale,
    }
    notes.append(f"过渡 {steps} 块，约束强度 {scale}")
    return s, prompt, params, notes


def initial_prompt():
    return plan("", INITIAL_STATE)[1]
