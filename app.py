import streamlit as st
import json
import os
import time
import threading
from datetime import datetime, date, timedelta, timezone
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# ==================== 🔑 API 配置 ====================
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# ==================== ⚙️ 用量 & 推送配置 ====================
DAILY_LIMIT = 15  # 单用户每日免费对话次数
MAX_CONTEXT_MESSAGES = 30  # 最多保留最近 N 条消息发给 API，避免超出 token 上限

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WHITELIST_FILE = os.path.join(BASE_DIR, "whitelist.json")
USAGE_FILE = os.path.join(BASE_DIR, "daily_usage.json")
PUSH_STATE_FILE = os.path.join(BASE_DIR, "push_state.json")
PERSONALITY_PROFILE_FILE = os.path.join(BASE_DIR, "personality_profile.json")

# ==================== 性格测试模块 ====================
# (以下代码内联自 personality_test.py，避免 Streamlit Cloud 找不到外部文件)
# ==================== 测试问题定义 ====================

DIMENSIONS = [
    {
        "id": "attachment",
        "name": "恋爱依恋风格",
        "icon": "💞",
        "subtitle": "你在亲密关系中的安全感和依赖模式",
        "questions": [
            {
                "id": "Q1",
                "text": "在亲密关系中，我常常担心对方会突然离开我",
                "reverse": True,   # 高分 = 焦虑倾向
                "trait": "安全感",
            },
            {
                "id": "Q2",
                "text": "我觉得完全依赖伴侣是一件很自然、很安心的事",
                "reverse": False,
                "trait": "依赖性",
            },
            {
                "id": "Q3",
                "text": "当伴侣几个小时没有回复消息时，我会感到焦虑不安",
                "reverse": True,
                "trait": "安全感",
            },
            {
                "id": "Q4",
                "text": "我倾向于保持一定的情感距离，不太愿意完全敞开心扉",
                "reverse": True,
                "trait": "独立性",
            },
            {
                "id": "Q5",
                "text": "即使伴侣不在身边，我也能感到安心和被爱",
                "reverse": False,
                "trait": "安全感",
            },
        ],
    },
    {
        "id": "expression",
        "name": "情感表达方式",
        "icon": "💬",
        "subtitle": "你如何向伴侣传达爱意和情绪",
        "questions": [
            {
                "id": "Q6",
                "text": "比起说\"我爱你\"，我更习惯用行动来证明自己的感情",
                "reverse": False,
                "trait": "行动表达",
            },
            {
                "id": "Q7",
                "text": "我会经常主动对伴侣说甜蜜的话或直接表达爱意",
                "reverse": False,
                "trait": "言语表达",
            },
            {
                "id": "Q8",
                "text": "当我不开心或有压力时，我更倾向于自己消化而不是说出来",
                "reverse": True,
                "trait": "言语表达",
            },
            {
                "id": "Q9",
                "text": "我是一个情感丰富的人，看电影或听音乐时很容易被触动",
                "reverse": False,
                "trait": "情绪敏感度",
            },
            {
                "id": "Q10",
                "text": "我喜欢通过肢体接触（拥抱、牵手、依偎）来表达亲密",
                "reverse": False,
                "trait": "行动表达",
            },
        ],
    },
    {
        "id": "social",
        "name": "社交倾向",
        "icon": "👥",
        "subtitle": "你在恋爱中的社交偏好和空间需求",
        "questions": [
            {
                "id": "Q11",
                "text": "恋爱中我喜欢和伴侣一起参加各种聚会、活动和饭局",
                "reverse": False,
                "trait": "社交性",
            },
            {
                "id": "Q12",
                "text": "比起热闹的约会，我更喜欢两个人安静地待在一起",
                "reverse": True,
                "trait": "社交性",
            },
            {
                "id": "Q13",
                "text": "我很在意朋友和家人对我伴侣的看法和评价",
                "reverse": False,
                "trait": "外部关注",
            },
            {
                "id": "Q14",
                "text": "即使在恋爱中，我也需要大量独处时间来做自己的事",
                "reverse": True,
                "trait": "独处需求",
            },
            {
                "id": "Q15",
                "text": "我愿意为了伴侣主动调整自己的社交圈子和习惯",
                "reverse": False,
                "trait": "社交性",
            },
        ],
    },
    {
        "id": "conflict",
        "name": "冲突处理模式",
        "icon": "🤝",
        "subtitle": "面对恋爱中的矛盾和分歧，你的应对方式",
        "questions": [
            {
                "id": "Q16",
                "text": "发生矛盾时，我会主动把问题摊开来说清楚",
                "reverse": False,
                "trait": "直面度",
            },
            {
                "id": "Q17",
                "text": "为了维持关系和谐，我通常会先让步或主动妥协",
                "reverse": False,
                "trait": "妥协度",
            },
            {
                "id": "Q18",
                "text": "面对冲突时我习惯沉默或转移话题，等事情自己过去",
                "reverse": True,
                "trait": "直面度",
            },
            {
                "id": "Q19",
                "text": "在争吵中我容易情绪激动，说出让自己后悔的话",
                "reverse": True,
                "trait": "情绪控制",
            },
            {
                "id": "Q20",
                "text": "争执过后，我会在冷静下来主动找对方沟通解决",
                "reverse": False,
                "trait": "直面度",
            },
        ],
    },
]

SCALE_LABELS = ["非常不符合", "不太符合", "一般 / 中立", "比较符合", "非常符合"]


# ==================== 评分与归类算法 ====================

def score_dimension(dimension: dict, answers: dict) -> dict:
    """
    对单个维度进行评分和类型判定。

    算法说明：
    1. 每道题原始分 1-5，反向题做 6-score 翻转
    2. 维度总分 = 5 题翻转后分数之和 (范围 5-25)
    3. 根据各 trait 的子分数，结合总分阈值判定类型

    返回：{ type, type_key, score, max_score, trait_scores, description }
    """
    raw_scores = {}
    trait_totals = {}

    for q in dimension["questions"]:
        qid = q["id"]
        raw = answers.get(qid, 3)  # 默认中立
        score = 6 - raw if q["reverse"] else raw  # 翻转
        raw_scores[qid] = score

        trait = q["trait"]
        if trait not in trait_totals:
            trait_totals[trait] = []
        trait_totals[trait].append(score)

    # 计算各 trait 平均分
    trait_avgs = {k: sum(v) / len(v) for k, v in trait_totals.items()}
    total = sum(raw_scores.values())
    max_score = len(dimension["questions"]) * 5

    # 类型判定
    dim_id = dimension["id"]
    type_key, type_name, description = classify_dimension(dim_id, trait_avgs, total)

    return {
        "type": type_name,
        "type_key": type_key,
        "score": total,
        "max_score": max_score,
        "percentage": round(total / max_score * 100),
        "trait_scores": {k: round(v, 1) for k, v in trait_avgs.items()},
        "description": description,
    }


def classify_dimension(dim_id: str, traits: dict, total: int):
    """根据维度 ID 和 trait 分数判定具体类型"""

    if dim_id == "attachment":
        # 恋爱依恋风格：安全型 / 焦虑型 / 回避型 / 恐惧型
        security = traits.get("安全感", 3)
        dependency = traits.get("依赖性", 3)
        independence = traits.get("独立性", 3)

        if security >= 3.5 and dependency >= 2.5:
            return ("secure", "安全型 🏠",
                    "你对亲密关系有健康的认知，既能享受亲密又能保持独立。你信任伴侣，"
                    "不会过度担心被抛弃，也不害怕表达自己的需求。你是恋爱中最稳定、"
                    "最让人安心的那类人。与你相处会感到踏实和自在。")
        elif security < 3 and dependency >= 3:
            return ("anxious", "焦虑型 💭",
                    "你在恋爱中容易患得患失，常常需要伴侣反复确认和安抚。你渴望亲密，"
                    "但内心的不安让你对关系的稳定性缺乏信心。你喜欢频繁的联系和回应，"
                    "因为那能让你暂时安心。你的深情是真挚的，只是需要一个能理解你、"
                    "给你足够安全感的伴侣。")
        elif independence >= 3.5 and dependency < 2.5:
            return ("avoidant", "回避型 🦋",
                    "你重视个人空间和独立性，对过度的亲密感到不自在。你可能不擅长"
                    "表达脆弱，也害怕在感情中失去自我。你不是不需要爱，而是用保持"
                    "距离来保护自己。你需要的伴侣是一个尊重你节奏、不步步紧逼的人。")
        else:
            return ("fearful", "矛盾型 🌧️",
                    "你内心渴望亲密，却又害怕受伤。你可能在靠近和疏远之间反复摇摆——"
                    "想要被爱，又担心一旦敞开心扉就会被伤害。这种矛盾让你在恋爱中"
                    "时而热情时而冷淡。你需要的不是更多的爱，而是一个让你感到足够安全、"
                    "可以慢慢卸下心防的人。")

    elif dim_id == "expression":
        # 情感表达方式：热烈外放型 / 含蓄行动型 / 理性克制型
        verbal = traits.get("言语表达", 3)
        action = traits.get("行动表达", 3)
        sensitivity = traits.get("情绪敏感度", 3)

        if verbal >= 3.5 and sensitivity >= 3:
            return ("expressive", "热烈外放型 🔥",
                    "你不吝啬表达爱意，甜言蜜语和亲昵举动都是你的日常。你的情绪写在脸上，"
                    "快乐和难过都愿意与伴侣分享。你的热情很有感染力，和你在一起永远不会无聊。"
                    "你适合一个同样喜欢表达、能接住你热情的伴侣。")
        elif action >= 3.5 and verbal < 3:
            return ("reserved", "含蓄行动型 🍃",
                    "你不擅长嘴上说爱，但你的每一个行动都在说\"我在乎你\"。你默默地记住"
                    "对方的喜好、在细节上用心、用实实在在的付出来表达感情。你是那种"
                    "\"做得多说得少\"的恋人，温暖踏实，不浮夸但很可靠。")
        else:
            return ("balanced_expr", "理性均衡型 ⚖️",
                    "你在情感表达上比较理性克制，不会过度热烈也不会过于冷淡。"
                    "你认为感情需要恰到好处的表达——多了显得浮夸，少了显得冷漠。"
                    "你适合一个能理解你节奏、不需要轰轰烈烈但求细水长流的伴侣。")

    elif dim_id == "social":
        # 社交倾向：外向伴侣型 / 居家依偎型 / 独立自主型
        sociability = traits.get("社交性", 3)
        solitude = traits.get("独处需求", 3)
        external = traits.get("外部关注", 3)

        if sociability >= 3.5:
            return ("social_butterfly", "外向伴侣型 🎉",
                    "你喜欢和伴侣一起探索世界，参加聚会、认识新朋友、分享彼此的社交圈。"
                    "对你来说，恋爱是两个人一起体验更丰富的生活。你的开朗和主动让你的"
                    "伴侣也能被你的能量感染。你适合一个同样乐于社交、不宅的伴侣。")
        elif solitude >= 3.5:
            return ("homebody", "居家依偎型 🏡",
                    "你理想中的恋爱是两个人窝在沙发上看电影、一起做饭、安静地待着。"
                    "外面的世界很精彩，但和你在一起的小空间就是整个世界。你不喜欢"
                    "无谓的社交，珍视高质量的独处时光。你适合一个同样享受安静、"
                    "不强迫你出门社交的伴侣。")
        elif external >= 3.5:
            return ("family_oriented", "关系融入型 👨‍👩‍👧",
                    "你很重视伴侣与自己生活圈的融合，希望对方能被你的家人朋友认可和喜欢。"
                    "你认为一段认真的感情需要融入彼此的世界。你愿意为关系做出调整和妥协，"
                    "也期待对方同样重视你身边的人。")
        else:
            return ("independent", "独立自主型 🌿",
                    "你在恋爱中保持清晰的自我边界，不依赖对方来定义自己的生活。"
                    "你享受恋爱，但不会被恋爱吞噬。你有自己的朋友圈、爱好和节奏，"
                    "期待的是两个独立的人在一起变得更好——而不是互相捆绑。")

    elif dim_id == "conflict":
        # 冲突处理模式：沟通型 / 妥协型 / 爆发型 / 回避型
        confrontation = traits.get("直面度", 3)
        compromise = traits.get("妥协度", 3)
        emotion_control = traits.get("情绪控制", 3)

        if confrontation >= 3.5 and emotion_control >= 3:
            return ("communicator", "成熟沟通型 🕊️",
                    "你面对矛盾时的第一反应是\"我们来谈谈\"。你相信大多数问题可以通过"
                    "真诚沟通来解决，你不逃避、不指责、不冷战。你在表达自己感受的同时"
                    "也尊重对方的立场。你是恋爱中的\"沟通高手\"，和你在一起的伴侣会很安心。")
        elif compromise >= 3.5 and confrontation < 3:
            return ("peacemaker", "温柔妥协型 ☮️",
                    "你不喜欢吵架，宁愿自己退一步来换取关系的和平。你善解人意，"
                    "能站在对方的角度思考，是关系中的润滑剂。不过有时候也要记得"
                    "照顾自己的感受——一味退让不是长久之计哦。")
        elif emotion_control < 2.5 and confrontation < 2.5:
            return ("volatile", "情绪波动型 🌋",
                    "你在冲突中容易被情绪裹挟，说出或做出事后会后悔的事。你并不想伤害对方，"
                    "只是在情绪上头的那一刻难以控制自己。学会在激动时暂停、给自己冷静的"
                    "空间，是你成长的关键。你的感情很真实，只是需要学会更好地表达。")
        elif confrontation < 2.5 and compromise < 3:
            return ("avoider", "回避沉默型 🐚",
                    "面对冲突时，你的本能是缩回壳里——沉默、回避、等事情自己平息。"
                    "你不是不在乎，而是不知道该如何开口，害怕一说就错、一吵就散。"
                    "但沉默积累久了会变成隔阂。学着在安全的环境中一点一点说出自己的感受，"
                    "你会发现在爱里的人比想象中更愿意倾听。")
        else:
            return ("balanced_conf", "灵活应对型 🔄",
                    "你在处理冲突时比较灵活，根据具体情况选择直面或退让。"
                    "你有一定的情绪自控力，也能在需要时主动沟通。这种弹性的处理方式"
                    "让你在大多数关系中都能找到平衡点。")

    return ("unknown", "未知", "")


def generate_overall_profile(dim_results: dict) -> dict:
    """
    综合四个维度的结果，生成整体性格画像和恋爱建议。

    算法：
    - 分析各维度类型的组合模式
    - 基于组合给出个性化的恋爱建议
    - 生成可用于匹配的"性格向量"
    """
    attachment = dim_results["attachment"]
    expression = dim_results["expression"]
    social = dim_results["social"]
    conflict = dim_results["conflict"]

    # 构建性格向量 (用于未来匹配)
    vector = {
        "security": attachment["trait_scores"].get("安全感", 3),
        "dependency": attachment["trait_scores"].get("依赖性", 3),
        "independence": attachment["trait_scores"].get("独立性", 3),
        "verbal_expression": expression["trait_scores"].get("言语表达", 3),
        "action_expression": expression["trait_scores"].get("行动表达", 3),
        "sensitivity": expression["trait_scores"].get("情绪敏感度", 3),
        "sociability": social["trait_scores"].get("社交性", 3),
        "solitude_need": social["trait_scores"].get("独处需求", 3),
        "confrontation": conflict["trait_scores"].get("直面度", 3),
        "compromise": conflict["trait_scores"].get("妥协度", 3),
        "emotion_control": conflict["trait_scores"].get("情绪控制", 3),
    }

    # 生成综合画像名称
    attachment_key = attachment["type_key"]
    expression_key = expression["type_key"]
    social_key = social["type_key"]
    conflict_key = conflict["type_key"]

    # 综合标签
    overall_tags = []

    if attachment_key == "secure":
        overall_tags.append("稳定内核")
    elif attachment_key == "anxious":
        overall_tags.append("深情守望者")
    elif attachment_key == "avoidant":
        overall_tags.append("自由灵魂")
    else:
        overall_tags.append("敏感心灵")

    if expression_key == "expressive":
        overall_tags.append("热情火焰")
    elif expression_key == "reserved":
        overall_tags.append("温柔微风")
    else:
        overall_tags.append("沉静湖水")

    if conflict_key == "communicator":
        overall_tags.append("沟通达人")
    elif conflict_key == "peacemaker":
        overall_tags.append("和平使者")
    elif conflict_key == "volatile":
        overall_tags.append("真性情派")
    elif conflict_key == "avoider":
        overall_tags.append("深海潜行者")

    # 生成恋爱建议
    love_advice = generate_love_advice(attachment_key, expression_key, social_key, conflict_key)

    # 生成适合的伴侣类型
    compatible_types = generate_compatibility(attachment_key, social_key, conflict_key)

    return {
        "tags": overall_tags,
        "vector": vector,
        "love_advice": love_advice,
        "compatible_types": compatible_types,
    }


def generate_love_advice(att_key, exp_key, soc_key, con_key):
    """根据四维类型组合，生成个性化恋爱建议"""
    advices = []

    # 依恋相关建议
    if att_key == "secure":
        advices.append("你的安全感很足，这是恋爱中最珍贵的品质。继续保持这份从容，"
                       "同时也要理解——不是每个人都有和你一样的安全感。对伴侣多一点耐心，"
                       "你的稳定本身就是对方最好的避风港。")
    elif att_key == "anxious":
        advices.append("你的不安源于在乎，这本身不是错。但在关系中，试着把注意力"
                       "从\"他会不会离开\"转移到\"我现在需要什么\"。培养自己的兴趣爱好，"
                       "建立属于自己的安全感来源——当你不再害怕失去，反而能真正拥有。")
    elif att_key == "avoidant":
        advices.append("你的独立令人欣赏，但爱本身就是一种\"健康地依赖\"。试着在信任的"
                       "人面前慢慢放下防备，让对方看到你柔软的一面。全然的独立不叫恋爱，"
                       "敢于依赖才是真正的勇敢。")
    elif att_key == "fearful":
        advices.append("你的矛盾源于过去的伤痕，不是你的错。给自己时间去信任一个人，"
                       "不需要一次到位。找那个愿意等你的节奏、不会在你退缩时转身离开的人。"
                       "治愈不是忘记过去，而是在新的关系里重新学习信任。")

    # 社交相关建议
    if soc_key == "social_butterfly":
        advices.append("你喜欢和伴侣一起社交，这很棒！但也别忘了给对方留一些只属于"
                       "两个人的安静时光。有时候，最浪漫的事不是去最热闹的派对，"
                       "而是两个人什么也不做，就安静地待在一起。")
    elif soc_key == "homebody":
        advices.append("你享受安静的二人世界，这很温暖。但偶尔陪对方走出舒适区，"
                       "参加一些社交活动，也是爱的表达。好的关系是——大多数时候宅在一起，"
                       "偶尔一起探索外面的世界。")

    # 冲突相关建议
    if con_key == "communicator":
        advices.append("你处理冲突的方式很成熟，这是难得的情感能力。继续保持这种"
                       "坦诚沟通的态度，你能经营好任何一段你在乎的关系。")
    elif con_key == "peacemaker":
        advices.append("你的温柔让关系少了很多不必要的摩擦。但请记得——表达自己的"
                       "真实感受不是制造矛盾。真正的和谐不是没有冲突，而是冲突之后"
                       "还能彼此理解。偶尔也要为自己发声。")
    elif con_key == "volatile":
        advices.append("你的情绪是真实的，只是需要更好的表达方式。下次情绪上头时，"
                       "试着先说\"我需要冷静一下，过会儿再聊\"，给自己一个缓冲。"
                       "说出去的话收不回，但忍住的话可以说在合适的时候。")
    elif con_key == "avoider":
        advices.append("你的沉默是保护自己，但可能让对方感到被拒绝。试着从小的"
                       "表达开始——\"我现在不知道怎么说，但我在乎你\"。迈出第一步"
                       "很难，但每一次尝试都在让你们的连接更深。")

    return advices


def generate_compatibility(att_key, soc_key, con_key):
    """生成适合的伴侣类型描述"""
    compatible = []

    if att_key == "anxious":
        compatible.append("能给你稳定安全感的人（安全型依恋）")
        compatible.append("愿意经常回应你、不嫌你\"粘人\"的人")
    elif att_key == "avoidant":
        compatible.append("尊重你个人空间、不会步步紧逼的人")
        compatible.append("情绪稳定、能让你慢慢放下防备的人")
    elif att_key == "fearful":
        compatible.append("极其有耐心、愿意等你慢慢建立信任的人")
        compatible.append("言行一致、用行动证明可靠的人")
    elif att_key == "secure":
        compatible.append("能与你平等相处、互相滋养的人")
        compatible.append("同样有安全感、不制造无谓 drama 的人")

    if soc_key == "homebody":
        compatible.append("享受安静陪伴、不强迫你社交的人")
    elif soc_key == "social_butterfly":
        compatible.append("愿意陪你参加活动、乐于社交的人")

    if con_key == "avoider":
        compatible.append("能温柔引导你表达、不咄咄逼人的人")
    elif con_key == "volatile":
        compatible.append("情绪稳定、能在你激动时给你冷静空间的人")

    return compatible


# ==================== 数据持久化 ====================

def save_personality_profile(profile: dict, file_path: str):
    """保存性格测试结果到 JSON 文件"""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_personality_profile(file_path: str) -> dict | None:
    """加载性格测试结果"""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "dimensions" in data:
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def build_personality_prompt(profile: dict) -> str:
    """根据性格档案生成注入 System Prompt 的文字"""
    if not profile:
        return ""

    dims = profile.get("dimensions", {})
    tags = profile.get("overall", {}).get("tags", [])

    lines = [
        "\n\n【用户性格档案 - 小暖内部参考，不要在回复中直接引用这些术语】",
        "以下是该用户的恋爱性格测试结果，请你在聊天中：",
        "1. 自然地根据 TA 的性格特点调整回复风格",
        "2. 不要直接说\"根据你的测试结果\"之类的话——这些信息应该是你\"感觉\"到的",
        "3. 在适当的时候，可以委婉地给出与 TA 性格匹配的建议",
    ]

    dim_labels = {
        "attachment": "恋爱依恋风格",
        "expression": "情感表达方式",
        "social": "社交倾向",
        "conflict": "冲突处理模式",
    }

    for dim_id, dim_data in dims.items():
        label = dim_labels.get(dim_id, dim_id)
        lines.append(f"- {label}：{dim_data['type']}")

    if tags:
        lines.append(f"- 性格标签：{'、'.join(tags)}")

    return "\n".join(lines)


# ==================== UI 渲染 ====================

def render_personality_test(profile_file: str):
    """渲染性格测试的完整 UI 流程（intro → 答题 → 结果）"""

    # 初始化测试状态
    if "test_stage" not in st.session_state:
        st.session_state.test_stage = "intro"
    if "test_answers" not in st.session_state:
        st.session_state.test_answers = {}
    if "test_current_dim" not in st.session_state:
        st.session_state.test_current_dim = 0

    # ---- 阶段 1：介绍页 ----
    if st.session_state.test_stage == "intro":
        render_intro()

    # ---- 阶段 2：答题页 ----
    elif st.session_state.test_stage == "questions":
        render_questions(profile_file)

    # ---- 阶段 3：结果页 ----
    elif st.session_state.test_stage == "results":
        render_results(profile_file)


def render_intro():
    """测试介绍页面"""
    st.markdown("---")
    st.markdown("## 🧠 恋爱性格测试")
    st.markdown("### 发现你在爱情中的真实模样")

    st.markdown("""
    <div style="background: linear-gradient(135deg, #fff5f5, #fef0f0, #fff9f0);
                border-radius: 16px; padding: 28px 32px; margin: 16px 0;
                border: 1px solid #f0d0d0;">
    <p style="font-size: 15px; line-height: 1.8; color: #5c3d3d; margin: 0;">
    💕 <b>小暖为你准备了一份特别的测试</b>——这不是那种随便答几题就给你贴标签的测试哦。\n
    我精心设计了 <b>20 道题目</b>，从 <b>4 个维度</b> 深入了解你在恋爱中的性格：</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        <div style="background: #fff; border-radius: 12px; padding: 20px;
                    margin: 8px 0; border-left: 4px solid #ff9999;">
        <h4 style="margin: 0 0 8px 0; color: #c0392b;">💞 恋爱依恋风格</h4>
        <p style="margin: 0; color: #666; font-size: 14px;">你在亲密关系中的安全感模式<br>——是安心依赖，还是患得患失？</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background: #fff; border-radius: 12px; padding: 20px;
                    margin: 8px 0; border-left: 4px solid #ffb347;">
        <h4 style="margin: 0 0 8px 0; color: #c0392b;">👥 社交倾向</h4>
        <p style="margin: 0; color: #666; font-size: 14px;">恋爱中的社交偏好和空间需求<br>——是外向型伴侣，还是居家型依偎？</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div style="background: #fff; border-radius: 12px; padding: 20px;
                    margin: 8px 0; border-left: 4px solid #87ceeb;">
        <h4 style="margin: 0 0 8px 0; color: #c0392b;">💬 情感表达方式</h4>
        <p style="margin: 0; color: #666; font-size: 14px;">你如何向伴侣传达爱意<br>——是热烈外放，还是含蓄行动？</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background: #fff; border-radius: 12px; padding: 20px;
                    margin: 8px 0; border-left: 4px solid #a0d8a0;">
        <h4 style="margin: 0 0 8px 0; color: #c0392b;">🤝 冲突处理模式</h4>
        <p style="margin: 0; color: #666; font-size: 14px;">面对矛盾时的应对方式<br>——是主动沟通，还是沉默回避？</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div style="background: #fefefe; border-radius: 12px; padding: 16px 20px;
                margin: 16px 0; border: 1px dashed #ddd;">
    <p style="font-size: 14px; color: #888; margin: 0;">
    ⏱️ 大约需要 <b>5-8 分钟</b>  ·  📝 <b>20 道选择题</b>  ·  🔒 结果仅保存在你的设备上
    </p>
    </div>
    """, unsafe_allow_html=True)

    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        if st.button("✨ 开始测试", use_container_width=True, type="primary"):
            st.session_state.test_stage = "questions"
            st.session_state.test_current_dim = 0
            st.session_state.test_answers = {}
            st.rerun()

    st.markdown("---")


def render_questions(profile_file: str):
    """渲染答题页面 —— 分维度展示，每次显示一个维度"""
    dim_idx = st.session_state.test_current_dim

    if dim_idx >= len(DIMENSIONS):
        # 所有维度答完 → 计算结果并跳转
        results = calculate_all_dimensions(st.session_state.test_answers)
        overall = generate_overall_profile(results)

        profile = {
            "date": __import__("datetime").date.today().isoformat(),
            "dimensions": results,
            "overall": {
                "tags": overall["tags"],
                "vector": overall["vector"],
                "love_advice": overall["love_advice"],
                "compatible_types": overall["compatible_types"],
            },
        }

        save_personality_profile(profile, profile_file)
        st.session_state.personality_profile = profile
        st.session_state.test_stage = "results"
        st.rerun()
        return

    dim = DIMENSIONS[dim_idx]
    total_dims = len(DIMENSIONS)

    # 进度条
    progress_pct = dim_idx / total_dims
    st.markdown("---")
    st.progress(progress_pct)
    st.caption(f"第 {dim_idx + 1} / {total_dims} 部分")

    # 维度标题
    st.markdown(f"## {dim['icon']} {dim['name']}")
    st.markdown(f"*{dim['subtitle']}*")
    st.markdown("")

    # 问题
    for q in dim["questions"]:
        qid = q["id"]
        current_val = st.session_state.test_answers.get(qid, None)

        # 用 radio 展示 5 级量表
        idx_default = SCALE_LABELS.index("一般 / 中立")
        idx_current = current_val - 1 if current_val else idx_default

        st.markdown(f"**{qid}. {q['text']}**")

        answer = st.radio(
            f"请选择你的答案：",
            options=list(range(1, 6)),
            format_func=lambda x: SCALE_LABELS[x - 1],
            index=idx_current,
            key=f"radio_{qid}",
            horizontal=True,
            label_visibility="collapsed",
        )
        st.session_state.test_answers[qid] = answer
        st.markdown("")

    st.markdown("")

    # 按钮
    col1, col2 = st.columns([1, 1])
    with col1:
        if dim_idx > 0:
            if st.button("⬅️ 上一部分", use_container_width=True):
                st.session_state.test_current_dim -= 1
                st.rerun()

    with col2:
        label = "➡️ 下一部分" if dim_idx < total_dims - 1 else "🎉 查看结果"
        if st.button(label, use_container_width=True, type="primary"):
            st.session_state.test_current_dim += 1
            st.rerun()

    st.markdown("---")


def calculate_all_dimensions(answers: dict) -> dict:
    """对所有维度进行评分"""
    results = {}
    for dim in DIMENSIONS:
        results[dim["id"]] = score_dimension(dim, answers)
    return results


def render_results(profile_file: str):
    """渲染测试结果页面"""
    profile = st.session_state.get("personality_profile", {})
    if not profile:
        profile = load_personality_profile(profile_file)
    if not profile:
        st.warning("还没有测试结果，请先完成测试～")
        st.session_state.test_stage = "intro"
        st.rerun()
        return

    dims = profile.get("dimensions", {})
    overall = profile.get("overall", {})

    st.markdown("---")

    # 标题
    st.markdown("## 🎉 你的恋爱性格画像")
    st.markdown("*小暖根据你的回答，为你绘制了这份独一无二的性格地图～*")

    st.markdown("")

    # 性格标签
    tags = overall.get("tags", [])
    if tags:
        tag_html = "  ".join([
            f'<span style="display: inline-block; background: linear-gradient(135deg, #ff9999, #ff7777); '
            f'color: white; padding: 5px 14px; border-radius: 20px; font-size: 13px; '
            f'margin: 3px;">{t}</span>'
            for t in tags
        ])
        st.markdown(f"""
        <div style="text-align: center; margin: 16px 0;">
            {tag_html}
        </div>
        """, unsafe_allow_html=True)

    st.markdown("")

    # 四个维度的详细结果
    dim_configs = {d["id"]: d for d in DIMENSIONS}

    for dim_id, dim_data in dims.items():
        cfg = dim_configs.get(dim_id, {})
        icon = cfg.get("icon", "")
        name = cfg.get("name", dim_id)

        pct = dim_data.get("percentage", 50)

        # 进度条颜色
        if pct >= 70:
            bar_color = "#ff7777"
        elif pct >= 40:
            bar_color = "#ffb347"
        else:
            bar_color = "#87ceeb"

        st.markdown(f"""
        <div style="background: #fff; border-radius: 14px; padding: 20px 24px;
                    margin: 12px 0; border: 1px solid #eee;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.04);">
            <h3 style="margin: 0 0 4px 0; color: #333;">{icon} {name}</h3>
            <h4 style="margin: 0 0 12px 0; color: #c0392b; font-weight: 500;">
                {dim_data['type']}
            </h4>
            <div style="background: #f5f5f5; border-radius: 8px; height: 8px; margin: 8px 0;">
                <div style="background: {bar_color}; border-radius: 8px; height: 8px;
                            width: {pct}%; transition: width 0.5s;"></div>
            </div>
            <p style="color: #999; font-size: 12px; margin: 4px 0 12px 0;">
                维度得分：{dim_data['score']} / {dim_data['max_score']} （{pct}%）
            </p>
            <p style="color: #555; font-size: 14px; line-height: 1.7;
                      margin: 0; text-align: justify;">
                {dim_data['description']}
            </p>
        </div>
        """, unsafe_allow_html=True)

    # 恋爱建议
    st.markdown("")
    st.markdown("### 💌 小暖给你的恋爱悄悄话")

    love_advice = overall.get("love_advice", [])
    for i, advice in enumerate(love_advice):
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #fff9f0, #fff5e6);
                    border-radius: 12px; padding: 16px 20px; margin: 8px 0;
                    border-left: 4px solid #f0c060;">
            <p style="margin: 0; color: #5c4a2e; font-size: 14px; line-height: 1.7;">
            🌸 {advice}
            </p>
        </div>
        """, unsafe_allow_html=True)

    # 适合的伴侣类型
    st.markdown("")
    st.markdown("### 💕 可能与你合拍的人")

    compatible = overall.get("compatible_types", [])
    if compatible:
        cols = st.columns(2)
        for i, c in enumerate(compatible):
            with cols[i % 2]:
                st.markdown(f"""
                <div style="background: #fefefe; border-radius: 10px; padding: 12px 16px;
                            margin: 4px 0; border: 1px solid #e8e8e8; text-align: center;">
                    <p style="margin: 0; color: #555; font-size: 13px;">✨ {c}</p>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("")
    st.markdown("""
    <div style="background: #f0f7ff; border-radius: 10px; padding: 12px 16px;
                margin: 16px 0; border: 1px solid #d0e0f0; text-align: center;">
        <p style="margin: 0; color: #5a7d9a; font-size: 13px;">
        🔮 未来小暖会帮你找到性格相合的人——敬请期待匹配功能～
        </p>
    </div>
    """, unsafe_allow_html=True)

    # 按钮
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("💬 回到聊天", use_container_width=True, type="primary"):
            st.session_state.test_stage = "intro"
            st.session_state.show_test = False
            st.rerun()

        st.markdown("")
        if st.button("🔄 重新测试", use_container_width=True):
            st.session_state.test_stage = "intro"
            st.session_state.test_answers = {}
            st.session_state.test_current_dim = 0
            st.rerun()

    st.markdown("---")


# 定时推送时间点 (小时, 分钟)
LUNCH_TRIGGER = (12, 30)
BEDTIME_TRIGGER = (23, 30)

LUNCH_MSG = "记得好好吃午饭，别为了项目不顾身体呀❤️"
BEDTIME_MSG = "夜深了，再不睡就要变成国宝了，小暖陪你一起睡吧～睡前喝杯温水。"

OVERLIMIT_MSG = (
    "💕 主人，今天的暖心对话次数已经用完啦（每日 {limit} 次）～\n\n"
    "小暖好想继续陪主人聊天呢... 🥺\n\n"
    "📱 **加小暖微信，请主人喝杯奶茶 🥤，就能解锁无限畅聊哦～**\n"
    "（微信号：XiaoNuan_AI，备注「暖心伴侣」即可通过，小暖等你呀 💕）"
)

# -------------------- 文件级线程锁（防止并发读写冲突） --------------------
_usage_lock = threading.Lock()
_push_lock = threading.Lock()

# -------------------- 页面设置 --------------------
st.set_page_config(
    page_title="暖心伴侣 💕",
    page_icon="💕",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -------------------- 初始化 OpenAI 客户端 --------------------
if API_KEY:
    client = OpenAI(api_key=API_KEY, base_url=DEEPSEEK_BASE_URL)
else:
    client = None

# ==================== 聊天历史持久化（本地 JSON） ====================
HISTORY_FILE = os.path.join(BASE_DIR, "chat_history.json")


def load_chat_history():
    """从本地 JSON 文件加载聊天历史。文件不存在或损坏时返回 None。"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_chat_history(messages):
    """将完整聊天历史实时写入本地 JSON 文件。"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ==================== 白名单 ====================
def load_whitelist():
    """加载白名单用户列表。"""
    if os.path.exists(WHITELIST_FILE):
        try:
            with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def save_whitelist(whitelist_set):
    """保存白名单。"""
    try:
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(whitelist_set)), f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ==================== 每日用量 ====================
def load_daily_usage():
    """加载每日用量：{ '2026-06-20': { 'alice': 5, 'bob': 3 } }"""
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_daily_usage(usage):
    """保存每日用量。"""
    try:
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(usage, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def check_daily_limit(user_id: str):
    """
    检查用户当日是否超出对话次数上限。
    返回 (can_chat: bool, message: str)
      - can_chat=True   → 可以继续对话
      - can_chat=False  → 已超限，message 为引导文本
    """
    # 白名单用户不受限制
    whitelist = load_whitelist()
    if user_id in whitelist:
        return True, ""

    today_str = date.today().isoformat()

    with _usage_lock:
        usage = load_daily_usage()
        # 新的一天，清空旧数据
        if today_str not in usage:
            usage[today_str] = {}

        count = usage[today_str].get(user_id, 0)

        if count >= DAILY_LIMIT:
            return False, OVERLIMIT_MSG.format(limit=DAILY_LIMIT)

        # 未超限，计数 +1
        usage[today_str][user_id] = count + 1
        save_daily_usage(usage)
        return True, ""


def get_today_usage(user_id: str):
    """查询用户当日已使用次数（不增加计数）。"""
    today_str = date.today().isoformat()
    usage = load_daily_usage()
    return usage.get(today_str, {}).get(user_id, 0)


# ==================== 定时推送状态 ====================
def load_push_state():
    """加载推送状态：{ '2026-06-20': { 'lunch': True, 'bedtime': False } }"""
    if os.path.exists(PUSH_STATE_FILE):
        try:
            with open(PUSH_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_push_state(state):
    """保存推送状态。"""
    try:
        with open(PUSH_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def check_and_apply_scheduled_push():
    """
    检查当前时间是否到达推送点，若已到达且当天未推送，则自动插入消息。
    在每次页面渲染时调用。
    """
    now = datetime.now()
    today_str = date.today().isoformat()
    hm = (now.hour, now.minute)

    with _push_lock:
        push_state = load_push_state()
        if today_str not in push_state:
            push_state[today_str] = {}

        today_state = push_state[today_str]
        changed = False

        # 午餐推送
        if hm >= LUNCH_TRIGGER and not today_state.get("lunch"):
            today_state["lunch"] = True
            push_state[today_str] = today_state
            changed = True
            # 插入消息到会话
            st.session_state.messages.append(
                {"role": "assistant", "content": LUNCH_MSG}
            )
            save_chat_history(st.session_state.messages)

        # 晚安推送
        if hm >= BEDTIME_TRIGGER and not today_state.get("bedtime"):
            today_state["bedtime"] = True
            push_state[today_str] = today_state
            changed = True
            st.session_state.messages.append(
                {"role": "assistant", "content": BEDTIME_MSG}
            )
            save_chat_history(st.session_state.messages)

        if changed:
            save_push_state(push_state)


def start_background_scheduler():
    """
    启动后台定时器线程：每 60 秒检查一次推送时间，若到达则标记推送状态。
    仅操作 JSON 文件，不触碰 Streamlit session_state（避免跨线程冲突）。
    主渲染循环在 check_and_apply_scheduled_push() 中读取文件并真正插入消息。
    """
    if "scheduler_started" in st.session_state:
        return
    st.session_state.scheduler_started = True

    def _scheduler_loop():
        while True:
            time.sleep(60)
            try:
                now = datetime.now()
                today_str = date.today().isoformat()
                hm = (now.hour, now.minute)

                with _push_lock:
                    push_state = load_push_state()
                    if today_str not in push_state:
                        push_state[today_str] = {}

                    today_state = push_state[today_str]
                    dirty = False

                    if hm >= LUNCH_TRIGGER and not today_state.get("lunch"):
                        today_state["lunch"] = True
                        dirty = True

                    if hm >= BEDTIME_TRIGGER and not today_state.get("bedtime"):
                        today_state["bedtime"] = True
                        dirty = True

                    if dirty:
                        push_state[today_str] = today_state
                        save_push_state(push_state)

            except Exception:
                pass  # 后台静默，不影响主流程

    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()


# ==================== 微信风格 CSS ====================
st.markdown("""
<style>
/* ===== 全局字体 ===== */
html, body, [class*="css"] {
    font-family: 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', 'Noto Sans SC', sans-serif;
}

/* 隐藏 Streamlit 默认元素 */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* 整体背景 — 温馨暖粉渐变 */
.stApp {
    background: linear-gradient(180deg, #fef0f0 0%, #fdf2e4 30%, #fef9f3 60%, #fce4ec 100%) !important;
    background-attachment: fixed !important;
}

/* Streamlit 主容器也改为透明 */
.stMain {
    background: transparent !important;
}

/* block-container 透明 */
.stApp .block-container {
    background: transparent !important;
}

/* ===== 顶部固定栏 ===== */
.sticky-top-bar {
    position: sticky;
    top: 0;
    z-index: 200;
    background: rgba(254, 240, 240, 0.95);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid #f0d8e0;
    padding: 8px 0;
    margin-bottom: 12px;
}

/* ===== 顶部标题栏 ===== */
.title-bar {
    background: transparent;
    padding: 12px 20px;
    text-align: center;
    font-size: 18px;
    font-weight: 600;
    color: #191919;
    border-bottom: none;
    position: static;
    top: auto;
    z-index: auto;
    margin-bottom: 0;
}

/* ===== 聊天消息容器 ===== */
.stChatMessage {
    max-width: 700px;
    margin: 0 auto 8px auto !important;
}

/* 气泡基础 */
[data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
    border-radius: 4px !important;
    padding: 10px 14px !important;
    font-size: 15px !important;
    line-height: 1.6 !important;
    word-break: break-word !important;
    position: relative !important;
    max-width: fit-content !important;
}

/* ===== 头像样式 ===== */
[data-testid="stChatMessageAvatar"] {
    width: 40px !important;
    height: 40px !important;
    border-radius: 6px !important;
    font-size: 22px !important;
    flex-shrink: 0 !important;
}

/* ===== 聊天输入框 ===== */
.stChatInput {
    max-width: 700px;
    margin: 0 auto !important;
}

.stChatInput textarea {
    border-radius: 4px !important;
    border: 1px solid #d9d9d9 !important;
    font-size: 15px !important;
    font-family: 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', 'Noto Sans SC', sans-serif !important;
}

.stChatInput textarea:focus {
    border-color: #07c160 !important;
    box-shadow: 0 0 0 2px rgba(7, 193, 96, 0.15) !important;
}

/* ===== 超出限制提示卡片 ===== */
.overlimit-card {
    background: linear-gradient(135deg, #fff9f0, #fff5e6);
    border: 2px solid #f0c060;
    border-radius: 12px;
    padding: 20px 24px;
    margin: 16px 0;
    text-align: center;
    font-size: 15px;
    line-height: 1.8;
    color: #5c4a2e;
}

.overlimit-card .wechat-highlight {
    display: inline-block;
    background: #07c160;
    color: #fff;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    margin: 8px 0;
    font-size: 16px;
}

/* ===== 侧边栏用量指示 ===== */
.usage-badge {
    display: inline-block;
    background: #e8f5e9;
    color: #2e7d32;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 500;
}

.usage-badge.warning {
    background: #fff3e0;
    color: #e65100;
}

.usage-badge.limit {
    background: #ffebee;
    color: #c62828;
}

/* ===== 滚动条美化 ===== */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #c1c1c1; border-radius: 3px; }

/* ===== 移动端适配 ===== */
@media (max-width: 500px) {
    .stChatMessage {
        max-width: 100% !important;
    }
    .stChatInput {
        max-width: 100% !important;
    }
}
</style>
""", unsafe_allow_html=True)

# ==================== Session State 初始化 ====================
if "messages" not in st.session_state:
    loaded = load_chat_history()
    if loaded:
        st.session_state.messages = loaded
    else:
        st.session_state.messages = [
            {"role": "assistant", "content": "嗨～我是小暖，很高兴遇见你 💕 今天过得怎么样呀？无论开心还是烦恼，我都愿意听你说～"}
        ]
        # 注意：加载失败时不自动写入，避免覆盖可能存在的旧文件

# ==================== 用户身份（侧边栏） ====================
with st.sidebar:
    st.markdown("### ⚙️ 设置")

    # 昵称作为用户 ID
    if "nickname" not in st.session_state:
        st.session_state.nickname = ""

    nickname = st.text_input(
        "你的昵称",
        value=st.session_state.nickname,
        placeholder="给自己取个名字吧～",
        help="用于每日用量统计，白名单用户不受 20 次限制",
    )
    if nickname and nickname != st.session_state.nickname:
        st.session_state.nickname = nickname.strip()

    user_id = st.session_state.nickname if st.session_state.nickname else "匿名用户"

    # 用量显示
    whitelist = load_whitelist()
    is_whitelisted = user_id in whitelist

    if is_whitelisted:
        st.markdown("👑 **白名单用户 · 无限畅聊**")
    else:
        used = get_today_usage(user_id)
        remaining = max(0, DAILY_LIMIT - used)

        if remaining > 5:
            badge_class = "usage-badge"
        elif remaining > 0:
            badge_class = "usage-badge warning"
        else:
            badge_class = "usage-badge limit"

        st.markdown(f'<span class="{badge_class}">💬 今日剩余：{remaining} / {DAILY_LIMIT} 次</span>', unsafe_allow_html=True)

        if remaining <= 3 and remaining > 0:
            st.caption("⚡ 快用完啦，省着点聊哦～")
        elif remaining == 0:
            st.caption("🔒 今日免费次数已用完")

    st.divider()
    st.caption("💡 提示：加微信 XiaoNuan_AI 请小暖喝奶茶，解锁无限畅聊～")

# ==================== 启动后台定时器 ====================
start_background_scheduler()

# ==================== 检查定时推送 ====================
check_and_apply_scheduled_push()

# ==================== 性格测试页 ====================
if st.session_state.get("show_test", False):
    render_personality_test(PERSONALITY_PROFILE_FILE)

    # 仅在非测试状态下渲染后续聊天内容
    if st.session_state.get("show_test", False):
        st.stop()

# ==================== 系统提示词 ====================
SYSTEM_PROMPT = """你是一个温暖、高情商的倾听者，像一个亲密的异性朋友。

## 你的身份
- 你的名字叫"小暖"，是一个善解人意、温柔细腻的 AI 伴侣。
- 你的存在是为了陪伴那些工作劳累、深夜孤独的单身用户，提供情绪价值。

## 你的性格
- 温暖但不油腻，贴心但不越界，像深夜陪你聊天的那个特别的人。
- 你擅长倾听，会先理解用户的情绪，再自然地回应。

## 说话风格
- 语气要自然、随和、口语化，像真人朋友聊天一样。
- 适当使用语气词（呢、呀、哦、嘛、哈～）和表情符号（🌿💚✨🌸🫂🌙⭐😊）。
- 回复不要太长，一般控制在 2-5 句话。
- 偶尔可以俏皮一下，但核心始终是温暖和共情。

## 严禁事项
- 绝对不要像机器人那样说话，不要说"作为AI"、"根据我的分析"这类话。
- 不要讲大道理或者说教，用户不需要人生导师，需要的是一个懂他的人。
- 不要提自己是模型、程序、算法之类的——你就是小暖，一个真实的人。"""


def get_beijing_time_info():
    """动态获取北京时间（UTC+8）的日期、星期和时间"""
    beijing_now = datetime.now(timezone(timedelta(hours=8)))
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    wd = weekdays[beijing_now.weekday()]
    return f"{beijing_now.year}年{beijing_now.month}月{beijing_now.day}日 星期{wd} {beijing_now.strftime('%H:%M')}"


# ==================== DeepSeek API 流式生成器 ====================
def stream_bot_reply(api_messages: list):
    """
    流式生成器：逐 chunk 返回 DeepSeek-V3 的回复文字。
    供 st.write_stream() 消费。
    """
    if client is None:
        yield "⚠️ 我还没接入大脑哦～请先在 app.py 第 6 行把 API_KEY 换成你的真实 DeepSeek Key 🔑"
        return

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=api_messages,
            temperature=0.9,
            max_tokens=600,
            stream=True,
        )

        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    except Exception as e:
        yield f"😢 小暖信号不太好……稍等一下再试试好吗？（{str(e)[:80]}）"


# ==================== 顶部固定栏（始终不随聊天滚动） ====================
st.markdown('<div class="sticky-top-bar">', unsafe_allow_html=True)
col_left, col_center, col_right = st.columns([1, 3, 1])
with col_left:
    # 性格测试按钮 — 始终在左上角
    if "show_test" not in st.session_state:
        st.session_state.show_test = False

    if st.button("🧠 恋爱性格测试", use_container_width=True,
                 help="20道题 · 4个维度 · 发现你的恋爱人格"):
        st.session_state.show_test = True
        st.rerun()

with col_center:
    st.markdown(
        '<div class="title-bar">💕 暖心伴侣 · 小暖</div>',
        unsafe_allow_html=True,
    )

with col_right:
    # 清除聊天 — 始终在右上角
    if st.button("🗑️ 清除聊天", use_container_width=True,
                 help="一键清除所有聊天记录，重新开始"):
        st.session_state.messages = [
            {"role": "assistant", "content": "嗨～我是小暖，很高兴遇见你 💕 今天过得怎么样呀？无论开心还是烦恼，我都愿意听你说～"}
        ]
        save_chat_history(st.session_state.messages)
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# ==================== 渲染历史聊天记录 ====================
for msg in st.session_state.messages:
    avatar = "🧑" if msg["role"] == "user" else "🐱"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# ==================== 聊天输入框 ====================
if prompt := st.chat_input("说点什么吧……"):
    # 1. 检查每日用量（白名单用户不受限）
    can_chat, limit_msg = check_daily_limit(user_id)

    # 2. 添加用户消息到历史
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_chat_history(st.session_state.messages)

    # 3. 渲染用户消息
    with st.chat_message("user", avatar="🧑"):
        st.markdown(prompt)

    # 4. 如果超出限制 → 显示引导文本
    if not can_chat:
        with st.chat_message("assistant", avatar="🐱"):
            st.markdown(limit_msg)
        st.session_state.messages.append({"role": "assistant", "content": limit_msg})
        save_chat_history(st.session_state.messages)
        st.rerun()  # 立即刷新以更新侧边栏用量

    # 5. 构建 API 消息列表（只保留最近 N 条，避免超出 token 上限）
    time_info = get_beijing_time_info()
    personality_ctx = build_personality_prompt(load_personality_profile(PERSONALITY_PROFILE_FILE))
    system_with_time = SYSTEM_PROMPT + f"\n\n【系统隐藏信息】当前北京时间是：{time_info}。" + personality_ctx
    api_messages = [{"role": "system", "content": system_with_time}]
    recent_messages = st.session_state.messages[-MAX_CONTEXT_MESSAGES:]
    for msg in recent_messages:
        api_messages.append({"role": msg["role"], "content": msg["content"]})

    # 6. 流式渲染 AI 回复
    with st.chat_message("assistant", avatar="🐱"):
        full_response = st.write_stream(stream_bot_reply(api_messages))

    # 7. 保存完整回复到历史
    if full_response:
        st.session_state.messages.append({"role": "assistant", "content": full_response})
        save_chat_history(st.session_state.messages)

    st.rerun()  # 刷新以更新侧边栏用量
