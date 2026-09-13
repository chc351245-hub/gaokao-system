# -*- coding: utf-8 -*-
"""
================================================================================
 算法质量回归测试 — test_algorithm_quality.py
================================================================================
 这个文件锁定的不是"代码能跑"，而是"算法没有退化成无效"。

 背景：修复前实测到以下失效现象，本测试把它们逐条变成断言，防止回归——
   1. 产业向量 10 个值加起来恒等于 100（是分布不是绝对分），导致 `>=60` 的
      "用户核心产业"门槛 300 份答卷 0 份能达到 → 永远走硬编码兜底。
   2. Layer 2 的 industry_match 用 Jaccard(用户集 ∪ 专业类集)，专业类覆盖产业
      越多分母越大、得分越低 → 完全倒挂（物流管理 0.50 > 计算机 0.25）。
   3. risk_tier 恒为 low（500 份答卷 high 出现 0 次）→ heat_align 退化成常数。
   4. 不同画像用户的结果高度重合（医学助人 vs 随机答卷 Top8 交集 8/8）。
   5. min(1.0, score) 截断让被提权的专业类并列在 1.000。

 运行：python test_algorithm_quality.py
================================================================================
"""
import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from questionnaire import (
    MACRO_QUESTIONS, MICRO_QUESTIONS, VALUE_DIMENSIONS,
    score_macro_questions, score_micro_questions, build_user_from_answers,
    declared_industry_from_answers,
)
from user_profile import BEHAVIOR_DIMENSIONS
import funnel_engine as FE
from funnel_engine import (
    load_funnel_data, run_funnel, layer1_discipline_match,
    layer2_category_match, get_top_industries, _risk_tier,
    _weighted_mean_ratio, RISK_TIER_MEDIUM, declared_direction_note,
)

_FAILURES = []


def check(cond: bool, label: str, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _FAILURES.append(label)


# ---------------------------------------------------------------------------
# 测试用画像构造
# ---------------------------------------------------------------------------

def best_macro_for(target: str) -> dict:
    """每题都选最偏向 target 产业方向的选项（构造一个立场最鲜明的用户）

    坑：M11 的选项 A~F 各只覆盖一组冷门方向，对一个主流 target 的权重**全是 0**。
    直接 max() 会把并列的最大值判给**第一个**选项（A = 建筑/土木/城规），于是
    「人工智能」画像的测试用户凭空多出一个建筑意向，把土木类顶到第一名——
    这是构造画像时的假象，不是引擎的锅。所以这里显式跳过零权重的选项；
    整题都没有带该 target 的选项时，选那个**不带任何产业权重**的选项
    （即「以上都不是」），与真实用户作答的语义一致。
    """
    out = {}
    for q in MACRO_QUESTIONS:
        weights = {k: v["industry_weights"].get(target, 0.0)
                   for k, v in q["options"].items()}
        if max(weights.values()) <= 0.0:
            neutral = [k for k, v in q["options"].items() if not v["industry_weights"]]
            out[q["id"]] = neutral[0] if neutral else next(iter(q["options"]))
        else:
            out[q["id"]] = max(weights, key=lambda k: weights[k])
    return out


def micro_for(dim_weights: dict) -> dict:
    """每题都选最有利于给定维度权重分布的选项（最大化点积）"""
    return {
        q["id"]: max(q["options"].items(),
                     key=lambda kv: sum(w * kv[1]["dims"].get(dk, 0)
                                        for dk, w in dim_weights.items()))[0]
        for q in MICRO_QUESTIONS
    }


PROFILES = {
    "技术/编程": (best_macro_for("人工智能/大模型"),
                 micro_for({"logic": 3.0, "hands_on": 3.0, "focus": 2.5,
                            "data_sense": 2.0, "detail": 1.0}),
                 ["物理", "化学", "生物"], 15.0),
    "传媒/创作": (best_macro_for("传媒/广告/公关"),
                 micro_for({"creative": 3.0, "comm": 3.0, "memory": 1.0, "team": 1.0}),
                 ["历史", "地理", "政治"], 25.0),
    "医学/临床": (best_macro_for("医疗健康/临床"),
                 micro_for({"memory": 3.0, "focus": 2.5, "detail": 2.0,
                            "stress_tol": 2.5, "logic": 1.0}),
                 ["物理", "化学", "生物"], 15.0),
    "金融/商业": (best_macro_for("金融/银行"),
                 micro_for({"data_sense": 3.0, "logic": 2.0, "comm": 2.5,
                            "stress_tol": 2.0}),
                 ["物理", "化学", "生物"], 12.0),
}


def build_profiles():
    out = {}
    for name, (macro, micro, subjects, pct) in PROFILES.items():
        out[name] = build_user_from_answers(
            macro, micro, selected_subjects=subjects,
            estimated_rank_percentile=pct,
        )
    return out


# ---------------------------------------------------------------------------
# Test 1：评分函数必须按「每个维度各自的上限」归一化
# ---------------------------------------------------------------------------

def test_normalization():
    print("\n[Test 1] 向量归一化：各维度必须能达到满分（修复前上限 55.7~83.3）")

    dim_map = {"logic": "逻辑推理", "hands_on": "动手实验", "team": "团队协作",
               "creative": "创造性思维", "detail": "精细操作", "focus": "持续专注",
               "comm": "沟通表达", "data_sense": "数据敏感",
               "stress_tol": "抗压能力", "memory": "记忆积累"}

    ceilings = {}
    for dim in BEHAVIOR_DIMENSIONS:
        answers = {}
        for q in MICRO_QUESTIONS:
            answers[q["id"]] = max(
                q["options"].items(),
                key=lambda kv: sum(dl for dk, dl in kv[1]["dims"].items()
                                   if dim_map.get(dk, dk) == dim and dl > 0))[0]
        ceilings[dim] = score_micro_questions(answers)[dim]

    worst = min(ceilings.values())
    check(worst >= 99.9,
          "微观行为 10 个维度均可达到 100 分",
          f"最低维度上限 = {worst:.1f}")

    # 产业向量必须能突破旧代码的 60 分门槛（旧实现 400 份答卷全部 < 60）
    iv, _ = score_macro_questions(best_macro_for("人工智能/大模型"))
    check(iv["人工智能/大模型"] >= 90.0,
          "鲜明立场的用户其目标产业分可达 90+",
          f"人工智能/大模型 = {iv['人工智能/大模型']:.1f}")

    # 风险容忍度必须能突破 high 档门槛（旧实现 high 出现 0 次）
    _, vv = score_macro_questions(
        {q["id"]: "B" for q in MACRO_QUESTIONS} | {"M6": "D", "M8": "A"})
    check(vv["风险容忍度"] >= 65.0,
          "明确偏好高风险的答卷其风险容忍度可达 high 档",
          f"风险容忍度 = {vv['风险容忍度']:.1f}")

    _, vv_low = score_macro_questions(
        {q["id"]: "B" for q in MACRO_QUESTIONS} | {"M6": "A", "M8": "B"})
    check(vv_low["风险容忍度"] < 35.0,
          "明确偏好稳定的答卷其风险容忍度落在 low 档",
          f"风险容忍度 = {vv_low['风险容忍度']:.1f}")


# ---------------------------------------------------------------------------
# Test 2：industry_match 必须单调（修复前是倒挂的）
# ---------------------------------------------------------------------------

def test_industry_match_monotonic():
    print("\n[Test 2] industry_match 单调性（修复前：覆盖越广得分越低，完全倒挂）")

    data = load_funnel_data()
    user = build_profiles()["技术/编程"]
    l1 = layer1_discipline_match(user, data)
    cats = {c["category_name"]: c for c in
            layer2_category_match(user, data, l1, top_n=999)}

    cs = cats["计算机类"]["industry_match"]
    wl = cats["物流管理与工程类"]["industry_match"]
    check(cs > wl,
          "技术爱好者：计算机类 > 物流管理与工程类",
          f"计算机类={cs:.3f} vs 物流管理={wl:.3f}（修复前 0.250 < 0.500）")

    # 达标项：用户真正有意向的产业，其对应专业类必须能拿到非零的 industry_match。
    # 修复前这些是「结构性恒 0」——无论用户多想学医，医学类的 industry_match 都是 0。
    # 注意 industry_match 是「覆盖我意向的比例」，因此对无意向的产业为 0 是正确的，
    # 断言必须逐画像地针对「该用户有意向的产业」来下，不能笼统要求全表非零。
    probes = {
        "技术/编程": ["计算机类", "电子信息类", "自动化类", "数学类"],
        "传媒/创作": ["中国语言文学类", "新闻传播学类", "外国语言文学类"],
        "医学/临床": ["临床医学类", "基础医学类", "药学类", "护理学类"],
        "金融/商业": ["经济学类", "金融学类", "经济与贸易类", "统计学类"],
    }
    profiles = build_profiles()
    for pname, probes_ in probes.items():
        pu = profiles[pname]
        pl1 = layer1_discipline_match(pu, data)
        pcats = {c["category_name"]: c for c in
                 layer2_category_match(pu, data, pl1, top_n=999)}
        dead = [p for p in probes_ if pcats.get(p, {}).get("industry_match", 0) <= 1e-9]
        check(not dead, f"{pname}: 其意向产业的对应专业类 industry_match 均 > 0",
              f"仍为 0 的: {dead}" if dead else
              f"{['%s=%.2f' % (p, pcats[p]['industry_match']) for p in probes_ if p in pcats]}")

    # 面向用户的强不变式：进入 Top8 的专业类，绝不可能 industry_match = 0
    # （run_funnel 的返回结构不保留 industry_match，故直接看 Layer 2 的 Top8 选取）
    for pname, pu in profiles.items():
        pl1 = layer1_discipline_match(pu, data)
        top8 = layer2_category_match(pu, data, pl1, top_n=8)
        bad = [c["category_name"] for c in top8 if c["industry_match"] <= 1e-9]
        check(not bad, f"{pname}: Top8 中不存在 industry_match=0 的专业类",
              f"混入: {bad}" if bad else
              "; ".join(f"{c['category_name']}={c['industry_match']:.2f}" for c in top8[:4]))

    peak = max(user.macro_industry_vector.values())
    check(len(get_top_industries(user)) >= 1,
          "用户核心产业意向集非空",
          f"峰值={peak:.1f} 意向集={sorted(get_top_industries(user))}")


# ---------------------------------------------------------------------------
# Test 3：risk_tier 三档都必须可用（修复前 high 是死代码）
# ---------------------------------------------------------------------------

def test_risk_tier_spans():
    print("\n[Test 3] risk_tier 分布（修复前 500 份答卷：high=0 / medium=68 / low=432）")
    random.seed(5)
    tiers = {"high": 0, "medium": 0, "low": 0}
    for _ in range(500):
        macro = {f"M{i}": random.choice("ABCD") for i in range(1, 10)} | \
                {"M9": random.choice("ABCDE")}
        micro = {f"U{i}": random.choice("ABCD") for i in range(1, 31)}
        u = build_user_from_answers(macro, micro,
                                    selected_subjects=["物理", "化学", "生物"])
        tiers[_risk_tier(u)] += 1
    check(all(v > 0 for v in tiers.values()),
          "high / medium / low 三档均能出现",
          f"{tiers}")


# ---------------------------------------------------------------------------
# Test 4：不同画像必须得到不同结果（修复前高度重合）
# ---------------------------------------------------------------------------

def test_user_distinctness():
    print("\n[Test 4] 不同画像的结果区分度"
          "（修复前：医学助人 vs 随机答卷 Top8 交集 8/8、专业 Jaccard 0.90）")

    results = {name: run_funnel(u, verbose=False)
               for name, u in build_profiles().items()}

    names = list(results)
    # 「金融/银行」与「AI/互联网」在学科上是真实相邻的（金融工程/量化交易本身就要
    # 计算机+数学+统计），这对画像允许较高重合；其余画像之间必须近乎不相交。
    ADJACENT = {frozenset({"技术/编程", "金融/商业"})}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            sa = {c["category_name"] for c in results[a]}
            sb = {c["category_name"] for c in results[b]}
            shared = sorted(sa & sb)
            ov = len(shared)
            limit = 5 if frozenset({a, b}) in ADJACENT else 2
            check(ov <= limit,
                  f"{a} vs {b} 交集 {ov} ≤ {limit}",
                  f"共同={shared}" if shared else "无交集")

    # 每个画像的 #1 必须落在与它目标产业同门的门类里
    expect_disc = {"技术/编程": {"工学", "理学", "交叉学科"},
                   "传媒/创作": {"文学", "艺术学", "历史学"},
                   "医学/临床": {"医学", "理学"},
                   "金融/商业": {"经济学", "管理学", "理学", "工学"}}
    for name, res in results.items():
        top = res[0]
        check(top["discipline_name"] in expect_disc[name],
              f"{name} 的 #1 门类合理",
              f"#1={top['category_name']}({top['discipline_name']})")


# ---------------------------------------------------------------------------
# Test 5：硬约束（选科 / 体检红线 / 结构上限）
# ---------------------------------------------------------------------------

def test_hard_constraints():
    print("\n[Test 5] 硬约束")

    results = {name: run_funnel(u, verbose=False)
               for name, u in build_profiles().items()}

    struct_ok, struct_detail = True, []
    for name, res in results.items():
        if len(res) > 8:
            struct_ok = False
            struct_detail.append(f"{name} 类别数 {len(res)}>8")
        for c in res:
            if len(c["recommended_majors"]) > 6:
                struct_ok = False
                struct_detail.append(f"{c['category_name']} 专业数>6")
            for m in c["recommended_majors"]:
                if not m["threshold_pass"]:
                    struct_ok = False
                    struct_detail.append(f"{m['major_name']} 红线未过滤")
    check(struct_ok, "类别数≤8 / 每类专业数≤6 / 体检红线全部过滤",
          "; ".join(struct_detail))

    # 选科硬校验：史地政用户不得拿到要求物理的专业类
    phys_required = {"计算机类", "电子信息类", "机械类", "土木类",
                     "临床医学类", "自动化类", "电气类", "材料类"}
    leaked = [c["category_name"] for c in results["传媒/创作"]
              if c["category_name"] in phys_required]
    check(not leaked, "史地政考生未混入物理必选的专业类",
          f"泄漏: {leaked}" if leaked else "无")


# ---------------------------------------------------------------------------
# Test 6：特殊赛道的阻断与提权
# ---------------------------------------------------------------------------

def test_special_track():
    print("\n[Test 6] 特殊赛道阻断 / 提权")

    macro, micro, subjects, pct = PROFILES["医学/临床"]

    def build(track, stance):
        return build_user_from_answers(
            macro, micro, selected_subjects=subjects,
            estimated_rank_percentile=pct,
            special_track_intent=track, special_track_stance=stance)

    res_block = run_funnel(build("医学", "极度抗拒"), verbose=False)
    med = [c["category_name"] for c in res_block if c["discipline_name"] == "医学"]
    check(not med, "声明『极度抗拒医学』→ 推荐中无任何医学类专业类",
          f"残留: {med}" if med else "已全部阻断")

    res_boost = run_funnel(build("医学", "强烈意向"), verbose=False)
    med_boost = [c["category_name"] for c in res_boost if c["discipline_name"] == "医学"]
    check(len(med_boost) >= 1, "声明『强烈意向医学』→ 医学类专业类被提权进入推荐",
          f"进入 {len(med_boost)} 个: {med_boost[:4]}")

    # 军警必须主动选择，否则应被阻断
    res_default = run_funnel(build(None, None), verbose=False)
    mp = [c["category_name"] for c in res_default
          if c["category_name"] in ("公安学类", "公安技术类", "兵器类")]
    check(not mp, "未主动选择军警 → 军警类专业类被阻断",
          f"残留: {mp}" if mp else "已阻断")


# ---------------------------------------------------------------------------
# Test 7：分数截断不得造成并列（修复前 min(1.0, ...) 把提权方向压成 1.000）
# ---------------------------------------------------------------------------

def test_no_clamp_ties():
    print("\n[Test 7] 分数上限（修复前 min(1.0, score) 让多个提权方向并列在 1.000）")

    for name, u in build_profiles().items():
        res = run_funnel(u, verbose=False)
        scores = [c["category_score"] for c in res]
        check(all(s > 0 for s in scores),
              f"{name}: 所有专业类得分 > 0",
              f"范围 {min(scores):.3f}~{max(scores):.3f}")

    # 技术爱好者会被 L1 传导推过 1.0，若截断仍在则最高分恰好是 1.000
    res = run_funnel(build_profiles()["技术/编程"], verbose=False)
    top = max(c["category_score"] for c in res)
    check(abs(top - 1.0) > 1e-6,
          "最高分不被截断在恰好 1.000",
          f"最高分 = {top:.4f}")


def test_output_ordering():
    print("\n[Test 8] 输出顺序必须与展示分数一致"
          "（修复前：多样性打散按位置就地替换，尾部出现 0.887 排在 0.893 前面）")

    for name, u in build_profiles().items():
        res = run_funnel(u, verbose=False)
        scores = [c["category_score"] for c in res]
        bad = [(i, scores[i], scores[i + 1]) for i in range(len(scores) - 1)
               if scores[i] < scores[i + 1]]
        check(not bad, f"{name}: 类别按 category_score 降序排列",
              "; ".join(f"#{i+1} {a:.4f} < #{i+2} {b:.4f}" for i, a, b in bad)
              if bad else f"{len(scores)} 个类别单调递减")

        for c in res:
            ms = [m["major_score"] for m in c["recommended_majors"]]
            badm = [(i, ms[i], ms[i + 1]) for i in range(len(ms) - 1) if ms[i] < ms[i + 1]]
            if badm:
                check(False, f"{name}/{c['category_name']}: 专业按 major_score 降序排列",
                      f"倒挂 {badm}")
                break
        else:
            continue


def test_fit_reality_separation():
    print("\n[Test 9] 契合度 / 现实折损必须分开且各自正确"
          "（修复前 UI 只显示二者混合的一个数，且提示语声称它不含录取概率）")

    data = load_funnel_data()
    profiles = build_profiles()

    for name, u in profiles.items():
        res = run_funnel(u, verbose=False)
        missing = [k for k in ("fit_score", "reality_tier", "reality_score", "reality_reason")
                   if k not in res[0]]
        check(not missing, f"{name}: 输出含契合度/现实折损字段",
              f"缺 {missing}" if missing else
              f"契合度 {res[0]['fit_score']:.3f} / 折损 {res[0]['reality_tier']}")

        bad_tier = [c["reality_tier"] for c in res if c["reality_tier"] not in ("低", "中", "高")]
        check(not bad_tier, f"{name}: 现实折损档位合法", f"异常 {bad_tier}" if bad_tier else "低/中/高")

        bad_reason = [c["category_name"] for c in res
                      if not c.get("reality_reason") or "位次" not in c["reality_reason"]]
        check(not bad_reason, f"{name}: 现实折损理由均说明位次",
              f"缺说明: {bad_reason}" if bad_reason else "全部含位次说明")

    # 展示字段必须来自分项本身，不能是占位默认值（曾因 L3 未透传而恒为 0/高）
    l1 = layer1_discipline_match(profiles["医学/临床"], data)
    l2 = {c["category_name"]: c for c in
          layer2_category_match(profiles["医学/临床"], data, l1, top_n=999)}
    clinical = l2["临床医学类"]
    check(clinical["industry_match"] > 0.99,
          "临床医学类对医学意向用户的契合度为满分",
          f"industry_match={clinical['industry_match']:.3f}")

    # 同一个专业类在不同位次下，现实折损必须给出相反的判断
    # 两个坑：(1) 必须重新 build，否则 profiles["X"] 两次是同一引用，改一个连带改另一个；
    #        (2) 必须为低位次用户重新算一遍 layer2 —— score_match 是随用户位次算好
    #            存进类别字典里的，拿高位次用户的字典去评估低位次用户只会得到旧结果。
    from funnel_engine import _reality_assessment
    u_high = profiles["医学/临床"]
    u_low = build_profiles()["医学/临床"]
    u_low.estimated_rank_percentile = 80.0
    l1_low = layer1_discipline_match(u_low, data)
    l2_low = {c["category_name"]: c for c in
              layer2_category_match(u_low, data, l1_low, top_n=999)}
    n_high = _reality_assessment(l2["护理学类"], u_high)
    n_low = _reality_assessment(l2_low["护理学类"], u_low)
    check(n_high["reality_tier"] == "高" and n_low["reality_tier"] == "低",
          "护理学类：高位次=浪费位次(折损高)，低位次=低分段友好(折损低)",
          f"前15%→{n_high['reality_tier']}, 前60-100%→{n_low['reality_tier']}")

    # 档位不得退化——risk_tier 曾经恒定落在 low（high 出现 0 次），
    # 使 heat_align 变成常数、HEAT_ALIGNMENT_MATRIX 的 high 行成了死代码。
    # 新加的档位必须覆盖全部三档且有实质占比，否则等于没加。
    from collections import Counter
    random.seed(11)
    tiers = Counter()
    for _ in range(60):
        m = {q["id"]: random.choice(list(q["options"])) for q in MACRO_QUESTIONS}
        mi = {q["id"]: random.choice(list(q["options"])) for q in MICRO_QUESTIONS}
        ru = build_user_from_answers(
            m, mi, selected_subjects=["物理", "化学", "生物"],
            estimated_rank_percentile=random.choice([5.0, 20.0, 45.0, 80.0]))
        ru.family_economic_level = random.choice(["高", "中", "低"])
        rl1 = layer1_discipline_match(ru, data)
        for c in layer2_category_match(ru, data, rl1, top_n=999):
            tiers[_reality_assessment(c, ru)["reality_tier"]] += 1
    tot = sum(tiers.values())
    share = {t: tiers[t] / tot for t in ("低", "中", "高")}
    check(all(s > 0.05 for s in share.values()),
          "现实折损三档均非退化（每档 >5%）",
          ", ".join(f"{t}={s*100:.0f}%" for t, s in share.items()))


def test_neutral_options():
    """v6.2：每题一个「都不感兴趣」选项。

    它必须满足两条性质，缺一不可：
      1. 不选它的人分数**一分不差**（分母是各选项最大值，它是 0，取 max 后不变）；
      2. 选了它的人，产业维度上是真"不表态"——不能再被主流方向被动累积。
    """
    print("\n[Test 10] 「都不感兴趣」选项：老用户零影响，新用户能真的不表态")

    neutral_of = {}
    for q in MACRO_QUESTIONS:
        neu = [k for k, v in q["options"].items() if v.get("neutral")]
        neutral_of[q["id"]] = neu[0] if neu else None
    missing = [qid for qid, k in neutral_of.items() if k is None and qid != "M11"]
    check(not missing, "M1–M10 每题都有「都不感兴趣」选项",
          f"缺失: {missing}" if missing else "10/10")

    # 性质 1：把中性选项从题库里摘掉再算，老答卷分数必须逐维度一致
    import questionnaire as _q
    saved = _q.MACRO_QUESTIONS
    random.seed(31)
    old_answers = []
    for _ in range(120):
        old_answers.append({q["id"]: random.choice(
            [k for k, v in q["options"].items() if not v.get("neutral")]) for q in MACRO_QUESTIONS})
    try:
        _q.MACRO_QUESTIONS = [
            {**q, "options": {k: v for k, v in q["options"].items() if not v.get("neutral")}}
            for q in saved]
        without = [_q.score_macro_questions(a) for a in old_answers]
    finally:
        _q.MACRO_QUESTIONS = saved
    with_neutral = [_q.score_macro_questions(a) for a in old_answers]
    check(without == with_neutral,
          "不选「都不感兴趣」的答卷，分数与加选项之前逐维度相同",
          f"{len(old_answers)} 份答卷比对" if without == with_neutral else "出现偏差")

    # 性质 2：全选「都不感兴趣」→ 产业向量必须全 0（医疗健康/临床 不再被动累积）
    all_neutral = {}
    for q in MACRO_QUESTIONS:
        all_neutral[q["id"]] = neutral_of[q["id"]] or "G"
    iv, vv = _q.score_macro_questions(all_neutral)
    check(max(iv.values()) == 0.0,
          "全选「都不感兴趣」→ 产业向量恒为 0（医学类不再被动累积）",
          f"峰值 {max(iv.values()):.1f}，非零维数 {sum(1 for v in iv.values() if v > 0)}")
    # 价值维度不能用 0 表示"没意见"——_risk_tier 的绝对阈值会把 0 读成"极度厌恶风险"
    check(vv["风险容忍度"] >= RISK_TIER_MEDIUM,
          "全选「都不感兴趣」→ 风险容忍度落在中档，而非被判成 low",
          f"风险容忍度={vv['风险容忍度']:.1f}（low 阈值 {RISK_TIER_MEDIUM}）")


def test_order_independent_of_data_file():
    """v6.2：推荐结果不得依赖数据文件里的键顺序。

    改动前实测：把 layer2_categories.json 的键顺序打乱重跑，600 份答卷里有 108 份
    （18%）Top8 名单发生变化——有的专业类直接进榜或掉榜。并列本身是真实的
    （标签集合相同 → 契合度数学上必然相等），但"谁排前面"不能由数据文件先写了谁决定。
    """
    print("\n[Test 11] 推荐结果与数据文件键顺序无关")

    base = FE.load_funnel_data()

    def reordered(seed):
        rnd = random.Random(seed)
        d = FE.FunnelData()
        cats = list(base.categories.items())
        rnd.shuffle(cats)
        d.categories = dict(cats)
        discs = list(base.disciplines.items())
        rnd.shuffle(discs)
        d.disciplines = dict(discs)
        d.majors = list(base.majors)
        d._cat_to_disc = dict(base._cat_to_disc)
        d._cat_to_majors = {k: list(v) for k, v in base._cat_to_majors.items()}
        for v in d._cat_to_majors.values():
            rnd.shuffle(v)
        return d

    random.seed(17)
    users = []
    for _ in range(40):
        u = build_user_from_answers(
            {q["id"]: random.choice(list(q["options"])) for q in MACRO_QUESTIONS},
            {q["id"]: random.choice(list(q["options"])) for q in MICRO_QUESTIONS},
            selected_subjects=["物理", "化学", "生物"],
            estimated_rank_percentile=random.choice([5.0, 20.0, 45.0, 80.0]))
        u.family_economic_level = random.choice(["高", "中", "低"])
        users.append(u)

    original = FE.load_funnel_data
    ref = [[c["category_name"] for c in FE.run_funnel(u)] for u in users]
    diffs = 0
    try:
        for seed in range(4):
            data = reordered(seed)
            FE.load_funnel_data = lambda d=data: d
            for i, u in enumerate(users):
                if [c["category_name"] for c in FE.run_funnel(u)] != ref[i]:
                    diffs += 1
    finally:
        FE.load_funnel_data = original
    check(diffs == 0, "打乱数据文件键顺序后 Top8 名单不变",
          f"{diffs} / {4 * len(users)} 份答卷发生变化（改动前为 18%）")


def test_fit_ties_are_disclosed():
    """v6.2：契合度并列必须被标注出来，且标注只描述事实、不编造区别。

    契合度是专业类产业标签集合的纯函数：标签集合相同 → 数值必然相等。这不是精度
    问题，打分环节修不掉（19 个专业类 / 8 组标签完全重复，占实测并列的 84%）。
    页面上并排挂三个一模一样的数字，用户只会认为算错了，所以至少要说清楚。
    """
    print("\n[Test 12] 契合度并列被如实标注")

    profiles = build_profiles()
    u = profiles["医学/临床"]
    res = run_funnel(u)
    by_name = {c["category_name"]: c for c in res}

    tied = [c for c in res if c.get("fit_tied_with")]
    check(bool(tied), "存在并列时给出了 fit_tied_with 标注",
          f"{len(tied)} 张卡片带标注")

    # 标注必须对称：A 说与 B 并列 ⇔ B 说与 A 并列
    symmetric = True
    for c in tied:
        for other in c["fit_tied_with"]:
            o = by_name.get(other)
            if o is None or c["category_name"] not in (o.get("fit_tied_with") or []):
                symmetric = False
    check(symmetric, "并列标注两两对称", "" if symmetric else "存在单向标注")

    # 标注内容必须与显示精度一致：写了并列，显示值就得真的相同
    consistent = all(
        round(by_name[n]["fit_score"], 3) == round(c["fit_score"], 3)
        for c in tied for n in c["fit_tied_with"] if n in by_name)
    check(consistent, "标注为并列的，契合度显示值确实相同",
          "" if consistent else "标注与实际不符")

    # 五个医学类同挂「医疗健康/临床」，必须全部互相标注（这是最典型的一组）
    MEDICAL = ["医学技术类", "中西医结合类", "临床医学类", "口腔医学类", "护理学类"]
    l1 = layer1_discipline_match(u, FE.load_funnel_data())
    all_cats = {c["category_name"]: c for c in
                layer2_category_match(u, FE.load_funnel_data(), l1, top_n=999)}
    present = [m for m in MEDICAL if m in all_cats]
    same = len({round(all_cats[m]["industry_match"], 3) for m in present}) == 1
    check(same, "标签集合相同的医学类专业类，契合度确实完全相等",
          f"{present} → {[round(all_cats[m]['industry_match'], 3) for m in present]}")


def test_undeclared_exit_discount():
    """v6.2：均值项对「用户没申报过的出路」打折，且不打折成"标签越少越占便宜"。"""
    print("\n[Test 13] 未申报出路打折：窄口径申报不再被标签数量惩罚")

    # 边界：全部申报过 → 与等权均值完全一致（不打折时不改变任何东西）
    full = [0.8, 0.5, 0.3]
    check(abs(_weighted_mean_ratio(full) - sum(full) / len(full)) < 1e-12,
          "所有出路都已申报时，等价于等权均值", f"{_weighted_mean_ratio(full):.4f}")

    # 方向：未申报的出路越多，均值相对等权越高（惩罚越轻）
    check(_weighted_mean_ratio([1.0, 0.0]) > _weighted_mean_ratio([1.0, 0.0, 0.0]),
          "未申报出路越多，惩罚越轻（而非越重）",
          f"{_weighted_mean_ratio([1.0, 0.0]):.4f} > {_weighted_mean_ratio([1.0, 0.0, 0.0]):.4f}")

    # 反方向：不能变成"标签越少分越高"——只挂 1 条且未命中的专业类仍必须是 0
    check(_weighted_mean_ratio([0.0]) == 0.0, "全未申报时仍为 0（不会白拿分）")

    # 单调性：同一条命中，多挂一条「用户完全没提过」的出路，扣分不得超过一条
    # 已申报但低分的出路（这是打折项存在的全部意义）
    undeclared = _weighted_mean_ratio([1.0, 0.0])
    declared_low = _weighted_mean_ratio([1.0, 0.1])
    check(undeclared > declared_low,
          "「没提过」比「提了但不搭」扣分更少",
          f"没提过={undeclared:.4f} > 提了不搭={declared_low:.4f}")


def test_declared_industry_boost():
    """v6.3：M11 的「明确申报方向」单独提权，不再被 M1–M10 的 10 题稀释。

    背景：M11 是全问卷唯一一道「如果必须选一个更具体的行业方向，你更愿意去?」的题，
    表达的是明确申报。但它只有 1 题的证据量，混进 macro_industry_vector 后会被
    M1–M10 的 10 题压掉——改动前申报「物流」的用户，物流管理与工程类进 Top8 的
    命中率只有 22/40。
    """
    print("\n[Test 14] M11 明确申报方向单独提权")

    # --- 解析：M11 的选项必须被读成"申报"，G「以上都不是」读成"没申报" ---
    declared = declared_industry_from_answers({"M11": "B"})
    check(declared.get("物流/供应链", 0) > 0,
          "M11 选 B 解析出物流方向的申报权重", f"{declared}")

    g = declared_industry_from_answers({"M11": "G"})
    check(g == {}, "M11 选 G「以上都不是」解析为空（没有申报）", f"{g}")

    missing = declared_industry_from_answers({})
    check(missing == {}, "没答 M11 时解析为空，不会凭空安一个方向", f"{missing}")

    # --- 效果：提权必须真的改变结果。用「关掉提权」做对照组，而不是跟 M11=G 比 ---
    # 坑：不能拿「M11=B」和「M11=G」两张答卷对比——M11 的权重同时也会进
    # macro_industry_vector，两张答卷的底子本来就不同，比出来的差值里混着基础效应。
    # 唯一干净的对照是**同一张答卷**、只把 DECLARED_BOOST 置 0 再算一遍。
    data = load_funnel_data()
    beta = FE.DECLARED_BOOST          # 跟随常量，改 β 时测试不用跟着改
    micro = micro_for({"logic": 3.0, "hands_on": 3.0, "focus": 2.5,
                       "data_sense": 2.0, "detail": 1.0})
    try:
        for key, rep in [("B", "物流管理与工程类"), ("A", "建筑类")]:
            macro = best_macro_for("人工智能/大模型")
            macro["M11"] = key
            before = after = 0
            for pct in (12.0, 18.0, 25.0):
                u = build_user_from_answers(
                    macro, micro, selected_subjects=["物理", "化学", "生物"],
                    estimated_rank_percentile=pct)
                FE.DECLARED_BOOST = 0.0
                if rep in [c["category_name"] for c in run_funnel(u)]:
                    before += 1
                FE.DECLARED_BOOST = beta
                if rep in [c["category_name"] for c in run_funnel(u)]:
                    after += 1
            check(before == 0 and after == 3,
                  f"主流 IT 画像明确申报「{key}」→ {rep} 由进不了榜变为 3/3 进榜",
                  f"关提权 {before}/3 → 开提权 {after}/3")

        # --- 不变量：只有挂着申报标签的专业类被抬高，其余一个字节都不动 ---
        def _snap(user):
            cats = layer2_category_match(user, data, layer1_discipline_match(user, data),
                                         top_n=999)
            return {c["category_name"]: c["industry_match"] for c in cats}

        macro_b = best_macro_for("人工智能/大模型")
        macro_b["M11"] = "B"
        u = build_user_from_answers(macro_b, micro, selected_subjects=["物理", "化学", "生物"],
                                    estimated_rank_percentile=15.0)
        FE.DECLARED_BOOST = 0.0
        low = _snap(u)
        FE.DECLARED_BOOST = beta
        high = _snap(u)

        tags = set(declared_industry_from_answers({"M11": "B"}))
        touched = {n for n in low if abs(low[n] - high[n]) > 1e-12}
        strays = sorted(n for n in touched
                        if not (tags & set(data.categories.get(n, {}).get("industry_map") or [])))
        check(not strays, "提权只作用于挂着申报标签的专业类",
              f"{len(touched)} 个类被改动，其中不挂申报标签的 {len(strays)} 个：{strays[:5]}")
        dropped = [n for n in touched if high[n] < low[n] - 1e-12]
        check(not dropped, "被提权的专业类契合度只升不降",
              f"{len(touched)} 个被改动的类中有 {len(dropped)} 个反而降了")
        check("物流管理与工程类" in touched,
              "申报「物流」确实抬高了物流管理与工程类",
              f"β=0 时 {low.get('物流管理与工程类', 0):.4f} → "
              f"β={beta} 时 {high.get('物流管理与工程类', 0):.4f}")

        # --- 边界：提权不得把 industry_match 顶过 1.0 ---
        u_med = build_user_from_answers(
            {**best_macro_for("医疗健康/临床"), "M11": "D"},
            micro_for({"memory": 3.0, "focus": 2.5}),
            selected_subjects=["物理", "化学", "生物"], estimated_rank_percentile=15.0)
        over = [c["category_name"] for c in
                layer2_category_match(u_med, data, layer1_discipline_match(u_med, data),
                                      top_n=999)
                if c["industry_match"] > 1.0 + 1e-9]
        check(not over, "提权后契合度上界仍是 1.0", f"越界 {len(over)} 个")
    finally:
        FE.DECLARED_BOOST = beta      # 无论如何都要复原，否则污染后面所有测试


def test_declared_direction_note():
    """v6.3：M11 申报方向落榜时的「特别提示」块。

    它**不改名单、不进排序**，只是把「你申报了 X，X 为什么不在上面」讲清楚。
    因此这里锁的主要是**它说了什么、以及说的话是不是真的**——一个把
    「契合度 0.197」说成「说明你与它确实对口」的提示，比没有提示更糟。
    """
    print("\n[Test 15] M11 申报落榜提示：只解释、不改名单，且不得说假话")

    data = load_funnel_data()
    micro = micro_for({"logic": 3.0, "hands_on": 3.0, "focus": 2.5,
                       "data_sense": 2.0, "detail": 1.0})

    def _user(m11):
        macro = best_macro_for("人工智能/大模型")
        macro["M11"] = m11
        return build_user_from_answers(macro, micro,
                                       selected_subjects=["物理", "化学", "生物"],
                                       estimated_rank_percentile=12.0)

    # --- 不申报就不提示 ---
    u_g = _user("G")
    check(declared_direction_note(u_g, [c["category_name"] for c in run_funnel(u_g)]) == [],
          "M11 选「以上都不是」→ 不产生任何提示")

    # --- F 是「一个都没进」的典型：体育学类契合度全表第 2，却排第 29 ---
    u_f = _user("F")
    shown_f = [c["category_name"] for c in run_funnel(u_f)]
    notes = declared_direction_note(u_f, shown_f)
    check(bool(notes), "M11 申报了方向且确有落榜类 → 产生提示", f"{len(notes)} 条")

    # 提示块不得改变名单（它根本没参与排序，这里锁的是「以后别顺手加进去」）
    check([c["category_name"] for c in run_funnel(u_f)] == shown_f,
          "生成提示前后，Top8 名单完全不变")

    # --- 结构性不变量：条数上限、跨方向去重、in_top 与 shown 一致 ---
    check(len(notes) <= 2, "最多只交代 2 个申报方向", f"{len(notes)} 条")
    check(all(len(n["missed"]) <= 2 for n in notes),
          "每个方向最多列 2 个落榜专业类",
          f"{[len(n['missed']) for n in notes]}")

    all_missed = [it["category_name"] for n in notes for it in n["missed"]]
    check(len(all_missed) == len(set(all_missed)),
          "同一个专业类不会在两个方向下重复出现", f"{all_missed}")
    check(all(name not in shown_f for name in all_missed),
          "列出来的确实都没进名单")
    check(all(all(name in shown_f for name in n["in_top"]) for n in notes),
          "in_top 里列的确实都进了名单")
    check(all(n["missed_total"] >= len(n["missed"]) for n in notes),
          "missed_total 不小于实际列出的条数（不能少报）",
          f"{[(n['missed_total'], len(n['missed'])) for n in notes]}")

    # --- 措辞必须与事实一致 ---
    # ① 「没有任何专业类进入名单」这句只能在 in_top 真的为空时说
    for n in notes:
        claimed_empty = "没有任何专业类" in n["headline"]
        check(claimed_empty == (not n["in_top"]),
              f"「{n['direction']}」的 headline 与 in_top 一致",
              f"in_top={n['in_top']} headline={n['headline'][:40]}...")

    # ② 契合度低的时候不许说「确实对口」——这是最容易印出去的假话
    fit_by_cat = {c["category_name"]: c["industry_match"] for c in
                  layer2_category_match(u_f, data, layer1_discipline_match(u_f, data),
                                        top_n=999)}
    bad_claim = [it["category_name"] for n in notes for it in n["missed"]
                 if fit_by_cat.get(it["category_name"], 0) < 0.6
                 and "确实对口" in it["reason"]]
    check(not bad_claim, "契合度 <0.6 的落榜类不会被说成「确实对口」", f"{bad_claim}")

    # ③ 说「被多样性规则挤下去」的，其综合排序分必须真的在名单长度之内。
    #    这条得换一个**真的会产生多样性归因**的画像来测——F 画像的落榜类全都是
    #    「分数本来就不够」，拿它测这条会以空列表通过，等于没测。
    #    B（物流）画像的 `交通运输类` 就是综合排序分第 5、却被多样性换掉的。
    u_b = _user("B")
    shown_b = [c["category_name"] for c in run_funnel(u_b)]
    notes_b = declared_direction_note(u_b, shown_b)
    by_score = sorted(layer2_category_match(u_b, data, layer1_discipline_match(u_b, data),
                                            top_n=999),
                      key=lambda c: (-c["score"], c["category_name"]))
    rank = {c["category_name"]: i + 1 for i, c in enumerate(by_score)}
    cited = [it["category_name"] for n in notes_b for it in n["missed"]
             if "多样性规则挤下去" in it["reason"]]
    check(bool(cited), "B 画像下确实产生了多样性归因（否则下面两条是空测）", f"{cited}")
    wrong = [name for name in cited if rank.get(name, 9999) > len(shown_b)]
    check(not wrong, "归因到「多样性」的确实分数够得着", f"{wrong}")

    # --- 名单不满时不许归因到多样性（保险丝分支） ---
    partial = declared_direction_note(u_b, shown_b[:5])
    leaked = [it["category_name"] for n in partial for it in n["missed"]
              if "多样性规则挤下去" in it["reason"]]
    check(not leaked, "名单不满 8 个时，不把落榜归因到多样性规则", f"{leaked}")


def main():
    print("=" * 74)
    print("  算法质量回归测试")
    print("=" * 74)
    test_normalization()
    test_industry_match_monotonic()
    test_risk_tier_spans()
    test_user_distinctness()
    test_hard_constraints()
    test_special_track()
    test_no_clamp_ties()
    test_output_ordering()
    test_fit_reality_separation()
    test_declared_industry_boost()
    test_declared_direction_note()
    test_neutral_options()
    test_order_independent_of_data_file()
    test_fit_ties_are_disclosed()
    test_undeclared_exit_discount()

    print("\n" + "=" * 74)
    if _FAILURES:
        print(f"  ❌ {len(_FAILURES)} 项失败：")
        for f in _FAILURES:
            print(f"     - {f}")
        return 1
    print("  🎉 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
