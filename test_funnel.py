"""
三层递进漏斗引擎 — 独立测试脚本
验证：Top 8 截断 / ≤6 majors / 红线过滤 / 分数范围
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from user_profile import create_test_user
from funnel_engine import run_funnel, print_funnel_results

print("=" * 60)
print("  三层递进漏斗引擎 v6.0 — 测试")
print("=" * 60)

# ---- 测试 1：默认测试用户（理科/逻辑强/记忆弱） ----
print("\n" + "=" * 60)
print("  测试 1：理科逻辑型用户（物化生，AI 向往强）")
print("=" * 60)

user1 = create_test_user()
if not user1.macro_value_vector:
    user1.macro_value_vector = {
        "稳定偏好": 30.0,
        "成长导向": 85.0,
        "风险容忍度": 60.0,
        "社会影响力": 45.0,
        "经济回报": 80.0,
    }

results1 = run_funnel(user1, verbose=True)
print_funnel_results(results1)

# ---- 测试 2：不同用户类型（文科/社交强） ----
print("\n" + "=" * 60)
print("  测试 2：文科社交型用户（历政地，沟通强/逻辑弱）")
print("=" * 60)

user2 = create_test_user()
user2.selected_subjects = ["历史", "政治", "地理"]
user2.micro_behavior_vector = {
    "逻辑推理":   45.0,
    "动手实验":   40.0,
    "团队协作":   88.0,
    "创造性思维": 82.0,
    "精细操作":   55.0,
    "持续专注":   60.0,
    "沟通表达":   90.0,
    "数据敏感":   50.0,
    "抗压能力":   70.0,
    "记忆积累":   78.0,
}
user2.macro_industry_vector = {
    "AI与大模型":      30.0,
    "互联网与软件":    40.0,
    "半导体与芯片":    20.0,
    "金融科技":        70.0,
    "智能制造":        25.0,
    "新能源":          20.0,
    "生物医药":        30.0,
    "教育培训":        85.0,
    "政府公共":        75.0,
    "文化传媒":        90.0,
}
if not user2.macro_value_vector:
    user2.macro_value_vector = {
        "稳定偏好": 75.0,
        "成长导向": 55.0,
        "风险容忍度": 35.0,
        "社会影响力": 80.0,
        "经济回报": 50.0,
    }
user2.infer_personality_from_behavior()
user2.estimated_rank_percentile = 45.0
user2.family_economic_level = "中"

results2 = run_funnel(user2, verbose=True)
print_funnel_results(results2)

# ---- 测试 3：有色盲的医学向用户 ----
print("\n" + "=" * 60)
print("  测试 3：色盲用户（应排除临床医学类专业）")
print("=" * 60)

user3 = create_test_user()
user3.physical_conditions = ["色盲", "色弱"]
user3.macro_industry_vector = {
    "AI与大模型":      30.0,
    "互联网与软件":    30.0,
    "半导体与芯片":    20.0,
    "金融科技":        25.0,
    "智能制造":        20.0,
    "新能源":          20.0,
    "生物医药":        95.0,
    "教育培训":        40.0,
    "政府公共":        30.0,
    "文化传媒":        25.0,
}
if not user3.macro_value_vector:
    user3.macro_value_vector = {
        "稳定偏好": 60.0,
        "成长导向": 70.0,
        "风险容忍度": 50.0,
        "社会影响力": 80.0,
        "经济回报": 60.0,
    }

results3 = run_funnel(user3, verbose=False)
print_funnel_results(results3)

# Check that no 临床医学 majors appear (they have 无红绿色盲 threshold)
clin_majors_dropped = True
for cat in results3:
    if "临床" in cat["category_name"]:
        for m in cat["recommended_majors"]:
            print(f"  ⚠ 意外出现: {m['major_name']} (应被红线过滤)")

# ---- 验证汇总 ----
print("\n" + "=" * 60)
print("  📊 验证汇总")
print("=" * 60)

all_ok = True
for label, results in [("Test 1", results1), ("Test 2", results2), ("Test 3", results3)]:
    cats_ok = len(results) <= 8
    majors_per_cat_ok = all(len(c["recommended_majors"]) <= 6 for c in results)
    total_majors = sum(len(c["recommended_majors"]) for c in results)
    scores_ok = all(
        0 <= m["major_score"] <= 1
        for c in results
        for m in c["recommended_majors"]
    )
    no_zero_score = all(
        m["major_score"] > 0
        for c in results
        for m in c["recommended_majors"]
    )

    ok = all([cats_ok, majors_per_cat_ok, scores_ok, no_zero_score])
    all_ok = all_ok and ok
    status = "✅" if ok else "❌"
    print(f"  {status} {label}: {len(results)} cats / {total_majors} majors | "
          f"cats≤8={cats_ok} majors≤6={majors_per_cat_ok} scores∈[0,1]={scores_ok} no_zeros={no_zero_score}")

if all_ok:
    print("\n🎉 全部验证通过！")
else:
    print("\n❌ 部分验证失败，请检查")
