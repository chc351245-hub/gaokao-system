"""
================================================================================
 高考志愿智能推荐引擎 v5.0 ? 核心匹配算法
================================================================================
 6 步管线 (Pipeline)：

   Step 0: 情绪测谎与置信度降维 (Data Purification)
          ? 宏观意愿 vs 微观行为矛盾检测 ? 矛盾集群衰减 ×0.5

   Step 1: 生死红线过滤 (Hard Filter)
          ? 选科不符 / 体检限制命中 ? 物理 drop

   Step 2: 特殊赛道阻断与提权 (Special Track)
          ? 医学/师范/军警：阻断或提权

   Step 3: 基础匹配分 (Base Score)
          ? 人格30% + 产业30% + 微观行为40%（余弦相似度）

   Step 4: 现实折损 (Reality Penalty)
          ? 分数位次折损 + 家庭资源折损

   Step 5: 底层信号强穿透 (Bypass Channel)
          ? 微观行为极高分 ? 无视性格/产业，拉满基础分至 1.0

   Step 6: 多样性强制打散 (Diversity Forcing)
          ? Top 3 同门类 ? 注入跨界 Plan B

 核心理念：
   - "匹配分" 只计算专业与人的内在适配度，绝不掺杂院校录取概率
   - 录取概率仅作为前端 UI 展示标签，绝不污染专业的匹配纯度
================================================================================
"""

import json
import math
from dataclasses import dataclass, field
from typing import Optional, Any

from user_profile import (
    UserProfile,
    BEHAVIOR_DIMENSIONS,
    INDUSTRY_CLUSTERS,
    RIASEC_INFO,
)
from questionnaire import CONSISTENCY_RULES


# ============================================================================
# 推荐结果数据结构
# ============================================================================

@dataclass
class RecommendationResult:
    """单个专业的推荐结果"""
    major: dict
    """完整的专业数据条目（来自 enhanced_majors.json）"""

    rank: int = 0
    """最终排名（1-based）"""

    final_score: float = 0.0
    """最终得分（0.0-1.0），经全部管线处理后的输出"""

    base_score: float = 0.0
    """基础匹配分（0.0-1.0），Step 3 输出，未折损"""

    personality_sim: float = 0.0
    """人格匹配相似度（0.0-1.0）"""

    industry_sim: float = 0.0
    """产业匹配相似度（0.0-1.0）"""

    micro_sim: float = 0.0
    """微观行为匹配相似度（0.0-1.0）"""

    reality_penalty: float = 1.0
    """现实折损系数（Step 4 乘法因子，?1.0）"""

    score_penalty: float = 1.0
    """分数位次折损子系数"""

    resource_penalty: float = 1.0
    """家庭资源折损子系数"""

    label: str = "标准推荐"
    """推荐标签：高优直达 / 排雷预警 / 跨界Plan B / 标准推荐"""

    step_details: dict = field(default_factory=dict)
    """各步骤处理详情（调试用）"""

    reason: str = ""
    """人类可读的推荐理由"""

    warnings: list[str] = field(default_factory=list)
    """排雷预警列表"""

    boosted: bool = False
    """是否被 Step 2 提权"""

    bypassed: bool = False
    """是否被 Step 5 底层信号强穿透"""

    blocked: bool = False
    """是否被 Step 1 或 Step 2 阻断（被阻断的不会出现在最终结果中）"""


# ============================================================================
# 工具函数
# ============================================================================

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    计算两个向量的余弦相似度。

    设计选择：余弦相似度归一化了"向量长度"??如果用户所有维度都填高分，
    不影响匹配结果（只看方向不看强度），有效防止"永远选A"的作弊行为。

    Returns:
        0.0-1.0 的相似度（钳位到 [0, 1]）
    """
    if len(a) != len(b) or len(a) == 0:
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    sim = dot_product / (norm_a * norm_b)
    # 余弦相似度理论范围 [-1, 1]，钳位到 [0, 1]
    return max(0.0, min(1.0, sim))


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """将值钳位到 [lo, hi] 区间"""
    return max(lo, min(hi, value))


# ============================================================================
# Step 0: 情绪测谎与置信度降维
# ============================================================================

def step0_lie_detection(user: UserProfile) -> tuple[dict[str, float], float, list[dict]]:
    """
    第 0 步：情绪测谎与置信度降维 (Data Purification)

    核心逻辑：
      对比用户的"宏观产业向往"与"微观行为得分"。
      如果用户声称极度向往某行业（macro > 60），
      但该行业所需的核心行为维度得分却很低（micro 均值 < 阈值），
      说明存在"叶公好龙"式的认知偏差 ?? 用户听说某行业赚钱/风光就向往，
      但根本不具备甚至排斥该行业的核心日常行为。

    处理方式：
      该矛盾集群的宏观产业分 × 0.5（半衰，不是归零）。

    为什么是 ×0.5 而不是归零？
      - 18岁青少年的自我认知本身就在快速变化中
      - 宏观向往虽然可能"不接地气"，但完全否定也不公平
      - 0.5 的衰减让微观行为信号占主导，但不完全消除宏观信号

    Args:
        user: 用户画像（含 macro_industry_vector 和 micro_behavior_vector）

    Returns:
        (adjusted_macro_vector, global_lie_score)
        - adjusted_macro_vector: 经过衰减处理后的产业向量（0-100）
        - global_lie_score: 全局测谎分数（0.0-1.0）
    """
    adjusted = dict(user.macro_industry_vector)
    contradiction_count = 0
    contradiction_details = []

    for rule in CONSISTENCY_RULES:
        cluster = rule["macro_cluster"]
        expected_dims = rule["expected_micro_dims"]
        threshold = rule["threshold"]
        severity = rule["severity"]

        macro_val = adjusted.get(cluster, 0)

        # 只检测"高向往"的集群（>60分才算真正向往）
        if macro_val <= 60:
            continue

        # 计算该集群所需微观维度的平均得分
        micro_vals = []
        for dim in expected_dims:
            val = user.micro_behavior_vector.get(dim, 50.0)
            micro_vals.append(val)

        micro_avg = sum(micro_vals) / len(micro_vals) if micro_vals else 50.0

        # 若微观均值低于阈值 ? 触发矛盾
        if micro_avg < threshold:
            contradiction_count += 1
            old_val = adjusted[cluster]
            adjusted[cluster] = old_val * severity

            contradiction_details.append({
                "cluster": cluster,
                "label": rule["label"],
                "macro_original": old_val,
                "macro_adjusted": adjusted[cluster],
                "micro_avg": round(micro_avg, 1),
                "threshold": threshold,
                "severity": severity,
            })

    # 全局测谎分数：矛盾集群数 / 总规则数
    total_rules = len(CONSISTENCY_RULES)
    lie_score = contradiction_count / total_rules if total_rules > 0 else 0.0

    # 存储到用户对象
    user.lie_score = lie_score
    user.macro_industry_vector = adjusted  # 更新为衰减后的向量

    return adjusted, lie_score, contradiction_details


# ============================================================================
# Step 1: 生死红线过滤
# ============================================================================

def step1_red_line_filter(
    user: UserProfile,
    majors: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    第 1 步：生死红线过滤 (Hard Filter)

    规则 1：选科要求不满足 ? 物理 drop
       例：临床医学要求 [物理, 化学]，用户只有 [物理, 生物] ? drop

    规则 2：体检限制命中 ? 物理 drop
       例：临床医学颜色盲限报，用户有色盲 ? drop

    这些专业绝不可能被录取（不是"不推荐"，而是"报不了"），
    直接从候选池中物理移除，后续流程中永不出现。

    Args:
        user: 用户画像
        majors: 待过滤的专业列表

    Returns:
        (survivors, blocked_majors)
        - survivors: 通过过滤的专业列表
        - blocked_majors: 被过滤的专业列表（含过滤原因）
    """
    user_subjects = set(user.selected_subjects)
    user_conditions = set(user.physical_conditions)

    survivors = []
    blocked_majors = []

    for major in majors:
        tt = major.get("threshold_tags", {})
        if not tt:
            survivors.append(major)
            continue

        required_subjects = set(tt.get("选科要求", []))
        physical_restrictions = set(tt.get("体检限制", []))

        blocked = False
        reasons = []

        # 检查选科
        if required_subjects and not required_subjects.issubset(user_subjects):
            missing = required_subjects - user_subjects
            reasons.append(f"选科不符：缺 {', '.join(sorted(missing))}")
            blocked = True

        # 检查体检
        if physical_restrictions:
            # 使用子串匹配：用户的"色盲"匹配专业的"色盲限报"
            hits = set()
            for restriction in physical_restrictions:
                for condition in user_conditions:
                    if condition in restriction or restriction in condition:
                        hits.add(restriction)
            if hits:
                reasons.append(f"体检限制命中：{', '.join(sorted(hits))}")
                blocked = True

        if blocked:
            blocked_majors.append({
                "major": major,
                "reasons": reasons,
            })
        else:
            survivors.append(major)

    return survivors, blocked_majors


# ============================================================================
# Step 2: 特殊赛道阻断与提权
# ============================================================================

# 医学赛道要求的完整选科集合
MEDICAL_SUBJECT_REQUIREMENT = {"物理", "化学"}

# 军警赛道体检硬要求（示例）
MILITARY_PHYSICAL_RESTRICTIONS = {
    "身高不达标限报",
    "裸眼视力<4.8限报",
}


def step2_special_track(
    user: UserProfile,
    majors: list[dict],
) -> tuple[list[dict], dict[str, float], list[dict]]:
    """
    第 2 步：特殊赛道阻断与提权 (Special Track Gating)

    三类特殊赛道：医学、师范、军警
    每一类都有独立的阻断/提权逻辑。

    医学赛道：
      - "极度抗拒" ? 所有 special_track == "医学" 的专业物理移除
      - "强烈意向" + 物化齐全 ? 基础匹配分 boost ×1.3
      - 不表态 ? 正常计算，无加成无惩罚

    师范赛道：
      - "强烈意向" ? boost ×1.2
      - "极度抗拒" ? 移除
      - 不表态 ? 正常计算

    军警赛道：
      - 非"强烈意向" ? 物理移除（军警必须主动选择）
      - "强烈意向" + 体检合格 ? boost ×1.5
      - "强烈意向" + 体检不合格 ? 物理移除

    Args:
        user: 用户画像
        majors: 待处理的专业列表（已通过 Step 1）

    Returns:
        (survivors, boost_map, blocked_majors)
        - survivors: 未因特殊赛道被阻断的专业
        - boost_map: {专业代码: boost系数}，仅含需要提权的专业
        - blocked_majors: 被阻断的专业列表
    """
    track = user.special_track_intent
    stance = user.special_track_stance  # "强烈意向" / "可以接受" / "极度抗拒"

    boost_map = {}
    survivors = []
    blocked_majors = []

    for major in majors:
        st = major.get("special_track")

        # 非特殊赛道专业 ? 直接放行
        if st is None:
            survivors.append(major)
            continue

        code = major["专业代码"]
        blocked = False

        # ------------------------------------------------------------------
        # 医学赛道处理
        # ------------------------------------------------------------------
        if st == "医学":
            if track == "医学" and stance == "极度抗拒":
                blocked = True
                blocked_majors.append({
                    "major": major,
                    "reason": "特殊赛道阻断：用户极度抗拒医学方向",
                })
            elif track == "医学" and stance == "强烈意向":
                user_subs = set(user.selected_subjects)
                if MEDICAL_SUBJECT_REQUIREMENT.issubset(user_subs):
                    boost_map[code] = 1.3
                else:
                    # 想学医但选科不全 ? 警告但不阻断
                    boost_map[code] = 1.0
                    # 标记选科警告（在后续 reason 中体现）
            elif track == "医学" and stance == "可以接受":
                boost_map[code] = 1.0  # 无加成无惩罚

        # ------------------------------------------------------------------
        # 师范赛道处理
        # ------------------------------------------------------------------
        elif st == "师范":
            if track == "师范" and stance == "极度抗拒":
                blocked = True
                blocked_majors.append({
                    "major": major,
                    "reason": "特殊赛道阻断：用户极度抗拒师范方向",
                })
            elif track == "师范" and stance == "强烈意向":
                boost_map[code] = 1.2
            elif track == "师范" and stance == "可以接受":
                boost_map[code] = 1.0

        # ------------------------------------------------------------------
        # 军警赛道处理
        # ------------------------------------------------------------------
        elif st == "军警":
            if track != "军警" or stance != "强烈意向":
                # 军警必须主动且强烈选择
                blocked = True
                blocked_majors.append({
                    "major": major,
                    "reason": "特殊赛道阻断：军警方向需主动且强烈选择",
                })
            else:
                user_conds = set(user.physical_conditions)
                conflicts = MILITARY_PHYSICAL_RESTRICTIONS & user_conds
                if conflicts:
                    blocked = True
                    blocked_majors.append({
                        "major": major,
                        "reason": f"军警体检不通过：{', '.join(sorted(conflicts))}",
                    })
                else:
                    boost_map[code] = 1.5

        if not blocked:
            survivors.append(major)

    return survivors, boost_map, blocked_majors


# ============================================================================
# Step 3: 基础匹配分计算
# ============================================================================

def step3_compute_base_score(
    user: UserProfile,
    major: dict,
    adjusted_macro: dict[str, float],
) -> tuple[float, float, float, float]:
    """
    第 3 步：基础匹配分 (Base Score)

    公式：
      Base Score = 0.30 × 人格匹配度 + 0.30 × 产业匹配度 + 0.40 × 微观行为匹配度

    三个分量均使用余弦相似度：
      - 人格匹配：用户推断 RIASEC 向量 vs 专业 personality_profile
      - 产业匹配：用户衰减后产业向量 vs 专业 industry_mapping
      - 微观匹配：用户微观行为向量 vs 专业 micro_action_tags

    权重设计逻辑：
      - 微观行为 40%：最难伪造、最稳定、最能预测真实适配
      - 产业向往 30%：有参考价值但可能变化，且已被 Step 0 衰减
      - 人格大类 30%：对性格与专业氛围的宏观匹配

    Args:
        user: 用户画像
        major: 专业数据
        adjusted_macro: Step 0 衰减后的产业向量

    Returns:
        (base_score, personality_sim, industry_sim, micro_sim)
    """
    # ------------------------------------------------------------------
    # 分量 1：人格匹配 (30%)
    # ------------------------------------------------------------------
    personality_dims = ["R", "I", "A", "S", "E", "C"]
    user_p_vec = [user.inferred_personality.get(d, 50.0) / 100.0 for d in personality_dims]
    major_p_vec = [major.get("personality_profile", {}).get(d, 0.5) for d in personality_dims]
    personality_sim = cosine_similarity(user_p_vec, major_p_vec)

    # ------------------------------------------------------------------
    # 分量 2：产业匹配 (30%)
    # ------------------------------------------------------------------
    user_i_vec = [adjusted_macro.get(ind, 0) / 100.0 for ind in INDUSTRY_CLUSTERS]
    major_i_vec = [major.get("industry_mapping", {}).get(ind, 0) for ind in INDUSTRY_CLUSTERS]
    industry_sim = cosine_similarity(user_i_vec, major_i_vec)

    # ------------------------------------------------------------------
    # 分量 3：微观行为匹配 (40%)
    # ------------------------------------------------------------------
    user_b_vec = [user.micro_behavior_vector.get(b, 50.0) / 100.0 for b in BEHAVIOR_DIMENSIONS]
    major_b_vec = [major.get("micro_action_tags", {}).get(b, 0.5) for b in BEHAVIOR_DIMENSIONS]
    micro_sim = cosine_similarity(user_b_vec, major_b_vec)

    # ------------------------------------------------------------------
    # 加权合成
    # ------------------------------------------------------------------
    base_score = 0.30 * personality_sim + 0.30 * industry_sim + 0.40 * micro_sim

    return base_score, personality_sim, industry_sim, micro_sim


# ============================================================================
# Step 4: 现实折损
# ============================================================================

def step4_reality_penalty(
    user: UserProfile,
    major: dict,
    base_score: float,
) -> tuple[float, float, float, list[str]]:
    """
    第 4 步：现实折损 (Reality Penalty)

    折损 a：分数位次折损
      - "高分敏感" + 用户在中低分段 ? 当前得分 × 0.4
        逻辑：有些专业（如临床医学）的顶尖院校高度集中在985/211，
        低分段即使进了同名专业，教育质量和就业出口也天差地别。
      - "低分段友好" + 用户在任何分段 ? 当前得分 × 1.5
        逻辑：有些专业（如护理学、机械）在不同层次院校间教育质量差距较小，
        更靠个人手艺而非学校牌子 ? 低分段也能翻身。
      - "中分段陷阱" ? 当前得分 × 0.7
        逻辑：有些专业（如生物、化学）在普通院校的出口极差，
        中低分段学生容易"进了坑才发现没出路"。

    折损 b：家庭抗风险折损
      - 家庭资源弱 + 专业"高资金/长周期壁垒" ? × 0.5
        例：医学5+3+X培养周期长，家庭经济吃紧则中期压力巨大
      - 家庭资源弱 + 专业"强资源驱动" ? × 0.5
        例：金融行业高度依赖一线城市人脉资源和家庭背景
      - 家庭资源弱 + 专业"高下限/手艺饭" ? × 1.2
        例：护理、机械??有手艺就能吃饭，受经济周期冲击小

    Args:
        user: 用户画像
        major: 专业数据
        base_score: Step 3 输出的基础匹配分

    Returns:
        (adjusted_score, score_penalty, resource_penalty, warnings)
    """
    score_penalty = 1.0
    resource_penalty = 1.0
    warnings = []

    ss = major.get("score_sensitivity", {})
    user_pct = user.estimated_rank_percentile
    segment = ss.get("segment", "")

    # ------------------------------------------------------------------
    # 折损 a：分数位次
    # ------------------------------------------------------------------

    # 高分敏感型专业：非高分段用户打折
    if segment == "高分敏感":
        if user_pct > 25:  # 前25%以外
            score_penalty = 0.4
            warnings.append(
                f"[!] 分数排雷：{major['专业名称']}属于'高分敏感'型专业，"
                f"你当前位次（前{user_pct}%）匹配该专业顶尖院校的概率较低。"
                f"若接受普通院校，请降低就业预期。"
            )
        elif user_pct > 15:
            score_penalty = 0.7
            warnings.append(
                f"[!] 分数预警：{major['专业名称']}头部院校竞争激烈，"
                f"你当前位次（前{user_pct}%）需谨慎选择院校层次。"
            )

    # 中分段陷阱：给中低分段用户打预防针
    elif segment == "中分段陷阱":
        if user_pct > 20:
            score_penalty = 0.7
            warnings.append(
                f"[!] 中分段陷阱：{major['专业名称']}在普通院校的科研资源和就业出口"
                f"与顶尖院校差距极大。中低分段慎入，建议优先选择应用型方向。"
            )

    # 低分段友好：加成分
    elif segment == "低分段友好":
        if user_pct > 25:
            score_penalty = 1.5
            # 高分段用户不加成（高分段选低分段友好型浪费分数）

    # ------------------------------------------------------------------
    # 折损 b：家庭抗风险能力
    # ------------------------------------------------------------------
    ast = major.get("asset_sensitivity_tags", {})

    # 判断家庭资源是否薄弱
    is_resource_weak = (
        user.family_economic_level == "低"
        and user.family_city_tier in ("三线及以下", "二线")
        and not user.family_has_overseas_resource
        and user.family_has_industry_connection == "无"
    )

    if is_resource_weak:
        # 高资金/长周期壁垒
        if ast.get("家庭经济支持", 0) >= 0.5:
            resource_penalty *= 0.5
            warnings.append(
                f"[Money] 经济排雷：{major['专业名称']}培养周期长、前期投入大"
                f"（家庭经济支持依赖度 {ast['家庭经济支持']:.0%}）。"
                f"你当前家庭经济条件可能在中途面临较大压力。"
            )

        # 强资源驱动
        if ast.get("行业人脉依赖", 0) >= 0.6:
            resource_penalty *= 0.5
            warnings.append(
                f"[Link] 人脉排雷：{major['专业名称']}高度依赖行业人脉和一线城市资源"
                f"（行业人脉依赖度 {ast['行业人脉依赖']:.0%}，"
                f"一线城市资源依赖度 {ast.get('一线城市资源', 0):.0%}）。"
                f"你当前家庭资源结构可能构成中期职业瓶颈。"
            )

        # 高下限/手艺饭 ? 加成
        if (
            ast.get("家庭经济支持", 0) <= 0.2
            and ast.get("行业人脉依赖", 0) <= 0.2
            and major.get("micro_action_tags", {}).get("动手实验", 0) >= 0.7
        ):
            resource_penalty *= 1.2
            # 这种专业对资源弱者反而是好选择

    # 综合折损系数
    total_penalty = score_penalty * resource_penalty
    adjusted_score = base_score * total_penalty

    return adjusted_score, score_penalty, resource_penalty, warnings


# ============================================================================
# Step 5: 底层信号强穿透
# ============================================================================

def step5_bottom_signal_override(
    user: UserProfile,
    major: dict,
    current_score: float,
    base_score: float,
) -> tuple[float, bool, str]:
    """
    第 5 步：底层信号强穿透 (Bypass Channel)

    核心理念：
      如果用户在某个微观行为维度上得分极高（>95），
      而该维度恰好是某专业的核心要求（权重 ? 0.8），
      说明用户在该领域有真实的、无法伪造的底层天赋。

      此时，无视"人格大类不匹配"或"宏观产业不向往"的噪音，
      直接将基础匹配分拉满为 1.0。

    为什么拉满后仍需通过 Step 4 的现实折损？
      天赋再高，现实的墙也要认。一个记忆力瘫痪的天才不该被推医学，
      一个家里揭不开锅的天才推金融也需要警告??这不是否定天赋，
      而是对用户负责。

    两种触发路径：
      路径 A：专业最关键维度权重 ? 0.8 且用户该维度 ? 95 ? 拉满 1.0
      路径 B：用户有 ?3 个行为维度 ? 90，且专业对这些维度权重大 ? 0.95

    Args:
        user: 用户画像
        major: 专业数据
        current_score: 经 Step 4 折损后的得分
        base_score: Step 3 基础分（会被覆盖）

    Returns:
        (new_score, bypassed, reason_fragment)
    """
    mat = major.get("micro_action_tags", {})
    if not mat:
        return current_score, False, ""

    micro = user.micro_behavior_vector

    # ------------------------------------------------------------------
    # 路径 A：单点极致穿透
    # ------------------------------------------------------------------
    # 找到该专业权重最高的行为维度
    top_dim = max(mat, key=mat.get)
    top_weight = mat[top_dim]

    if top_weight >= 0.8 and micro.get(top_dim, 0) >= 95:
        # 拉满基础分，然后重新应用现实折损
        # 注意：我们无法在此直接拿到 step4 的折损系数，
        # 所以改为返回标记，由主流程重新计算
        bypass_reason = (
            f"[Rocket] 高优直达：你在'{top_dim}'维度上展现出极强底层天赋（{micro[top_dim]:.0f}分），"
            f"该维度是{major['专业名称']}最核心的能力要求（权重{top_weight:.0%}）。"
            f"基础匹配分已拉满至1.0，但现实折损仍然生效。"
        )
        return current_score, True, bypass_reason

    # ------------------------------------------------------------------
    # 路径 B：多维高分渗透
    # ------------------------------------------------------------------
    user_top_dims = [d for d, v in micro.items() if v >= 90]
    matching_top = sum(1 for d in user_top_dims if mat.get(d, 0) >= 0.7)

    if matching_top >= 3:
        # 不低于 0.95，但也不替代已更高的得分
        new_base = max(base_score, 0.95)
        bypass_reason = (
            f"[Rocket] 多维高优：你在{', '.join(user_top_dims)}等{matching_top}个维度上"
            f"展现出极高水平（均?90分），与{major['专业名称']}的核心要求高度吻合。"
        )
        return max(current_score, new_base), True, bypass_reason

    return current_score, False, ""


# ============================================================================
# Step 6: 多样性强制打散
# ============================================================================

def step6_diversity_inject(
    results: list[RecommendationResult],
) -> list[RecommendationResult]:
    """
    第 6 步：多样性强制打散 (Diversity Forcing)

    规则：
      - 若 Top 3 全部属于同一"学科门类"，
      - 则在第 4 名位置强制插入一个不属于该门类、且在剩余候选中得分最高的专业
      - 被插入的专业标记为 [跨界 Plan B]

    设计目的：
      防止用户因为"我在某个维度得分极高"就被困在单一学科门类的回音壁里。
      高考志愿的本质是"给自己留可能性"，而非"在最擅长的路上走到黑"。

    Args:
        results: 按 final_score 降序排列的全部推荐结果

    Returns:
        经过多样性打散后的推荐结果列表（排名已更新）
    """
    if len(results) < 5:
        return results

    # 检查 Top 3 的学科门类
    top3_categories = set()
    for r in results[:3]:
        top3_categories.add(r.major.get("学科门类", ""))

    if len(top3_categories) > 1:
        # 已经足够多样，无需打散
        return results

    # Top 3 全部同一门类 ? 需要注入
    dominant_category = list(top3_categories)[0]

    # 在 Top 5 之外寻找最佳跨学科候选
    # （不只看 Top 5 之外，而是整个列表）
    for i, r in enumerate(results):
        if i < 3:  # 跳过 Top 3
            continue
        cat = r.major.get("学科门类", "")
        if cat != dominant_category:
            # 找到第一个跨学科高分的 ? 注入
            injection = r
            injection.label = "跨界Plan B"
            injection.rank = 4  # 暂定第4名

            # 从原位置移除
            results = [x for x in results if x.major.get("专业代码") != injection.major.get("专业代码")]
            # 插入到第4名（index 3）
            results.insert(3, injection)

            # 重新排名
            for idx, res in enumerate(results):
                res.rank = idx + 1

            return results

    return results


# ============================================================================
# 主推荐管线
# ============================================================================

def recommend(
    user: UserProfile,
    majors_db: list[dict],
    top_n: int = 10,
    verbose: bool = True,
) -> dict:
    """
    高考志愿智能推荐引擎 ? 主入口

    6 步管线依次执行，最终返回 Top N 推荐结果。

    Args:
        user: 用户画像（包含硬约束、家庭资源、问卷结果）
        majors_db: 增强专业数据库（来自 enhanced_majors.json）
        top_n: 返回前 N 个推荐
        verbose: 是否打印详细过程（测试用）

    Returns:
        {
            "results": list[RecommendationResult],  # 最终推荐列表
            "pipeline_log": dict,                   # 各步骤处理日志
            "user_summary": str,                    # 用户画像摘要
        }
    """
    pipeline_log = {}

    # ==================================================================
    # Step 0: 情绪测谎与置信度降维
    # ==================================================================
    adjusted_macro, lie_score, contradiction_details = step0_lie_detection(user)
    pipeline_log["step0"] = {
        "lie_score": lie_score,
        "contradiction_count": len(contradiction_details),
        "details": contradiction_details,
    }

    if verbose and contradiction_details:
        print(f"\n[Step 0: 情绪测谎]")
        print(f"  矛盾检测: {len(contradiction_details)}/{len(CONSISTENCY_RULES)} 规则触发")
        for cd in contradiction_details:
            print(f"    ? {cd['cluster']}: {cd['label']}")
            print(f"       宏观原值 {cd['macro_original']:.1f} ? 衰减后 {cd['macro_adjusted']:.1f}")
            print(f"       微观均值 {cd['micro_avg']:.1f} < 阈值 {cd['threshold']}")
        print(f"  全局置信度: {'高' if lie_score < 0.15 else '中' if lie_score < 0.35 else '低'} (lie_score={lie_score:.2f})")

    # ==================================================================
    # Step 1: 生死红线过滤
    # ==================================================================
    survivors, blocked_step1 = step1_red_line_filter(user, majors_db)
    pipeline_log["step1"] = {
        "total_in": len(majors_db),
        "survivors": len(survivors),
        "blocked": len(blocked_step1),
        "blocked_details": blocked_step1,
    }

    if verbose:
        print(f"\n[Step 1: 生死红线过滤]")
        print(f"  输入: {len(majors_db)} 专业")
        print(f"  通过: {len(survivors)} 专业")
        print(f"  过滤: {len(blocked_step1)} 专业")
        for bm in blocked_step1:
            name = bm["major"]["专业名称"]
            reasons = "; ".join(bm["reasons"])
            print(f"    [X] {name}: {reasons}")

    # ==================================================================
    # Step 2: 特殊赛道阻断与提权
    # ==================================================================
    survivors, boost_map, blocked_step2 = step2_special_track(user, survivors)
    pipeline_log["step2"] = {
        "survivors": len(survivors),
        "boost_map": boost_map,
        "blocked": len(blocked_step2),
        "blocked_details": blocked_step2,
    }

    if verbose:
        print(f"\n[Step 2: 特殊赛道]")
        track_info = user.special_track_intent or "无"
        stance_info = user.special_track_stance or "未表态"
        print(f"  用户意图: {track_info} ({stance_info})")
        if blocked_step2:
            print(f"  阻断: {len(blocked_step2)} 专业")
            for bm in blocked_step2:
                name = bm["major"]["专业名称"]
                print(f"    [X] {name}: {bm['reason']}")
        if boost_map:
            print(f"  提权: {len(boost_map)} 专业")
            for code, boost in boost_map.items():
                if boost > 1.0:
                    # 找到对应专业名
                    name = code
                    for m in survivors:
                        if m.get("专业代码") == code:
                            name = m.get("专业名称", code)
                            break
                    print(f"    [Rocket] {name}: boost ×{boost:.1f}")

    # ==================================================================
    # Step 3: 基础匹配分
    # ==================================================================
    results = []
    for major in survivors:
        base_score, personality_sim, industry_sim, micro_sim = step3_compute_base_score(
            user, major, adjusted_macro
        )

        # 应用 Step 2 的 boost
        code = major.get("专业代码", "")
        boost = boost_map.get(code, 1.0)
        if boost != 1.0:
            base_score *= boost

        r = RecommendationResult(
            major=major,
            base_score=clamp(base_score),
            personality_sim=personality_sim,
            industry_sim=industry_sim,
            micro_sim=micro_sim,
            boosted=(boost != 1.0),
        )
        results.append(r)

    pipeline_log["step3"] = {
        "scored_count": len(results),
        "avg_base_score": round(sum(r.base_score for r in results) / max(len(results), 1), 3),
    }

    if verbose:
        print(f"\n[Step 3: 基础匹配分]")
        print(f"  已评分: {len(results)} 专业")
        print(f"  平均基础分: {pipeline_log['step3']['avg_base_score']:.3f}")

    # ==================================================================
    # Step 4: 现实折损
    # ==================================================================
    for r in results:
        adjusted, score_pen, res_pen, warnings = step4_reality_penalty(
            user, r.major, r.base_score
        )
        r.final_score = clamp(adjusted)
        r.reality_penalty = score_pen * res_pen
        r.score_penalty = score_pen
        r.resource_penalty = res_pen
        r.warnings = warnings

    pipeline_log["step4"] = {
        "avg_reality_penalty": round(
            sum(r.reality_penalty for r in results) / max(len(results), 1), 3
        ),
    }

    if verbose:
        print(f"\n[Step 4: 现实折损]")
        print(f"  平均折损系数: {pipeline_log['step4']['avg_reality_penalty']:.3f}")
        penalized = [r for r in results if r.reality_penalty < 0.9]
        if penalized:
            print(f"  受折损专业: {len(penalized)} 个")
            for r in penalized[:5]:
                print(f"    [!] {r.major['专业名称']}: 基础{r.base_score:.2f} × {r.reality_penalty:.2f} = 最终{r.final_score:.2f}")

    # ==================================================================
    # Step 5: 底层信号强穿透
    # ==================================================================
    bypass_count = 0
    for r in results:
        # 先按正常流程的 base_score ? 再尝试穿透
        new_score, bypassed, reason = step5_bottom_signal_override(
            user, r.major, r.final_score, r.base_score
        )
        if bypassed:
            r.final_score = clamp(new_score)
            r.bypassed = True
            r.base_score = 1.0  # 穿透后基础分视为1.0
            # 重新计算 final = 1.0 * reality_penalty
            r.final_score = clamp(1.0 * r.reality_penalty)
            bypass_count += 1
            if reason and verbose:
                pass  # reason 将在生成理由时使用

    pipeline_log["step5"] = {"bypass_count": bypass_count}

    if verbose:
        print(f"\n[Step 5: 底层信号强穿透]")
        print(f"  穿透触发: {bypass_count} 专业")
        for r in results:
            if r.bypassed:
                print(f"    [Rocket] {r.major['专业名称']}: 基础分拉满至1.0, 最终={r.final_score:.2f}")

    # ==================================================================
    # Step 6: 排序 + 打标签 + 多样性打散
    # ==================================================================
    # 按 final_score 降序排列
    results.sort(key=lambda r: r.final_score, reverse=True)

    # 先分配标签（打散前）
    for r in results:
        r.label = _assign_label(r, user)

    # 多样性强制打散
    results = step6_diversity_inject(results)

    # 截取 Top N
    top_results = results[:top_n]

    # 为每个结果生成推荐理由
    for r in top_results:
        r.reason = _generate_reason(r, user)

    pipeline_log["step6"] = {
        "top_categories": list(set(
            r.major.get("学科门类", "") for r in top_results[:5]
        )),
        "diversity_ok": len(set(
            r.major.get("学科门类", "") for r in top_results[:3]
        )) > 1 if len(top_results) >= 3 else True,
    }

    if verbose:
        print(f"\n[Step 6: 多样性打散]")
        top3_cats = [r.major.get("学科门类", "") for r in top_results[:3]]
        print(f"  Top 3 门类: {top3_cats}")
        print(f"  多样性: {'[OK] 已打散' if pipeline_log['step6']['diversity_ok'] else '[!] 已注入跨界Plan B'}")
        for r in top_results[:3]:
            if r.label == "跨界Plan B":
                print(f"    [Loop] {r.major['专业名称']} ({r.major['学科门类']}): {r.label}")

    # ==================================================================
    # 组装返回
    # ==================================================================
    return {
        "results": top_results,
        "pipeline_log": pipeline_log,
        "user_summary": user.summarize(),
    }


# ============================================================================
# 标签分配
# ============================================================================

def _assign_label(result: RecommendationResult, user: UserProfile) -> str:
    """
    根据最终得分、折损情况和穿透状态分配推荐标签。

    标签体系：
      - 高优直达：final >= 0.75 且 bypassed 或高匹配无预警
      - 排雷预警：reality_penalty < 0.6 或有严重警告
      - 跨界Plan B：由 Step 6 注入（此处暂不分配，由 Step 6 覆写）
      - 标准推荐：其余情况
    """
    if result.bypassed:
        return "高优直达"

    if result.reality_penalty < 0.5:
        return "排雷预警"

    if result.final_score >= 0.75:
        return "高优直达"

    if result.warnings and len(result.warnings) >= 2:
        return "排雷预警"

    return "标准推荐"


# ============================================================================
# 推荐理由生成
# ============================================================================

def _generate_reason(result: RecommendationResult, user: UserProfile) -> str:
    """
    为推荐结果生成人类可读的个性化解释。

    理由结构：
      - 开头：核心匹配维度 + 得分亮点
      - 中间（如有）：排雷预警
      - 结尾：行动建议
    """
    major = result.major
    name = major.get("专业名称", "该专业")
    category = major.get("学科门类", "")
    zyl = major.get("专业类", "")

    parts = []

    # ---- 核心匹配说明 ----
    if result.bypassed:
        top_behaviors = user.get_top_behaviors(3)
        behavior_str = "、".join(f"{k}({v:.0f}分)" for k, v in top_behaviors)
        parts.append(
            f"你在微观行为维度上展现出极强的底层信号（{behavior_str}），"
            f"该信号直接击穿了{name}的核心能力门槛，触发高优直达通道。"
        )
    else:
        # 说明哪部分匹配最突出
        sims = [
            ("人格倾向", result.personality_sim),
            ("产业向往", result.industry_sim),
            ("微观行为", result.micro_sim),
        ]
        best_dim, best_sim = max(sims, key=lambda x: x[1])

        if best_sim >= 0.85:
            parts.append(f"你与{name}在'{best_dim}'维度上高度契合（匹配度{best_sim:.0%}），")
        elif best_sim >= 0.7:
            parts.append(f"你与{name}在'{best_dim}'维度上较为匹配（匹配度{best_sim:.0%}），")
        else:
            parts.append(f"你与{name}整体匹配度中等（最高维度'{best_dim}' {best_sim:.0%}），")

        # 补充说明专业特点
        mat = major.get("micro_action_tags", {})
        top_major_dims = sorted(mat.items(), key=lambda x: x[1], reverse=True)[:3]
        top_dims_str = "、".join(f"{d}(权重{w:.0%})" for d, w in top_major_dims)
        parts.append(f"该专业的核心能力要求为{top_dims_str}。")

    # ---- 分数位次说明（仅当折损时） ----
    if result.score_penalty < 0.9:
        parts.append(f"注意：你当前位次（前{user.estimated_rank_percentile}%）与该专业的分数门槛有一定差距，建议在院校选择上做好梯度规划。")

    # ---- 排雷预警（如有） ----
    if result.warnings:
        for w in result.warnings[:2]:  # 最多2条警告
            parts.append(w)

    # ---- 行动建议 ----
    if result.label == "高优直达":
        parts.append(f"建议将该专业作为第一梯队核心志愿，重点研究目标院校的专业排名。")
    elif result.label == "排雷预警":
        parts.append(f"若仍决定报考，请充分了解上述风险并制定备选方案。")
    elif result.label == "跨界Plan B":
        parts.append(f"这是一个跨学科备选方案，为你提供一个不同于主流推荐方向的参考选项。")
    else:
        parts.append(f"可将此专业作为中位志愿，与冲刺志愿和保底志愿搭配填报。")

    return " ".join(parts)


# ============================================================================
# 便捷入口
# ============================================================================

def load_enhanced_majors(filepath: str = "enhanced_majors.json") -> list[dict]:
    """加载增强专业数据库"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 过滤掉注释条目
    return [d for d in data if "专业代码" in d]


def recommend_for_user(
    user: UserProfile,
    majors_file: str = "enhanced_majors.json",
    top_n: int = 10,
    verbose: bool = True,
) -> dict:
    """
    一站式推荐入口：加载专业库 ? 运行管线 ? 返回结果
    """
    majors = load_enhanced_majors(majors_file)
    return recommend(user, majors, top_n, verbose)


# ============================================================================
# 便捷打印
# ============================================================================

def print_results(report: dict) -> None:
    """美化打印推荐结果（用于测试和演示）"""
    results = report["results"]
    pipeline_log = report["pipeline_log"]

    print()
    print("=" * 72)
    print("   ? 高考志愿智能推荐引擎 v5.0 ? 最终推荐结果")
    print("=" * 72)

    print()
    print(report["user_summary"])
    print()

    print("-" * 72)
    print(f"  {'排名':<6} {'专业名称':<22} {'门类':<8} {'基础分':<8} {'最终分':<8} {'标签'}")
    print("-" * 72)

    for r in results:
        label_icon = {
            "高优直达": "[Rocket]",
            "排雷预警": "[!]",
            "跨界Plan B": "[Loop]",
            "标准推荐": "[OK]",
        }.get(r.label, "[OK]")

        print(
            f"  {label_icon} #{r.rank:<3} "
            f"{r.major['专业名称']:<22} "
            f"{r.major.get('学科门类', ''):<8} "
            f"{r.base_score:.3f}   "
            f"{r.final_score:.3f}   "
            f"{r.label}"
        )

    print("-" * 72)

    # 打印各专业的推荐理由
    print()
    print("[Note] 详细推荐理由：")
    print()
    for r in results:
        icon = {"高优直达": "[Rocket]", "排雷预警": "[!]", "跨界Plan B": "[Loop]", "标准推荐": "[OK]"}.get(r.label, "[OK]")
        print(f"  {icon} #{r.rank} {r.major['专业名称']} ({r.major.get('学科门类', '')}/{r.major.get('专业类', '')})")
        print(f"     标签: {r.label}")
        print(f"     基础分: {r.base_score:.3f} | 人格:{r.personality_sim:.2f} 产业:{r.industry_sim:.2f} 微观:{r.micro_sim:.2f}")
        print(f"     折损: {r.reality_penalty:.2f} (分数×{r.score_penalty:.2f} 资源×{r.resource_penalty:.2f})")
        print(f"     最终分: {r.final_score:.3f}")
        if r.bypassed:
            print(f"     ? 已触发底层信号强穿透")
        if r.boosted:
            print(f"     [Chart] 已触发特殊赛道提权")
        print(f"     [Msg] {r.reason}")
        if r.warnings:
            for w in r.warnings:
                print(f"     {w}")
        print()


if __name__ == "__main__":
    # 快速自测
    from user_profile import create_test_user

    user = create_test_user()
    report = recommend_for_user(user, verbose=True)
    print_results(report)
