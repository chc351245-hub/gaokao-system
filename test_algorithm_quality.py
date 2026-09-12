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
)
from user_profile import BEHAVIOR_DIMENSIONS
from funnel_engine import (
    load_funnel_data, run_funnel, layer1_discipline_match,
    layer2_category_match, get_top_industries, _risk_tier,
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
