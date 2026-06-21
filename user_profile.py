"""
================================================================================
 用户画像数据模型 (User Profile Data Model)
================================================================================
 定义 UserProfile 数据类，包含：
   1. 硬约束字段（选科、分数、位次、体检）
   2. 家庭资源字段（经济水平、城市层级、海外资源、行业人脉）
   3. 特殊赛道意图（医学/师范/军警）
   4. 问卷计算结果（宏观产业向量、微观行为向量、推断人格）
   5. 人格推断矩阵（从微观行为 → RIASEC 六维度）
================================================================================
"""

from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# 行为维度定义（10个微观维度）
# ============================================================================
BEHAVIOR_DIMENSIONS = [
    "逻辑推理",     # logical reasoning — 演绎、归纳、抽象思维
    "动手实验",     # hands-on experimentation — 搭建、操作、调试
    "团队协作",     # team collaboration — 分工、协调、互助
    "创造性思维",   # creative thinking — 发散、设计、原创
    "精细操作",     # fine/detail-oriented work — 精确、校准、规范
    "持续专注",     # sustained concentration — 长时间聚焦、抗干扰
    "沟通表达",     # communication & expression — 说服、展示、共情
    "数据敏感",     # data/numerical sensitivity — 量化、统计、模式识别
    "抗压能力",     # stress tolerance — 高压环境下保持稳定
    "记忆积累",     # memorization & accumulation — 知识储备、长期记忆
]

# ============================================================================
# 产业集群定义（10个宏观产业方向）
# ============================================================================
INDUSTRY_CLUSTERS = [
    "AI与大模型",
    "互联网与软件",
    "半导体与芯片",
    "金融科技",
    "智能制造",
    "新能源",
    "生物医药",
    "教育培训",
    "政府公共",
    "文化传媒",
]

# ============================================================================
# 人格推断矩阵：micro_behavior_vector → RIASEC 六维度
# 每个 RIASEC 维度由若干行为维度加权合成
# ============================================================================
PERSONALITY_INFERENCE_MAP = {
    # 现实型 R：动手操作、精细加工、持续投入
    "R": [
        ("动手实验",      0.50),
        ("精细操作",      0.30),
        ("持续专注",      0.20),
    ],
    # 研究型 I：逻辑推理、持续专注、数据敏感
    "I": [
        ("逻辑推理",      0.50),
        ("持续专注",      0.30),
        ("数据敏感",      0.20),
    ],
    # 艺术型 A：创造性思维、沟通表达、动手实现
    "A": [
        ("创造性思维",    0.55),
        ("沟通表达",      0.30),
        ("动手实验",      0.15),
    ],
    # 社会型 S：沟通表达、团队协作、记忆积累（共情与理解）
    "S": [
        ("沟通表达",      0.40),
        ("团队协作",      0.40),
        ("记忆积累",      0.20),
    ],
    # 企业型 E：沟通表达、团队协调、抗压能力、数据驱动决策
    "E": [
        ("沟通表达",      0.35),
        ("团队协作",      0.25),
        ("抗压能力",      0.25),
        ("数据敏感",      0.15),
    ],
    # 常规型 C：精细操作、数据敏感、记忆积累、逻辑条理
    "C": [
        ("精细操作",      0.40),
        ("数据敏感",      0.30),
        ("记忆积累",      0.20),
        ("逻辑推理",      0.10),
    ],
}

# ============================================================================
# RIASEC 维度说明（保留用于输出显示）
# ============================================================================
RIASEC_INFO = {
    "R": {"name": "现实型 (Realistic)", "icon": "🔧",
          "desc": "动手操作，喜爱工具与机械，偏好户外与体力活动"},
    "I": {"name": "研究型 (Investigative)", "icon": "🔬",
          "desc": "观察思考，喜爱分析探索，偏好科学与实验"},
    "A": {"name": "艺术型 (Artistic)", "icon": "🎨",
          "desc": "创意表达，喜爱文学艺术，偏好自由与美感"},
    "S": {"name": "社会型 (Social)", "icon": "🤝",
          "desc": "助人为乐，喜爱教导服务，偏好人际沟通"},
    "E": {"name": "企业型 (Enterprising)", "icon": "📢",
          "desc": "领导说服，喜爱管理影响，偏好目标与成就"},
    "C": {"name": "常规型 (Conventional)", "icon": "📋",
          "desc": "条理规范，喜爱整理数据，偏好秩序与系统"},
}


@dataclass
class UserProfile:
    """
    用户画像数据类 — 聚合硬约束、家庭资源、问卷结果。

    设计原则：
    - 硬约束（选科/体检）来自用户直接输入，不是问卷推断
    - 家庭资源来自用户自述（匿名、不强制）
    - 问卷结果来自 questionnaire.py 的评分函数
    - inferred_personality 从 micro_behavior_vector 通过矩阵映射自动推断
    """

    # ================================================================
    # 硬约束字段（用户直接输入）
    # ================================================================
    selected_subjects: list[str] = field(default_factory=list)
    """选考科目，如 ["物理", "化学", "生物"]"""

    estimated_score: int = 0
    """预估高考分数（裸分），如 635"""

    estimated_rank_percentile: float = 100.0
    """预估位次百分位，如 8.5 表示全省前 8.5%（数值越小越靠前）"""

    physical_conditions: list[str] = field(default_factory=list)
    """体检限制标签，如 [] 或 ["色盲", "裸眼视力<4.8"]"""

    # ================================================================
    # 家庭资源字段（用户直接输入）
    # ================================================================
    family_economic_level: str = "中"
    """家庭经济水平: "高" / "中" / "低" """

    family_city_tier: str = "新一线"
    """家庭所在城市层级: "一线" / "新一线" / "二线" / "三线及以下" """

    family_has_overseas_resource: bool = False
    """家庭是否有海外留学资源（亲属、经济能力等）"""

    family_has_industry_connection: str = "无"
    """家庭在某行业的人脉资源，如 "金融" / "医疗" / "教育" / "无" """

    # ================================================================
    # 特殊赛道意图（用户直接选择）
    # ================================================================
    special_track_intent: Optional[str] = None
    """特殊赛道意图: None / "医学" / "师范" / "军警" """

    special_track_stance: Optional[str] = None
    """对待特殊赛道的态度细化: None / "强烈意向" / "可以接受" / "极度抗拒" """

    # ================================================================
    # 问卷计算结果（由 questionnaire.py 的 scoring 函数填充）
    # ================================================================
    macro_industry_vector: dict[str, float] = field(default_factory=dict)
    """
    宏观产业向量（0-100），key 为 10 个产业集群名。
    来自 10 道宏观意愿题（M1-M10）的得分汇总。
    在 Step 0 中可能被衰减。
    """

    macro_value_vector: dict[str, float] = field(default_factory=dict)
    """
    宏观价值观向量（0-100）。
    key: "稳定偏好" / "成长导向" / "风险容忍度" / "社会影响力" / "经济回报"
    """

    micro_behavior_vector: dict[str, float] = field(default_factory=dict)
    """
    微观行为向量（0-100），key 为 10 个行为维度名。
    来自 30 道微观场景题（U1-U30）的得分汇总。
    这是最难伪造的信号，权重最高（40%）。
    """

    inferred_personality: dict[str, float] = field(default_factory=dict)
    """
    从微观行为向量推断的 RIASEC 人格向量（0-100）。
    key: "R" / "I" / "A" / "S" / "E" / "C"
    自动计算，不是用户自评。
    """

    lie_score: float = 0.0
    """
    全局测谎分数（0.0-1.0）。
    0.0 = 宏观微观完全一致，1.0 = 严重矛盾。
    由 Step 0 计算。
    """

    # ================================================================
    # 便捷方法
    # ================================================================

    def infer_personality_from_behavior(self) -> dict[str, float]:
        """
        从 micro_behavior_vector 推断 RIASEC 人格向量。

        映射逻辑：对每个 RIASEC 维度，取相关行为维度的加权平均，
        然后归一化到 0-100。

        Returns:
            dict[str, float]: {"R": 73.5, "I": 82.0, ...}
        """
        result = {}
        for dim, components in PERSONALITY_INFERENCE_MAP.items():
            raw = 0.0
            total_weight = 0.0
            for behavior_name, weight in components:
                score = self.micro_behavior_vector.get(behavior_name, 50.0)
                raw += score * weight
                total_weight += weight
            result[dim] = round(raw / total_weight, 1) if total_weight > 0 else 50.0

        self.inferred_personality = result
        return result

    def get_dominant_personality(self) -> str:
        """返回主导人格维度（RIASEC 六取一）"""
        if not self.inferred_personality:
            self.infer_personality_from_behavior()

        if not self.inferred_personality:
            return "I"

        return max(self.inferred_personality.items(), key=lambda x: x[1])[0]

    def get_top_behaviors(self, n: int = 3) -> list[tuple[str, float]]:
        """返回得分最高的 N 个行为维度"""
        sorted_behaviors = sorted(
            self.micro_behavior_vector.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_behaviors[:n]

    def get_weakest_behaviors(self, n: int = 3) -> list[tuple[str, float]]:
        """返回得分最低的 N 个行为维度"""
        sorted_behaviors = sorted(
            self.micro_behavior_vector.items(),
            key=lambda x: x[1]
        )
        return sorted_behaviors[:n]

    def summarize(self) -> str:
        """生成用户画像摘要（用于调试和输出）"""
        top_behavior = self.get_top_behaviors(3)
        weak_behavior = self.get_weakest_behaviors(3)
        top_personality = self.get_dominant_personality()

        lines = [
            f"选科: {'+'.join(self.selected_subjects) if self.selected_subjects else '未设置'}",
            f"分数: {self.estimated_score}分 (前{self.estimated_rank_percentile}%)",
            f"家庭: {self.family_economic_level}经济 / {self.family_city_tier} / "
            f"{'有' if self.family_has_overseas_resource else '无'}海外资源 / "
            f"{'无' if self.family_has_industry_connection == '无' else self.family_has_industry_connection + '人脉'}",
            f"特殊赛道: {self.special_track_intent or '无'} ({self.special_track_stance or '未表态'})",
            f"主导人格: {RIASEC_INFO.get(top_personality, {}).get('name', top_personality)}",
            f"行为优势: {', '.join(f'{k}({v:.0f})' for k, v in top_behavior)}",
            f"行为短板: {', '.join(f'{k}({v:.0f})' for k, v in weak_behavior)}",
            f"测谎分数: {self.lie_score:.2f}",
        ]
        return "\n".join(lines)


# ============================================================================
# 便捷工厂函数
# ============================================================================

def create_test_user() -> UserProfile:
    """
    创建用于测试的典型用户画像。
    选科物化生，中等分数，家庭资源一般，微观逻辑强但记忆弱。
    """
    user = UserProfile(
        selected_subjects=["物理", "化学", "生物"],
        estimated_score=580,
        estimated_rank_percentile=20.0,      # 前20%，一本线上
        physical_conditions=[],               # 无体检限制
        family_economic_level="低",
        family_city_tier="三线及以下",
        family_has_overseas_resource=False,
        family_has_industry_connection="无",
        special_track_intent=None,
        special_track_stance=None,

        # 宏观产业向往：强烈向往AI/互联网，中度向往生物医药
        macro_industry_vector={
            "AI与大模型":      85.0,
            "互联网与软件":    80.0,
            "半导体与芯片":    65.0,
            "金融科技":        40.0,
            "智能制造":        50.0,
            "新能源":          45.0,
            "生物医药":        60.0,
            "教育培训":        30.0,
            "政府公共":        20.0,
            "文化传媒":        25.0,
        },

        # 宏观价值观
        macro_value_vector={
            "稳定偏好":     30.0,
            "成长导向":     85.0,
            "风险容忍度":   60.0,
            "社会影响力":   45.0,
            "经济回报":     80.0,
        },

        # 微观行为：逻辑强、专注强、数据敏感，但记忆积累弱、沟通弱
        micro_behavior_vector={
            "逻辑推理":   88.0,
            "动手实验":   75.0,
            "团队协作":   55.0,
            "创造性思维": 70.0,
            "精细操作":   65.0,
            "持续专注":   82.0,
            "沟通表达":   50.0,
            "数据敏感":   78.0,
            "抗压能力":   60.0,
            "记忆积累":   45.0,        # ← 关键短板：医学专业的天花板
        },
    )

    # 自动推断人格
    user.infer_personality_from_behavior()

    return user


def create_empty_user() -> UserProfile:
    """创建空用户模板（所有字段默认值）"""
    return UserProfile()


if __name__ == "__main__":
    # 快速自测
    user = create_test_user()
    print("=" * 60)
    print("用户画像摘要")
    print("=" * 60)
    print(user.summarize())
    print()
    print("推断人格向量:", user.inferred_personality)
    print("主导人格:", user.get_dominant_personality())
