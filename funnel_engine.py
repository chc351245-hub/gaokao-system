"""
================================================================================
 三层递进漏斗推荐引擎 v6.0 — Funnel Engine
================================================================================
 核心算法：
   Layer 1：学科门类初筛 — 认知风格 + 人格倾向 → 13 个门类匹配分
   Layer 2：专业类精选 — 产业 + 资产 + 分数 → Top 8 硬截断
   Layer 3：专业微观狙击 — 微观动作 + 热度 + 红线 → ≤6/类硬截断

  Layer 3 公式（用户确认）：
   score = (micro_match × 0.6 + heat_align × 0.4) × threshold_pass
   threshold_pass ∈ {0, 1} → 红线触发则直接归零
================================================================================
"""

import json
import math
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import openpyxl

from user_profile import (
    UserProfile,
    BEHAVIOR_DIMENSIONS,
)

# ============================================================================
# 路径配置
# ============================================================================
BASE_DIR = Path(__file__).parent
CHECKPOINT_DIR = BASE_DIR / "label_checkpoints"
MAJORS_XLSX = BASE_DIR / "gaokao_majors.xlsx"

# ============================================================================
# 标签 → 向量映射表（将分类标签转为数值向量用于余弦匹配）
# ============================================================================

# 认知风格 → 10 维行为向量
COGNITIVE_STYLE_TO_BEHAVIOR: dict[str, dict[str, float]] = {
    "系统建构":    {"逻辑推理": 0.60, "精细操作": 0.40},
    "逻辑推演":    {"逻辑推理": 0.70, "数据敏感": 0.30},
    "空间想象":    {"创造性思维": 0.50, "动手实验": 0.50},
    "语言敏感":    {"沟通表达": 0.60, "记忆积累": 0.40},
    "抽象思辨":    {"逻辑推理": 0.50, "创造性思维": 0.50},
    "共情表达":    {"沟通表达": 0.60, "团队协作": 0.40},
    "数据敏感":    {"数据敏感": 0.60, "逻辑推理": 0.40},
    "实验思维":    {"动手实验": 0.60, "逻辑推理": 0.40},
    "归纳推理":    {"逻辑推理": 0.50, "数据敏感": 0.50},
    "动手实践":    {"动手实验": 0.60, "精细操作": 0.40},
    "审美判断":    {"创造性思维": 0.60, "精细操作": 0.40},
    "社会洞察":    {"沟通表达": 0.50, "团队协作": 0.50},
    "批判思维":    {"逻辑推理": 0.60, "创造性思维": 0.40},
    "记忆积累":    {"记忆积累": 0.70, "持续专注": 0.30},
    "模式识别":    {"数据敏感": 0.50, "逻辑推理": 0.50},
    "流程管控":    {"精细操作": 0.60, "团队协作": 0.40},
    "创意发散":    {"创造性思维": 0.70, "沟通表达": 0.30},
}

# 人格倾向 → RIASEC 六维向量
PERSONA_TO_RIASEC: dict[str, dict[str, float]] = {
    "理性分析型":  {"I": 0.70, "C": 0.30},
    "动手实践型":  {"R": 0.70, "I": 0.30},
    "情感输出型":  {"A": 0.70, "S": 0.30},
    "审美直觉型":  {"A": 0.80, "I": 0.20},
    "社会服务型":  {"S": 0.80, "E": 0.20},
    "探索创新型":  {"I": 0.50, "A": 0.50},
    "规则执行型":  {"C": 0.80, "R": 0.20},
    "领导管理型":  {"E": 0.70, "S": 0.30},
    "沟通协作型":  {"S": 0.50, "E": 0.50},
    "数据驱动型":  {"I": 0.40, "C": 0.60},
}

# 微观动作 → 10 维行为向量
MICRO_ACTION_TO_BEHAVIOR: dict[str, dict[str, float]] = {
    "Debug与迭代修复":          {"逻辑推理": 0.50, "动手实验": 0.30, "持续专注": 0.20},
    "系统架构设计":             {"逻辑推理": 0.50, "创造性思维": 0.30, "精细操作": 0.20},
    "代码编写与Review":         {"逻辑推理": 0.40, "精细操作": 0.40, "团队协作": 0.20},
    "数据分析与统计建模":       {"数据敏感": 0.50, "逻辑推理": 0.50},
    "机器学习模型训练":         {"数据敏感": 0.40, "逻辑推理": 0.30, "动手实验": 0.30},
    "数据库设计与优化":         {"逻辑推理": 0.40, "精细操作": 0.40, "数据敏感": 0.20},
    "实验设计与执行":           {"动手实验": 0.50, "逻辑推理": 0.30, "精细操作": 0.20},
    "文献检索与综述撰写":       {"记忆积累": 0.40, "逻辑推理": 0.30, "持续专注": 0.30},
    "田野调查与访谈":           {"沟通表达": 0.50, "团队协作": 0.30, "抗压能力": 0.20},
    "临床诊断与鉴别":           {"逻辑推理": 0.50, "记忆积累": 0.30, "精细操作": 0.20},
    "手术/介入操作":            {"动手实验": 0.50, "精细操作": 0.30, "抗压能力": 0.20},
    "医学影像判读":             {"数据敏感": 0.40, "精细操作": 0.30, "记忆积累": 0.30},
    "法律文书起草与审查":       {"逻辑推理": 0.40, "沟通表达": 0.30, "记忆积累": 0.30},
    "庭审辩论与质证":           {"沟通表达": 0.50, "逻辑推理": 0.30, "抗压能力": 0.20},
    "合同谈判与尽调":           {"沟通表达": 0.40, "数据敏感": 0.30, "逻辑推理": 0.30},
    "财务报表编制与分析":       {"数据敏感": 0.50, "精细操作": 0.30, "逻辑推理": 0.20},
    "风险评估与量化":           {"数据敏感": 0.50, "逻辑推理": 0.50},
    "审计底稿编制":             {"精细操作": 0.50, "数据敏感": 0.30, "记忆积累": 0.20},
    "教学设计/教案编写":        {"创造性思维": 0.40, "沟通表达": 0.30, "记忆积累": 0.30},
    "课堂讲授与互动":           {"沟通表达": 0.60, "团队协作": 0.20, "创造性思维": 0.20},
    "课堂教学与互动":           {"沟通表达": 0.60, "团队协作": 0.20, "创造性思维": 0.20},
    "学生心理辅导":             {"沟通表达": 0.50, "团队协作": 0.30, "记忆积累": 0.20},
    "素描/色彩/造型创作":       {"创造性思维": 0.50, "动手实验": 0.30, "精细操作": 0.20},
    "软件UI/UX设计":            {"创造性思维": 0.40, "精细操作": 0.30, "沟通表达": 0.30},
    "三维建模与渲染":           {"动手实验": 0.40, "创造性思维": 0.30, "精细操作": 0.30},
    "乐器演奏/声乐训练":        {"动手实验": 0.40, "精细操作": 0.30, "记忆积累": 0.30},
    "剧本分析与表演创作":       {"创造性思维": 0.40, "沟通表达": 0.40, "记忆积累": 0.20},
    "镜头语言与剪辑":           {"创造性思维": 0.50, "精细操作": 0.30, "数据敏感": 0.20},
    "体能训练与运动康复":       {"动手实验": 0.50, "持续专注": 0.30, "记忆积累": 0.20},
    "竞赛战术制定":             {"逻辑推理": 0.40, "数据敏感": 0.30, "团队协作": 0.30},
    "运动生物力学分析":         {"数据敏感": 0.40, "逻辑推理": 0.30, "动手实验": 0.30},
    "工程制图/CAD建模":         {"动手实验": 0.40, "精细操作": 0.30, "创造性思维": 0.30},
    "电路设计与PCB布局":        {"逻辑推理": 0.40, "动手实验": 0.30, "精细操作": 0.30},
    "嵌入式系统开发":           {"逻辑推理": 0.40, "动手实验": 0.40, "精细操作": 0.20},
    "化学合成与分离纯化":       {"动手实验": 0.50, "精细操作": 0.30, "持续专注": 0.20},
    "色谱/光谱分析":            {"数据敏感": 0.40, "精细操作": 0.30, "逻辑推理": 0.30},
    "材料性能测试":             {"动手实验": 0.40, "数据敏感": 0.30, "精细操作": 0.30},
    "环境采样与监测":           {"动手实验": 0.40, "数据敏感": 0.30, "持续专注": 0.30},
    "环评报告编制":             {"逻辑推理": 0.30, "沟通表达": 0.30, "记忆积累": 0.40},
    "生态修复方案设计":         {"创造性思维": 0.40, "逻辑推理": 0.30, "动手实验": 0.30},
    "政策文本分析与解读":       {"逻辑推理": 0.50, "沟通表达": 0.30, "记忆积累": 0.20},
    "新闻采访与稿件撰写":       {"沟通表达": 0.50, "记忆积累": 0.30, "创造性思维": 0.20},
    "多语种翻译与本地化":       {"记忆积累": 0.50, "沟通表达": 0.30, "精细操作": 0.20},
    "用户需求调研与访谈":       {"沟通表达": 0.50, "团队协作": 0.30, "数据敏感": 0.20},
    "产品原型设计与迭代":       {"创造性思维": 0.50, "动手实验": 0.30, "团队协作": 0.20},
    "A/B测试与增长实验":        {"数据敏感": 0.50, "逻辑推理": 0.30, "创造性思维": 0.20},
    "芯片版图设计":             {"精细操作": 0.40, "逻辑推理": 0.30, "动手实验": 0.30},
    "信号完整性分析":           {"逻辑推理": 0.50, "数据敏感": 0.30, "精细操作": 0.20},
    "射频调试与匹配":           {"动手实验": 0.50, "逻辑推理": 0.30, "数据敏感": 0.20},
    "工地现场管理与监理":       {"团队协作": 0.40, "抗压能力": 0.30, "精细操作": 0.30},
    "结构力学计算与分析":       {"逻辑推理": 0.50, "数据敏感": 0.50},
    "造价预算编制":             {"数据敏感": 0.50, "精细操作": 0.30, "记忆积累": 0.20},
    "临床护理操作":             {"动手实验": 0.40, "精细操作": 0.30, "沟通表达": 0.30},
    "康复训练方案制定":         {"创造性思维": 0.40, "沟通表达": 0.30, "动手实验": 0.30},
    "公共卫生流行病学调查":     {"数据敏感": 0.40, "逻辑推理": 0.30, "团队协作": 0.30},
}

# ---------------------------------------------------------------------------
# 【已删除】INDUSTRY_TAG_TO_CLUSTER / UNMAPPED_INDUSTRY_TAGS
#
# 这里原本有一张「33 个产业标签 → 10 个产业集群」的多对一映射表：用户向量是 10 维、
# 专业类的标签有 33 个，靠这张表对齐。它是本引擎两个长期缺陷的共同根源：
#
#   · 「政府公共」吞并了 法律服务/合规、科研/学术、军事/国防工业、房地产/物业，
#     一个维度覆盖 50/93 = 53.8% 的专业类，几乎不携带区分信息；
#   · 「智能制造」吞并了 物流/供应链、建筑/土木/城规、航空航天、海洋工程/船舶，
#     使「物流管理与工程类」凭空继承两个最热门的集群——实测 300 份随机答卷里
#     16 份把它推为第一名、92 份进 Top8，而它真实的去向（物流/供应链）
#     从头到尾没参与过打分。
#
# 中间做过一轮症状修复（把这 5 个错配标签排除出映射表）：物流确实降下去了，但代价是
# 这些方向对**所有**用户恒为 0——因为问卷当时根本无法表达它们（用户向量只有 10 维，
# M1-M10 没有一题问得到物流/建筑/航空航天）。拿假阳性换假阴性只是权宜。
#
# 现在：用户向量与专业类标签共用同一套 33 维词表（user_profile.INDUSTRY_DIMENSIONS），
# 问卷也补上了能表达这些方向的 M11。映射层因此被**彻底删除**——专业类的
# industry_map 标签直接就是用户向量的键，不需要任何转换。
# 新增产业方向时，只需同时更新 INDUSTRY_DIMENSIONS 与相关题目的 industry_weights。
# ---------------------------------------------------------------------------

# 热度匹配：风险容忍度 → 社会热度的匹配分
# 行：风险容忍度等级，列：社会热度等级
HEAT_ALIGNMENT_MATRIX: dict[str, dict[str, float]] = {
    # 高风险容忍 → 喜欢追风口，极高/高热 = 高分
    "high":    {"极高": 1.0, "高": 0.9, "中": 0.5, "低": 0.2},
    # 中风险容忍 → 适中，匹配高/中 = 高分
    "medium":  {"极高": 0.6, "高": 0.8, "中": 1.0, "低": 0.5},
    # 低风险容忍 → 追求稳定，低/中热 = 高分
    "low":     {"极高": 0.2, "高": 0.4, "中": 0.8, "低": 1.0},
}

# 资产敏感度匹配：家庭经济水平 → 资产敏感度的匹配分
# 行：经济水平，列：资产敏感度
ASSET_ALIGNMENT_MATRIX: dict[str, dict[str, float]] = {
    # 高经济水平 → 高敏感也能驾驭
    "高":  {"低": 0.7, "中": 0.9, "高": 1.0},
    # 中经济水平 → 低/中敏感合适
    "中":  {"低": 1.0, "中": 0.9, "高": 0.5},
    # 低经济水平 → 低敏感最友好
    "低":  {"低": 1.0, "中": 0.6, "高": 0.2},
}

# 分数敏感度匹配：排名百分位 → 分数敏感度的匹配分
# 行：排名分位，列：分数敏感度
SCORE_ALIGNMENT_MATRIX: dict[str, dict[str, float]] = {
    # 前10% → 顶级排名，极高敏感也能打
    "top":       {"极高": 1.0, "高": 1.0, "中": 0.6, "低": 0.3},
    # 前10-30% → 中上排名
    "upper":     {"极高": 0.6, "高": 0.9, "中": 0.9, "低": 0.4},
    # 前30-60% → 中等排名
    "middle":    {"极高": 0.3, "高": 0.5, "中": 0.9, "低": 0.8},
    # 前60-100% → 中低排名
    "lower":     {"极高": 0.1, "高": 0.3, "中": 0.6, "低": 1.0},
}


# 用户核心产业意向的判定比例：达到个人峰值该比例以上的产业集群，视为"核心意向"。
# 用相对峰值而非绝对阈值，是因为不同用户的意向强度天然不同（实测随机答卷峰值
# 均值 57、个别用户可达 90+），但"他最想要的那几个方向"这件事是可比的。
INDUSTRY_PEAK_RATIO = 0.65


def _rank_tier(percentile: float) -> str:
    if percentile <= 10:
        return "top"
    elif percentile <= 30:
        return "upper"
    elif percentile <= 60:
        return "middle"
    else:
        return "lower"


def get_top_industries(user: UserProfile) -> set[str]:
    """
    用户的核心产业意向集 = 产业向量中达到个人峰值 INDUSTRY_PEAK_RATIO 以上的集群。

    抽成独立函数是为了让 Layer 2 的筛选和推荐理由的生成共用同一定义，
    避免两处各自维护阈值导致口径漂移。
    """
    iv = user.macro_industry_vector or {}
    peak = max(iv.values()) if iv else 0.0
    if peak <= 0:
        return set()
    return {ind for ind, score in iv.items() if score >= peak * INDUSTRY_PEAK_RATIO}


# 风险容忍度分档阈值（绝对值，基于 questionnaire.py 的「按维度各自归一化」）
# 归一化修复后实测：随机答卷均值 50.7、中位 50.0、范围 0~100；
# 直接答"高风险偏好"(M6=D, M8=A) 的用户得 78.6，答"低风险偏好"(M6=A, M8=B) 的得 0.0。
# 所以 65/35 能把三类人分开，而不是像原来那样把 86% 的人塞进同一档。
RISK_TIER_HIGH = 65.0
RISK_TIER_MEDIUM = 35.0


def _risk_tier(user: UserProfile) -> str:
    """
    根据风险容忍度的绝对水平判断风险偏好档位。

    为什么不再用「相对最大值」：原实现拿 风险容忍度 / max(五个价值维度) 做判定。
    但那五个维度共享同一个分母、总分恒为 100，而"风险容忍度"在选项权重里出现得
    本来就少（只有 M6/M7/M8/M10 涉及），于是它天然垫底——实测 500 份答卷里
    high 出现 0 次、low 占 432 次，HEAT_ALIGNMENT_MATRIX 的 high 行成了死代码，
    heat_align（占 Layer 3 分数的 40%）退化成「社会热度的固定查表」。
    现在归一化改成按维度各自的上限，这里的绝对阈值才有意义。
    """
    risk_tolerance = user.macro_value_vector.get("风险容忍度", 50.0)
    if risk_tolerance >= RISK_TIER_HIGH:
        return "high"
    elif risk_tolerance >= RISK_TIER_MEDIUM:
        return "medium"
    else:
        return "low"


# 招生体量 → 市场容量系数
#
# 注意：这个系数乘在 Layer 3 总分上，所以它的摆幅必须显著小于 micro_match 的
# 真实区分度。原表摆幅是 0.70~1.15（相差 64%），而 883 个专业里 440 个是"极小"
# ——等于给一半专业无条件打了七折，比"你和这个专业合不合"影响还大。
#
# 招生体量是「就业市场容量」信息，不是「适配度」。这里把它降级为不超过 ±3% 的
# 破并列项，保留它的相对大小关系，不让它主导排序。
ENROLLMENT_CAPACITY_COEFFICIENT: dict[str, float] = {
    "极大": 1.03,
    "大":   1.015,
    "中":   1.00,
    "小":   0.985,
    "极小": 0.97,
}

# 说明：原先这里有一张 INDUSTRY_HEAT_BONUS（产业风口加成表），对 AI/半导体/新能源
# 等赛道给 1.02~1.05 的乘数。它是「专业/产业的属性」，与用户是谁无关，属于白皮书
# 1.2 节明令禁止"污染匹配分"的那类项，已从匹配分中移除。如需保留"风口"信息，
# 建议作为前端的独立展示标签，而不是参与排序。


# ============================================================================
# 工具函数
# ============================================================================

# 红线语义映射：用户自述条件 → 匹配的专业红线关键词
_THRESHOLD_SEMANTIC_MAP: dict[str, set[str]] = {
    "色盲": {"色盲", "红绿色盲", "色觉", "色弱"},   # 色盲→触发所有色觉类红线
    "色弱": {"色弱", "色觉"},                     # 色弱≠红绿色盲，只触发色弱+色觉类
    "裸眼视力<4.8": {"裸眼视力", "裸眼"},
    "身高不达标": {"身高"},
}

def _threshold_match(user_condition: str, major_threshold: str) -> bool:
    """检查用户身体条件是否触发专业的红线（语义匹配）"""
    # 语义扩展匹配
    expanded = _THRESHOLD_SEMANTIC_MAP.get(user_condition, {user_condition})
    for keyword in expanded:
        if keyword in major_threshold:
            return True
    # 兜底：用户条件作为专业红线的子串
    if user_condition in major_threshold:
        return True
    return False


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度，钳位到 [0, 1]"""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def tags_to_vector(
    tags: list[str],
    mapping: dict[str, dict[str, float]],
    dims: list[str],
) -> list[float]:
    """
    将标签列表通过映射表转换为向量。

    说明：本函数的所有调用方都用余弦相似度做比对，而余弦对向量的整体缩放不敏感，
    所以这里不做"除以标签数量"的归一化——那一步在数学上是空操作，只会让人误以为
    它影响结果。真正决定对比结果的是各维度之间的相对比例。

    归一化例外：无可用标签时必须返回零向量。原实现返回 [0.5] * len(dims)，而它与
    典型用户向量的余弦高达 0.86，会让一个完全没有标签数据的专业拿到接近满分的匹配。
    """
    vec = {d: 0.0 for d in dims}
    for tag in tags:
        if tag in mapping:
            for dim, weight in mapping[tag].items():
                if dim in vec:
                    vec[dim] += weight
    return [vec[d] for d in dims]


# ============================================================================
# 数据加载
# ============================================================================

@dataclass
class FunnelData:
    """三层漏斗数据结构"""
    disciplines: dict[str, dict] = field(default_factory=dict)
    categories: dict[str, dict] = field(default_factory=dict)
    majors: list[dict] = field(default_factory=list)
    # 索引
    _cat_to_disc: dict[str, str] = field(default_factory=dict)
    _cat_to_majors: dict[str, list[dict]] = field(default_factory=dict)

    def get_majors_in_category(self, category: str) -> list[dict]:
        return self._cat_to_majors.get(category, [])

    def get_discipline(self, category: str) -> str:
        return self._cat_to_disc.get(category, "")


def load_funnel_data() -> FunnelData:
    """加载三层标签数据"""
    data = FunnelData()
    errors = []

    # Layer 1: 学科门类
    l1_path = CHECKPOINT_DIR / "layer1_disciplines.json"
    if l1_path.exists():
        with open(l1_path, "r", encoding="utf-8") as f:
            data.disciplines = json.load(f)
    else:
        errors.append(f"L1 missing: {l1_path}")

    # Layer 2: 专业类
    l2_path = CHECKPOINT_DIR / "layer2_categories.json"
    if l2_path.exists():
        with open(l2_path, "r", encoding="utf-8") as f:
            data.categories = json.load(f)
    else:
        errors.append(f"L2 missing: {l2_path}")

    # Layer 3: 从 JSON 加载标签
    l3_path = CHECKPOINT_DIR / "layer3_majors.json"
    l3_data = {}
    if l3_path.exists():
        with open(l3_path, "r", encoding="utf-8") as f:
            l3_data = json.load(f)
    else:
        errors.append(f"L3 missing: {l3_path}")

    # 从 Excel 读取专业元数据
    if not MAJORS_XLSX.exists():
        errors.append(f"Excel missing: {MAJORS_XLSX}")
    else:
        wb = openpyxl.load_workbook(MAJORS_XLSX)
        ws = wb[wb.sheetnames[0]]
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
            seq, discipline, category, code, name = row
            if not category or str(category).strip() in ("", "-"):
                category = "交叉类"
            category = str(category).strip()
            discipline = str(discipline).strip() if discipline else ""
            code = str(code).strip() if code else ""
            name = str(name).strip() if name else ""

            major_entry = {
                "seq": seq,
                "discipline": discipline,
                "category": category,
                "code": code,
                "name": name,
                "micro_actions": l3_data.get(name, {}).get("micro_actions", []),
                "hard_threshold": l3_data.get(name, {}).get("hard_threshold", []),
                "social_heat": l3_data.get(name, {}).get("social_heat", "中"),
                "heat_trend": l3_data.get(name, {}).get("heat_trend", "平稳"),
                "enrollment_volume": l3_data.get(name, {}).get("enrollment_volume", "中"),
            }
            data.majors.append(major_entry)
            data._cat_to_disc[category] = discipline
            if category not in data._cat_to_majors:
                data._cat_to_majors[category] = []
            data._cat_to_majors[category].append(major_entry)

    # 校验
    data._load_errors = errors
    if not data.disciplines:
        print(f"[WARN] load_funnel_data: 0 disciplines loaded!")
    if not data.categories:
        print(f"[WARN] load_funnel_data: 0 categories loaded!")
    if not data.majors:
        print(f"[WARN] load_funnel_data: 0 majors loaded!")
    if errors:
        print(f"[WARN] load_funnel_data errors: {errors}")

    return data


# ============================================================================
# ============================================================================
# 专业类 → 新高考选科要求（Layer 2 精确校验）
# ============================================================================
# 每个专业类的必选科目。用户不满足 → 该专业类直接归零。
# 空集合表示不限选科。
# 数据来源：教育部《普通高校本科招生专业选考科目要求指引》
# ============================================================================

CATEGORY_SUBJECT_REQUIREMENTS: dict[str, set[str]] = {
    # ===== 医学类 =====
    "临床医学类":               {"物理", "化学"},
    "口腔医学类":               {"物理", "化学"},
    "基础医学类":               {"物理", "化学"},
    "中西医结合类":             {"物理", "化学"},
    "法医学类":                 {"物理", "化学"},
    "中医学类":                 {"物理"},
    "中药学类":                 {"化学"},
    "药学类":                   {"化学"},
    "医学技术类":               {"物理"},
    "公共卫生与预防医学类":     {"物理"},
    "护理学类":                 set(),

    # ===== 工学类 =====
    "计算机类":                 {"物理"},
    "电子信息类":               {"物理"},
    "自动化类":                 {"物理"},
    "电气类":                   {"物理"},
    "机械类":                   {"物理"},
    "土木类":                   {"物理"},
    "建筑类":                   {"物理"},
    "航空航天类":               {"物理"},
    "核工程类":                 {"物理"},
    "兵器类":                   {"物理"},
    "交通运输类":               {"物理"},
    "仪器类":                   {"物理"},
    "力学类":                   {"物理"},
    "测绘类":                   {"物理"},
    "安全科学与工程类":         {"物理"},
    "工业工程类":               {"物理"},
    "海洋工程类":               {"物理"},
    "水利类":                   {"物理"},
    "矿业类":                   {"物理"},
    "地质类":                   {"物理"},
    "农业工程类":               {"物理"},
    "林业工程类":               {"物理"},
    "公安技术类":               {"物理"},
    "能源动力类":               {"物理"},
    "生物医学工程类":           {"物理"},
    "环境科学与工程类":         {"物理"},
    # 物理 + 化学 双锁
    "材料类":                   {"物理", "化学"},
    "化工与制药类":             {"物理", "化学"},
    "纺织类":                   {"物理", "化学"},
    "轻工类":                   {"物理", "化学"},
    "生物工程类":               {"物理", "化学"},
    "食品科学与工程类":         {"物理", "化学"},

    # ===== 理学类 =====
    "数学类":                   {"物理"},
    "物理学类":                 {"物理"},
    "化学类":                   {"物理", "化学"},
    "天文学类":                 {"物理"},
    "大气科学类":               {"物理"},
    "海洋科学类":               {"物理"},
    "地球物理学类":             {"物理"},
    "地质学类":                 {"物理"},
    "生物科学类":               {"物理", "化学"},
    "统计学类":                 {"物理"},
    "心理学类":                 set(),
    "地理科学类":               {"地理"},

    # ===== 农学类 =====
    "植物生产类":               {"化学"},
    "动物生产类":               {"化学"},
    "动物医学类":               {"物理", "化学"},
    "林学类":                   {"化学"},
    "水产类":                   {"化学"},
    "草学类":                   {"化学"},
    "自然保护与环境生态类":     {"化学"},

    # ===== 交叉学科 =====
    "交叉类":                   {"物理"},
}


# ============================================================================
# 特殊赛道 → 专业类映射（Layer 2 使用）
# ============================================================================

MEDICAL_CATEGORIES = {
    "临床医学类", "口腔医学类", "基础医学类", "中医学类", "中西医结合类",
    "药学类", "中药学类", "法医学类", "医学技术类", "护理学类",
    "公共卫生与预防医学类",
}

TEACHING_CATEGORIES = {
    "教育学类", "体育学类",
}

MILITARY_POLICE_CATEGORIES = {
    "公安学类", "公安技术类", "兵器类",
}

# 军警体检红线
MILITARY_PHYSICAL_RED_LINES = {"身高不达标", "裸眼视力<4.8"}


# ============================================================================
# Layer 1: 学科门类匹配
# ============================================================================

def layer1_discipline_match(user: UserProfile, data: FunnelData) -> list[dict]:
    """
    第一层：学科门类初筛（纯认知风格 + 人格倾向，不做选科过滤）

    score = cosine(behavior, disc_cognitive) × 0.5
          + cosine(personality, disc_persona) × 0.3
          + discipline_weight × 0.2

    选科校验下沉到 Layer 2（专业类级别精确匹配）。
    """
    # 用户向量
    user_behavior = [user.micro_behavior_vector.get(d, 50.0) / 100.0 for d in BEHAVIOR_DIMENSIONS]
    riasec_dims = ["R", "I", "A", "S", "E", "C"]
    user_personality = [user.inferred_personality.get(d, 50.0) / 100.0 for d in riasec_dims]

    results = []
    for disc_name, disc_labels in data.disciplines.items():
        cognitive_tags = disc_labels.get("cognitive_style", [])
        persona_tags = disc_labels.get("persona_tendency", [])
        disc_weight = disc_labels.get("discipline_weight", 0.5)

        # 标签 → 向量
        disc_cognitive_vec = tags_to_vector(cognitive_tags, COGNITIVE_STYLE_TO_BEHAVIOR, BEHAVIOR_DIMENSIONS)
        disc_persona_vec = tags_to_vector(persona_tags, PERSONA_TO_RIASEC, riasec_dims)

        cog_sim = cosine_similarity(user_behavior, disc_cognitive_vec)
        per_sim = cosine_similarity(user_personality, disc_persona_vec)

        # 认知:人格 = 50:30 的相对比例保持不变，去掉静态项后重新归一化到 0~1。
        # 去掉了原来的 `+ disc_weight * 0.2`：discipline_weight 是一个写死的
        # 「学科就业前景」排序（工学 0.92 / 医学 0.6 / 艺术学 0.4 / 哲学 0.25），
        # 对每个用户固定贡献 0.05~0.184 分，与"这个人和这个门类合不合"无关，
        # 属于白皮书 1.2 节禁止混入匹配分的那类项。
        # discipline_weight 仍保留在返回值里供前端展示，但不参与打分。
        score = cog_sim * 0.625 + per_sim * 0.375

        results.append({
            "discipline_name": disc_name,
            "cognitive_sim": round(cog_sim, 4),
            "persona_sim": round(per_sim, 4),
            "weight_bonus": round(disc_weight, 4),  # 仅供展示，不参与打分
            "score": round(score, 4),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ============================================================================
# Layer 2: 专业类精选（Top 8 硬截断）
# ============================================================================

def layer2_category_match(
    user: UserProfile,
    data: FunnelData,
    l1_results: list[dict],
    top_n: int = 8,
) -> list[dict]:
    """
    第二层：专业类精选
    匹配产业向往 + 资产敏感度 + 分数敏感度 → Top N 截断

    1. 选科硬校验：不满足 CATEGORY_SUBJECT_REQUIREMENTS → 直接跳过
    2. score = industry_match × 0.5 + asset_match × 0.2 + score_match × 0.3
    3. × 产业热度微调 + 选科匹配加成(+3%/科) + L1门类传导(±25%)
    """
    # ---- 用户核心产业 ----
    top_industries = get_top_industries(user)
    iv = user.macro_industry_vector or {}
    # 注意：原实现在 top_industries 为空时硬编码兜底为 {"互联网与软件"}，且因为
    # 旧的归一化让 >=60 永远打不到，这个兜底 100% 命中——等于给所有用户都安上了
    # 同一个互联网偏好。现在如实反映"这个用户确实没有明显产业倾向"：
    # 意向集为空 → 每个专业类的产业覆盖度都是 0 → 产业项对所有专业类是同一个常数，
    # 自然失去区分力，由资产/分数项决定排序。这是正确的退化行为。

    rank_tier = _rank_tier(user.estimated_rank_percentile)
    econ_level = user.family_economic_level  # "高"/"中"/"低"
    # 说明：原来这里算了一个 risk_tier 却从未在 Layer 2 中使用（死代码），已删除。
    # risk_tier 只在 Layer 3 的 heat_align 里使用。

    # 构建 L1 的门类得分查找表
    disc_scores = {d["discipline_name"]: d["score"] for d in l1_results}

    results = []
    user_subjects = set(user.selected_subjects)
    for cat_name, cat_labels in data.categories.items():
        disc_name = data.get_discipline(cat_name)

        # ---- subject_check：新高考选科硬要求 ----
        required_subjects = CATEGORY_SUBJECT_REQUIREMENTS.get(cat_name)
        if required_subjects and not required_subjects.issubset(user_subjects):
            # 不满足该专业类的选科要求 → 直接跳过
            continue

        # --- industry_match：用户产业意向被该专业类覆盖的比例 ---
        # 专业类的 industry_map 标签与用户向量的键**是同一套 33 维词表**
        # （user_profile.INDUSTRY_DIMENSIONS），因此这里不需要任何映射或转换。
        ind_dims = cat_labels.get("industry_map", [])
        #
        # 标签直接作为查找键，不存在的键 iv.get(..., 0.0) 记 0 分——这是有意的：
        # 一个专业类挂着的每条出路（哪怕用户完全没兴趣）都要留在分母里。**去掉一个 0
        # 会抬高均值**：早期版本把未映射的标签直接丢弃，实测「建筑类」在传媒画像下
        # 从 0.678 虚高到 0.830，一个建筑专业压过了中国语言文学类跃居第一。
        # 同理，industry_map 里若出现没在 INDUSTRY_DIMENSIONS 登记的标签（登记遗漏），
        # 它同样记 0 并留在分母——宁可让该专业类吃亏，也不要凭空放大它的契合度。

        # 原实现用 Jaccard(len(交集)/len(并集))，而并集含「用户的全部意向产业」，
        # 于是专业类覆盖的产业越广、分母越大、得分反而越低——完全倒挂：
        #   物流管理与工程类（2条出路）0.500 > 计算机类（5条出路）0.250
        #   > 临床医学类（1条不含互联网的出路）0.000
        # 后果是医学/法学/农学/基础理学/教育学的产业项恒为 0（Layer 2 一半权重被清零），
        # 且"物流管理"成为技术爱好者的第一推荐。
        #
        # 中途曾改成 served/total_intent（求和/总意向），它修好了「恒为 0」和倒挂，
        # 但引入了相反方向的偏差：求和使**标签越多分越高**，把「这个专业类有几条
        # 出路」当成了「有多契合我」。实测（生物医药型用户，峰值=100）：
        #   临床医学类 ['医疗健康/临床']                            = 0.339
        #   基础医学类 ['医疗健康/临床','科研/学术','制药/生物技术']  = 0.527
        # 基础医学类凭空高 1.55 倍，只因为它多挂了一条「科研/学术」。而全表标签最多的
        # 心理学类（互联网/软件+教育培训+医疗健康/临床+政府/公共服务）拿到 0.702，
        # 被顶到该用户第一名——这不是契合度，这是标签广度。
        #
        # 现改为「最强出路 × 平均出路 的几何平均」。对每条出路算 意向/峰值：
        #   best  = max(意向/峰值)   —— 它最好的一条出路，是不是我最想要的
        #   mean_ = mean(意向/峰值)  —— 它整体上有多少条出路合我口味
        #   industry_match = sqrt(best * mean_)
        #
        # 为什么不用两者之一：
        #   · 只用 mean_（纯平均）：会**惩罚宽口径专业**。实测技术爱好者（峰值 AI=100）
        #     计算机类有 4 条出路 {AI 1.00, 互联网 0.68, 智能制造 0.63, 金融 0.21}
        #     → mean=0.630，反而低于只有 2 条中等出路的物流管理与工程类（0.655）。
        #     结果是计算机类被挤出 Top8、位置让给电子商务类/物流类——最典型的工科
        #     强相关专业输给了「每条出路都平庸」的专业，方向错了。
        #   · 只用 best（最强）：会**丧失区分度**。凡带"医疗健康/临床"标签的专业类全部
        #     封顶 1.000（医学画像下 10 个专业类并列），Top8 截断线无从下手。
        # 几何平均恒有 sqrt(best*mean_) ≥ mean_（因 best ≥ mean_），且 best=mean_ 时
        # 等于两者——即「每条出路都完全对口」才得满分，「有一条顶级对口出路」也不会
        # 被其余平庸出路拖垮。上界恒为 1.0，与标签数量无关，跨专业类可比。
        peak_intent = max(iv.values()) if iv else 0.0
        if ind_dims and peak_intent > 0:
            ratios = [iv.get(d, 0.0) / peak_intent for d in ind_dims]
            best_ratio = max(ratios)
            mean_ratio = sum(ratios) / len(ratios)
            industry_match = (best_ratio * mean_ratio) ** 0.5
        else:
            industry_match = 0.0

        # 特殊赛道 → 产业匹配强制拉升（用户明确意向 > 问卷推测）
        track = user.special_track_intent
        stance = user.special_track_stance
        if track and stance == "强烈意向":
            if cat_name in MEDICAL_CATEGORIES and track == "医学":
                industry_match = max(industry_match, 0.65)
            elif cat_name in TEACHING_CATEGORIES and track == "师范":
                industry_match = max(industry_match, 0.60)
            elif cat_name in MILITARY_POLICE_CATEGORIES and track == "军警":
                industry_match = max(industry_match, 0.60)

        # --- asset_match ---
        asset_sens = cat_labels.get("asset_sensitivity", "中")
        asset_match = ASSET_ALIGNMENT_MATRIX.get(econ_level, {}).get(asset_sens, 0.5)

        # --- score_match ---
        score_sens = cat_labels.get("score_sensitivity", "中")
        score_match = SCORE_ALIGNMENT_MATRIX.get(rank_tier, {}).get(score_sens, 0.5)

        # 综合得分
        score = industry_match * 0.5 + asset_match * 0.2 + score_match * 0.3

        # 已移除的两项静态加成（都只取决于专业类自身，与用户无关）：
        #   1. industry_bonus：按其产业标签给 AI/半导体/新能源 等风口 1.02~1.05 的乘数
        #   2. 选科数量加成 `1.0 + 0.03 * len(required_subjects)`：这条逻辑是反的
        #      ——选科要求越多代表门槛越高，不该反而加分（物化双锁 +6% > 单选物理 +3%）

        # ---- special_track：特殊赛道阻断与提权 ----
        track = user.special_track_intent
        stance = user.special_track_stance

        # 医学赛道
        if cat_name in MEDICAL_CATEGORIES:
            if track == "医学" and stance == "极度抗拒":
                continue  # 用户明确拒绝 → 跳过
            elif track == "医学" and stance == "强烈意向":
                score *= 1.50  # 强烈意愿 → 提权 50%

        # 师范赛道
        if cat_name in TEACHING_CATEGORIES:
            if track == "师范" and stance == "极度抗拒":
                continue
            elif track == "师范" and stance == "强烈意向":
                score *= 1.30

        # 军警赛道（必须主动且强烈选择）
        if cat_name in MILITARY_POLICE_CATEGORIES:
            if track != "军警" or stance != "强烈意向":
                continue  # 非强烈意向 → 直接跳过
            # 体检红线
            user_conds = set(user.physical_conditions)
            if user_conds & MILITARY_PHYSICAL_RED_LINES:
                continue  # 体检不通过
            score *= 1.50  # 强烈意愿 + 体检合格 → 提权 50%

        # L1 门类得分传导（±25%）：认知/人格匹配结果渗入L2
        disc_bonus = disc_scores.get(disc_name, 0.5)
        score = score * (0.75 + 0.50 * disc_bonus)

        results.append({
            "category_name": cat_name,
            "discipline_name": disc_name,
            "industry_match": round(industry_match, 4),
            "asset_match": round(asset_match, 4),
            "score_match": round(score_match, 4),
            # 不在这里做 min(1.0, ...) 截断：特殊赛道提权(×1.5/×1.3)和 L1 门类传导
            # (最高 ×1.25) 本就会把分数推过 1.0，截断会把多个"被提权的方向"压成同一个
            # 1.000，排名退化成"谁先出现在数据文件里谁靠前"。实测技术爱好者用户会出现
            # 电子信息类 1.000 与另一个类别 1.000 并列；传媒用户更是出现两个 1.000。
            # 分数只用于排序与展示，放开上限没有任何副作用。
            "score": round(score, 4),
            "labels": cat_labels,
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    # 🔴 硬截断：保留 Top N
    return results[:top_n]


# ============================================================================
# Layer 3: 专业微观狙击（≤6/类 硬截断）
# ============================================================================

def layer3_major_match(
    user: UserProfile,
    data: FunnelData,
    top_categories: list[dict],
) -> list[dict]:
    """
    第三层：专业微观狙击
    在 Top 8 专业类下计算每个专业的微观匹配，每类最多 6 个

    score = (micro_match × 0.6 + heat_align × 0.4) × threshold_pass
    """
    user_behavior = [user.micro_behavior_vector.get(d, 50.0) / 100.0 for d in BEHAVIOR_DIMENSIONS]
    user_physical = set(user.physical_conditions)
    risk_tier = _risk_tier(user)

    funnel_output = []

    for cat in top_categories:
        cat_name = cat["category_name"]
        disc_name = cat["discipline_name"]
        majors = data.get_majors_in_category(cat_name)

        major_results = []
        for major in majors:
            # --- micro_match ---
            micro_tags = major.get("micro_actions", [])
            major_behavior_vec = tags_to_vector(micro_tags, MICRO_ACTION_TO_BEHAVIOR, BEHAVIOR_DIMENSIONS)
            micro_match = cosine_similarity(user_behavior, major_behavior_vec)

            # --- heat_align ---
            social_heat = major.get("social_heat", "中")
            heat_align = HEAT_ALIGNMENT_MATRIX.get(risk_tier, {}).get(social_heat, 0.5)

            # --- threshold_pass ---
            hard_thresholds = major.get("hard_threshold", [])
            threshold_pass = 1
            triggered = []
            if hard_thresholds:
                for ht in hard_thresholds:
                    for uc in user_physical:
                        if _threshold_match(uc, ht):
                            threshold_pass = 0
                            triggered.append(ht)
                            break

            # 🔴 最终公式（含招生体量市场容量系数）
            enroll_vol = major.get("enrollment_volume", "中")
            capacity_coef = ENROLLMENT_CAPACITY_COEFFICIENT.get(enroll_vol, 1.0)
            score = (micro_match * 0.6 + heat_align * 0.4) * capacity_coef * threshold_pass

            major_results.append({
                "major_name": major["name"],
                "major_code": major["code"],
                "category_name": cat_name,
                "discipline_name": disc_name,
                "micro_match": round(micro_match, 4),
                "heat_align": round(heat_align, 4),
                "threshold_pass": bool(threshold_pass),
                "triggered_thresholds": triggered,
                "social_heat": social_heat,
                "heat_trend": major.get("heat_trend", "平稳"),
                "hard_threshold": hard_thresholds,
                "micro_actions": micro_tags,
                # 招生体量原先只被换算成 capacity_coef 参与打分，没有带进结果，
                # 于是推荐理由里想说「这专业全国招得极少」也拿不到数——而这是
                # 家长最该看到的硬信息之一。
                "enrollment_volume": enroll_vol,
                "score": round(score, 4),
            })

        # 过滤 threshold_pass=0 的专业 + 排序
        major_results = [m for m in major_results if m["threshold_pass"]]
        major_results.sort(key=lambda x: x["score"], reverse=True)

        # 🔴 硬截断：每类最多 6 个
        top_majors = major_results[:6]

        if top_majors:
            funnel_output.append({
                "category_name": cat_name,
                "discipline_name": disc_name,
                "category_score": cat["score"],
                # 三个分项必须一并带出来：下游 _reality_assessment 要靠它们把
                # 「契合度」与「现实折损」拆开展示。原先这里只传了 category_score，
                # 于是下游 .get(...) 全部落到默认值——契合度恒为 0、现实折损恒为「高」，
                # UI 上会显示成"你完全不适合，而且哪个方向都高不可攀"。
                "industry_match": cat.get("industry_match", 0.0),
                "asset_match": cat.get("asset_match", 0.5),
                "score_match": cat.get("score_match", 0.5),
                # 注意 L2 里这个字段叫 labels，L3 这里沿用 category_labels——
                # 两处命名不一致是历史遗留，_reality_assessment 读的是后者。
                "category_labels": cat["labels"],
                "recommended_majors": top_majors,
            })

    return funnel_output


# ============================================================================
# 标签与理由生成
# ============================================================================

# 「产业风口」标签的判定集合。
#
# 这里原来写着 "新能源" 和 "碳中和"——它们是**旧 10 产业集群词表的残留**，而专业类的
# industry_map 用的是 33 维标签（user_profile.INDUSTRY_DIMENSIONS），这两个字符串
# 永远不可能命中，等于白写。
#
# 修法是**删掉，而不是换成新名字**：若把它们改写成 "能源/电力/碳中和" 与
# "环保/新能源"，[产业风口] 会从 30/93 个专业类涨到 43/93，新增的是草学类、林学类、
# 自然保护与环境生态类、海洋科学类、化学类这种——标成「风口」是误导。
# 而真正该标风口的（电气类、能源动力类、材料类、机械类）本来就靠
# 新能源汽车/智能制造/航空航天 命中了，删掉不会漏。
HOT_INDUSTRY_TAGS = {
    "人工智能/大模型", "半导体/集成电路", "新能源汽车",
    "智能制造/机器人", "互联网/软件", "航空航天",
}


def _generate_category_tags(cat_labels: dict) -> list[str]:
    """专业类级别的标签——对该类下**所有**专业都是同一个值。

    这些标签原先挂在每张专业卡片上，于是一页 6 张卡片会把同一个标签重复 6 遍。
    改成在类级别说明一次：既不再复读，信息也没丢。
    """
    tags = []

    industry_tags = set(cat_labels.get("industry_map", []))
    if industry_tags & HOT_INDUSTRY_TAGS:
        tags.append("[产业风口]")

    if cat_labels.get("score_sensitivity", "中") in ("极高", "高"):
        tags.append("[高分敏感]")

    if cat_labels.get("asset_sensitivity", "中") == "低":
        tags.append("[低资源友好]")

    # 薪资潜力：数据里一直有（layer2_categories.json 的 salary_potential），
    # 但此前全引擎 0 次引用——采了没用。
    if cat_labels.get("salary_potential") in ("高", "极高"):
        tags.append("[薪资潜力高]")

    return tags


def _generate_major_tags(major: dict) -> list[str]:
    """为专业生成展示标签——只放**专业之间会不同**的维度。

    类级别的属性（产业风口/高分敏感/低资源友好/薪资潜力）见 _generate_category_tags，
    不在这里重复。
    """
    tags = []
    micro = major.get("micro_match", 0)

    if micro >= 0.85:
        tags.append("[微观极度契合]")
    elif micro >= 0.70:
        tags.append("[微观高度契合]")

    # 招生体量紧跟微观契合排在前面：它是这几个标签里最影响决策的一个
    # （「极小」= 全国只有少数院校开设，大小年波动大、调剂风险高）。
    if major.get("enrollment_volume") == "极小":
        tags.append("[招生体量极小]")

    heat = major.get("social_heat", "中")
    if heat == "极高":
        tags.append("[极度内卷]")

    if major.get("heat_trend") == "上升":
        tags.append("[热度上升]")

    return tags


def _generate_category_reason(cat: dict, user: UserProfile) -> str:
    """生成专业类级别的推荐理由"""
    parts = []

    # 产业匹配
    # 阈值按新的「覆盖度」口径标定：industry_match 现在表示"该专业类覆盖了用户
    # 多大比例的产业意向"，实测有效区间约 0.05~0.60（旧口径下这里是 0~1 的
    # Jaccard，阈值 0.7 在新口径下几乎不可能触发，会让这段理由永不出现）。
    ind_match = cat.get("industry_match", 0)
    if ind_match >= 0.35:
        top_inds = sorted(get_top_industries(user), key=lambda i: -user.macro_industry_vector.get(i, 0))
        if top_inds:
            parts.append(f"你强烈向往的{'/'.join(top_inds[:3])}赛道与此方向高度对口")
    elif ind_match >= 0.15:
        top_inds = sorted(get_top_industries(user), key=lambda i: -user.macro_industry_vector.get(i, 0))
        if top_inds:
            parts.append(f"与你关注的{'/'.join(top_inds[:2])}方向有一定衔接")

    # 资产匹配
    asset_match = cat.get("asset_match", 0)
    cat_labels = cat.get("category_labels", {})
    asset_sens = cat_labels.get("asset_sensitivity", "中")
    if asset_match >= 0.8 and asset_sens == "低":
        parts.append("该方向对家庭资源的依赖度较低，竞争更看个人能力")
    elif asset_match < 0.4:
        parts.append(f"该方向对家庭资源有一定要求（资产敏感度：{asset_sens}）")

    # 分数匹配
    score_match = cat.get("score_match", 0)
    score_sens = cat_labels.get("score_sensitivity", "中")
    if score_match >= 0.8:
        parts.append(f"你的分数位次与此方向的竞争格局匹配良好")
    elif score_match < 0.4:
        parts.append(f"注意：此方向分数竞争激烈（敏感度：{score_sens}）")

    if not parts:
        parts.append("综合多维度评估后的推荐方向")

    return "；".join(parts)


# ---------------------------------------------------------------------------
# 现实折损：把「契合度」与「现实可行度」拆成两个可独立展示的量
# ---------------------------------------------------------------------------
# 背景：`category_score = industry_match*0.5 + asset_match*0.2 + score_match*0.3`
# 是一个把「你适不适合」和「你能不能上/扛不扛得住」混在一起的数。app.py 曾经
# 直接把它当「方向匹配分」显示，同时又在下方提示「匹配分衡量你适不适合，不等同于
# 你能不能考上」——这句话对那个数不成立（它有 50% 权重不是契合度）。
#
# 白皮书§五要求：录取概率必须作为独立标签展示，让用户能分辨
# 「我适合但这个分不够」和「我不太适合」。所以这里把两者拆开输出：
#   fit_score      —— 纯契合度（industry_match），只回答「适不适合」
#   reality_tier   —— 现实折损档位，「能不能上 / 家庭扛不扛得住」的合并结论
#   reality_reason —— 一句可直接展示给人看的话
#
# 注意：**排序仍用原来的 category_score**，这次改动只增加展示用的字段，
# 不改变任何推荐结果。改排序口径是另一件事，需单独决策。
REALITY_TIER_LOW = 0.85   # asset*0.4 + score*0.6 高于此值 → 折损小
REALITY_TIER_MID = 0.65

_SCORE_SENS_PHRASE = {
    "极高": "该专业通常需要前 10% 位次，院校层级几乎决定职业高度",
    "高":   "该专业通常需要前 15% 位次，好平台影响明显",
    "中":   "该专业中分段仍可进入行业，院校差距主要体现在起点",
    "低":   "该专业各层次院校差距不大，更看个人能力",
    "极低": "该专业对院校层级不敏感，靠手艺吃饭",
}

_ASSET_SENS_PHRASE = {
    "低": "对家庭资源依赖低，主要靠个人能力",
    "中": "需要中等家庭资源支撑",
    "高": "强资源驱动，家庭条件会形成长期天花板",
}

_RANK_TIER_PHRASE = {
    "top": "前 10%", "upper": "前 10-30%",
    "middle": "前 30-60%", "lower": "前 60-100%",
}


def _reality_assessment(cat: dict, user: UserProfile) -> dict:
    """把现实折损拆成档位 + 可读理由，供 UI 独立展示（不进排序公式）"""
    asset_match = cat.get("asset_match", 0.5)
    score_match = cat.get("score_match", 0.5)
    # 兼容两种字段名：L2 的输出用 "labels"，L3 把它改名成了 "category_labels"。
    # 只认后者会让本函数在直接吃 L2 结果时静默退化成"敏感度=中"——临床医学类明明是
    # 极高敏感，却会显示成"中分段仍可进入行业"，把最该提醒的话说反。
    labels = cat.get("category_labels") or cat.get("labels") or {}
    score_sens = labels.get("score_sensitivity", "中")
    asset_sens = labels.get("asset_sensitivity", "中")

    # 分数位次是比家庭资源更硬的约束（位次当年就定死了，资源还有 4 年可变），
    # 故合并时给分数 0.6、资源 0.4。
    combined = asset_match * 0.4 + score_match * 0.6
    if combined >= REALITY_TIER_LOW:
        tier = "低"
    elif combined >= REALITY_TIER_MID:
        tier = "中"
    else:
        tier = "高"

    rank_tier = _rank_tier(getattr(user, "estimated_rank_percentile", 50.0))
    econ = getattr(user, "family_economic_level", "中")

    # 分数那句要说清「为什么是这一档」：score_match 低有两种相反的原因——
    #   位次不够（专业太卷）  或  位次富裕（专业太浅）。
    # 早期实现只会照抄 score_sensitivity 的描述，于是护理学类对前 15% 的考生
    # 一边显示「现实折损：高」、一边写着"各层次院校差距不大，更看个人能力"——
    # 高折损却说了一句宽心话，用户看不懂到底哪里不行。这里按组合分别表述。
    my_rank = _RANK_TIER_PHRASE.get(rank_tier, "未知")
    if score_sens in ("低", "极低") and rank_tier in ("top", "upper"):
        score_note = (f"你的位次约在{my_rank}，高于该专业的常见录取区间——"
                      f"它各层次院校差距不大，读它可能浪费你的位次")
    elif score_sens in ("极高", "高") and rank_tier in ("middle", "lower"):
        score_note = (f"你的位次约在{my_rank}，低于该专业的常见录取区间——"
                      f"它高度依赖院校层级，需要位次再加把劲")
    else:
        score_note = (f"你的位次约在{my_rank}，"
                      f"{_SCORE_SENS_PHRASE.get(score_sens, '该专业对分数位次有一定要求')}")

    notes = [
        score_note,
        f"你的家庭经济水平为「{econ}」，该方向{_ASSET_SENS_PHRASE.get(asset_sens, '')}",
    ]
    return {
        "fit_score": round(cat.get("industry_match", 0.0), 4),
        "reality_tier": tier,
        "reality_score": round(combined, 4),
        "reality_reason": "；".join(notes),
    }


def _pick(variants: list[str], i: int) -> str:
    """按**名次**挑句式变体。

    这里不能用哈希（无论 crc32 还是内置 hash）：哈希在全局上分布均匀，但在**同一页
    内部**不保证散开——实测 crc32 会在一页 6 个专业里挑出 3 个同款句式，正是要避免的
    画面。按名次取模能保证相邻两个专业必然换一种说法。

    也不用内置 hash()：它对字符串按进程随机加盐，同一个专业刷新一次页面就换一句话。
    """
    return variants[i % len(variants)]


def _generate_major_reason(major: dict, user: UserProfile, cat_labels: dict = None,
                           idx: int = 0) -> str:
    """生成具体专业的推荐理由。

    设计原则：**每一条理由都必须提到这个专业本身**。

    旧实现最致命的一档是 micro < 0.70 的兜底：「你的核心优势（抗压能力(59分)、
    创造性思维(48分)）与此专业有一定关联」——它只夸用户、完全不提专业，套在哲学、
    护理、土木上全都成立。实测它占了全部推荐理由的 67.6%，是「文案官方、重复率高」
    的最大来源（真正提到专业的 micro>=0.85 那档只占 2.4%，因为门槛太高）。
    所以这里改成：说明这个专业**要什么**、和你的强项差在哪、它为什么还在榜上。
    """
    parts = []
    micro = major.get("micro_match", 0)
    actions = major.get("micro_actions", [])
    name = major.get("major_name", "该专业")
    code = major.get("major_code", "")
    demand = "、".join(actions[:2])
    best_dim, best_val = user.get_top_behaviors(1)[0]

    if micro >= 0.85 and demand:
        parts.append(_pick([
            f"{demand}——这正是{name}的核心动作，也是你最强的那一档",
            f"你的行为画像与{name}几乎重合：它要的就是{demand}",
            f"{name}的日常就是{demand}，在所有专业里算罕见的对口",
        ], idx))

    elif micro >= 0.70 and demand:
        parts.append(_pick([
            f"{name}主要要求{demand}，和你对得上",
            f"你在{demand}上有底子，正是{name}的日常",
            f"{name}的核心动作是{demand}，与你重合度较高",
        ], idx))

    elif demand:
        # 这一档不再空夸用户，而是如实交代落差与上榜原因。
        # 注意三个变体里只有**一个**会点名用户的最强维度：用户的最强维度是固定的，
        # 如果每条理由都念一遍，一页 4 个专业就会出现 4 次「不是你最强的动手实验
        # (58分)」——句式轮换了，读起来还是复读机（实测每页 3.68 条在念同一个维度）。
        parts.append(_pick([
            f"{name}要的是{demand}，不是你最强的{best_dim}({best_val:.0f}分)——"
            f"它上榜靠的是所属专业类的整体匹配",
            f"它主要要求{demand}，与你的强项不同路，属于可以了解而非高度对口",
            f"{name}的日常是{demand}；这一档不是你的强项，"
            f"它进榜靠的是专业类整体匹配",
        ], idx))

    else:
        parts.append(f"你的核心优势（{best_dim}({best_val:.0f}分)）与此专业有一定关联")

    # 补充信息按重要性排序，最多再放一条——卡片正文被截断在 100 字，
    # 塞太多反而把最该看的挤掉。
    # 同一件事实给多个说法：一页里 4 个专业都「招生体量极小」时，若用同一句话
    # 复述 4 遍，就又变回模板了。
    extra = ""
    thresholds = major.get("hard_threshold", [])
    if thresholds:
        extra = _pick([
            f"该专业设体检门槛：{'、'.join(thresholds)}（你已符合）",
            f"报考有硬门槛——{'、'.join(thresholds)}，你的条件没问题",
            f"注意它有体检限制（{'、'.join(thresholds)}），你符合要求",
        ], idx + 1)
    elif major.get("enrollment_volume") == "极小":
        extra = _pick([
            "全国招生体量极小，开设院校少、分数波动大，志愿梯度要拉开",
            "招生体量极小，只有少数院校开设，大小年波动明显",
        ], idx + 1)
    elif major.get("social_heat") == "极高":
        extra = _pick([
            "该专业当前竞争极为激烈，建议做好梯度规划",
            "眼下报考热度极高，冲稳保三档都要留足",
        ], idx + 1)
    elif major.get("social_heat") == "低":
        extra = _pick([
            "该专业相对冷门但稳定，竞争压力较小",
            "报考热度不高，录取相对从容",
        ], idx + 1)
    if extra:
        parts.append(extra)

    return "。".join(parts)


# ============================================================================
# 主入口：运行三层漏斗
# ============================================================================

def run_funnel(user: UserProfile, verbose: bool = False) -> list[dict]:
    """
    运行三层递进漏斗，返回结构化推荐结果。

    Args:
        user: 用户画像
        verbose: 是否打印中间过程

    Returns:
        list[dict]: 符合前端 Schema 的推荐结果
    """
    try:
        return _run_funnel_impl(user, verbose)
    except Exception as e:
        import traceback
        print(f"[ERROR] run_funnel failed: {e}")
        traceback.print_exc()
        return []


def _run_funnel_impl(user: UserProfile, verbose: bool = False) -> list[dict]:
    data = load_funnel_data()

    # 数据校验
    if not data.disciplines:
        print("[ERROR] Funnel data: no disciplines loaded!")
        return []
    if not data.categories:
        print("[ERROR] Funnel data: no categories loaded!")
        return []
    if not data.majors:
        print("[ERROR] Funnel data: no majors loaded!")
        return []

    # ---- Layer 1: 学科门类初筛 ----
    if verbose:
        print("\n[Layer 1] 学科门类初筛")
    l1 = layer1_discipline_match(user, data)
    if verbose:
        for d in l1[:5]:
            print(f"  {d['discipline_name']}: {d['score']:.4f} "
                  f"(cog={d['cognitive_sim']:.3f} per={d['persona_sim']:.3f} w={d['weight_bonus']:.2f})")

    # ---- Layer 2: 专业类精选 (Top 8) ----
    if verbose:
        print(f"\n[Layer 2] 专业类精选 → Top 8 截断")
    l2 = layer2_category_match(user, data, l1)
    if verbose:
        for i, c in enumerate(l2):
            print(f"  #{i+1} {c['category_name']} ({c['discipline_name']}): {c['score']:.4f} "
                  f"ind={c['industry_match']:.3f} ast={c['asset_match']:.3f} scr={c['score_match']:.3f}")

    if not l2:
        print("[ERROR] Layer 2 returned no categories!")
        return []

    # ---- 多样性强制打散：同一门类占比过高时逐步替换末位 ----
    # 注意：若用户有强烈意向特殊赛道，跳过打散（尊重用户明确选择）
    has_strong_track = (
        user.special_track_intent is not None
        and user.special_track_stance == "强烈意向"
    )
    from collections import Counter
    disc_counts = Counter(c["discipline_name"] for c in l2)
    dominant_disc, dominant_count = disc_counts.most_common(1)[0]
    if not has_strong_track and dominant_count >= 5:
        all_cats = layer2_category_match(user, data, l1, top_n=999)
        # 从候选池按顺序取跨门类替补
        candidate_idx = 0
        for replace_pos in range(len(l2) - 1, -1, -1):
            if l2[replace_pos]["discipline_name"] != dominant_disc:
                continue  # 已经是跨门类，无需替换
            # 找下一个跨门类候选
            while candidate_idx < len(all_cats):
                cand = all_cats[candidate_idx]
                candidate_idx += 1
                if cand["category_name"] not in {c["category_name"] for c in l2}:
                    if cand["discipline_name"] != dominant_disc:
                        l2[replace_pos] = cand
                        if verbose:
                            print(f"  [Diversity] 替换 #{replace_pos+1}: "
                                  f"{cand['category_name']}({cand['discipline_name']})")
                        break
            # 更新计数
            disc_counts = Counter(c["discipline_name"] for c in l2)
            dominant_disc, dominant_count = disc_counts.most_common(1)[0]
            if dominant_count <= 4:
                break  # 已足够多样

        # 上面是「按位置就地替换」(l2[replace_pos] = cand)，替补的跨门类专业类
        # 分数通常低于被换掉的那个，却继承了原位置 —— 于是对外展示的顺序不再
        # 按分数单调。实测技术爱好者用户：材料类(0.9422)/力学类(0.9070) 被换成
        # 数学类(0.8869)/物理学类(0.8895)，名单上就出现 #6 0.887 < #7 0.890
        # < #8 0.893 的倒挂。
        # 打散只关心「选哪些类专业类」，不关心顺序，故替换后重排一次即可，
        # 打散效果完全保留。
        l2.sort(key=lambda x: x["score"], reverse=True)

    # ---- Layer 3: 专业微观狙击 (≤6/类) ----
    if verbose:
        print(f"\n[Layer 3] 专业微观狙击 → ≤6/类 截断")
    l3 = layer3_major_match(user, data, l2)
    if verbose:
        for cat in l3:
            print(f"  [{cat['category_name']}] {len(cat['recommended_majors'])} majors")
            for m in cat["recommended_majors"][:3]:
                print(f"    {m['major_name']}: {m['score']:.4f} "
                      f"(micro={m['micro_match']:.3f} heat={m['heat_align']:.3f})")

    # 救援机制：若 L3 输出偏少（类别<5 或总专业<15），从备选池补充
    total_majors = sum(len(c["recommended_majors"]) for c in l3)
    if (len(l3) <= 5 or total_majors < 15) and len(l3) < len(l2):
        rescued_needed = 8 - len(l3)
        # 取 L2 中未参与 L3 的类别（第 9 名起）
        all_l2 = layer2_category_match(user, data, l1, top_n=999)
        used_names = {c["category_name"] for c in l2}
        candidates = [c for c in all_l2 if c["category_name"] not in used_names]
        rescue_cats = candidates[:rescued_needed]
        if rescue_cats:
            l3_rescue = layer3_major_match(user, data, rescue_cats)
            l3.extend(l3_rescue)
            if verbose:
                print(f"  [Rescue] 输出偏少(类别{len(l3)}/专业{total_majors})，"
                      f"补充 {len(l3_rescue)} 个备选类别: "
                      f"{[c['category_name'] for c in l3_rescue]}")
            # 救援类别是直接 extend 到末尾的，而它们的分数未必最低（它们只是
            # 从 L2 第 9 名往后取的，不是按分数补的），同样会造成展示顺序倒挂。
            l3.sort(key=lambda x: x["category_score"], reverse=True)

    # ---- 格式化输出 ----
    output = []
    for cat in l3:
        cat_labels = cat.get("category_labels", {})
        majors_out = []
        for mi, m in enumerate(cat["recommended_majors"]):
            tags = _generate_major_tags(m)
            # 传名次 mi：理由的句式按名次轮换，保证同一页相邻的专业不会用同一种说法
            reason = _generate_major_reason(m, user, cat_labels, idx=mi)
            majors_out.append({
                "major_name": m["major_name"],
                "major_code": m["major_code"],
                "tags": tags,
                "major_reason": reason,
                "major_score": m["score"],
                "threshold_pass": m["threshold_pass"],
            })

        cat_reason = _generate_category_reason(cat, user)
        reality = _reality_assessment(cat, user)
        output.append({
            "category_name": cat["category_name"],
            "discipline_name": cat["discipline_name"],
            "category_reason": cat_reason,
            "category_score": cat["category_score"],
            # 薪资潜力是**专业类**级别的属性（layer2_categories.json 里就有），
            # 全引擎此前 0 次引用——采了没用。放在类级别展示一次，既补上了这块
            # 信息，又避免 6 个专业卡片上重复 6 遍。
            "salary_potential": cat_labels.get("salary_potential", "中"),
            "category_tags": _generate_category_tags(cat_labels),
            # 展示用分项：让「适不适合」与「能不能上」分开可见（见 _reality_assessment）
            "fit_score": reality["fit_score"],
            "reality_tier": reality["reality_tier"],
            "reality_score": reality["reality_score"],
            "reality_reason": reality["reality_reason"],
            "recommended_majors": majors_out,
        })

    return output


# ============================================================================
# 便捷打印
# ============================================================================

def print_funnel_results(results: list[dict]) -> None:
    """美化打印漏斗结果"""
    print()
    print("=" * 72)
    print("  🎯 三层递进漏斗推荐引擎 v6.0 — 最终推荐结果")
    print("=" * 72)

    for ci, cat in enumerate(results):
        medal = {0: "🥇", 1: "🥈", 2: "🥉"}.get(ci, f"#{ci+1}")
        print(f"\n{medal} [{cat['category_name']}] ({cat['discipline_name']})")
        print(f"   契合度: {cat.get('fit_score', 0):.3f}  "
              f"| 现实折损: {cat.get('reality_tier', '?')}  "
              f"| 综合排序分: {cat['category_score']:.3f}")
        print(f"   📌 {cat['category_reason']}")
        if cat.get("reality_reason"):
            print(f"   ⚖️ {cat['reality_reason']}")
        print(f"   ──────────────────────────────")

        for mi, m in enumerate(cat["recommended_majors"]):
            tag_str = " ".join(m["tags"]) if m["tags"] else ""
            print(f"   {mi+1}. {m['major_name']} ({m['major_code']}) "
                  f"| {m['major_score']:.3f} {tag_str}")
            print(f"      {m['major_reason']}")

    print(f"\n{'='*72}")
    total_majors = sum(len(c["recommended_majors"]) for c in results)
    print(f"  共 {len(results)} 个专业类 / {total_majors} 个专业")


# ============================================================================
# 自测
# ============================================================================

if __name__ == "__main__":
    from user_profile import create_test_user

    user = create_test_user()
    # 补充价值观向量（测试用户默认没有）
    if not user.macro_value_vector:
        user.macro_value_vector = {
            "稳定偏好": 30.0,
            "成长导向": 85.0,
            "风险容忍度": 60.0,
            "社会影响力": 45.0,
            "经济回报": 80.0,
        }

    results = run_funnel(user, verbose=True)
    print_funnel_results(results)

    # 验证
    print("\n[验证]")
    assert len(results) <= 8, f"Too many categories: {len(results)}"
    for cat in results:
        assert len(cat["recommended_majors"]) <= 6, \
            f"{cat['category_name']} has {len(cat['recommended_majors'])} majors"
    print(f"✅ 类别数: {len(results)} (≤8)")
    for cat in results:
        print(f"✅ {cat['category_name']}: {len(cat['recommended_majors'])} majors (≤6)")
    print("✅ 所有验证通过！")
