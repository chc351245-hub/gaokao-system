"""
================================================================================
 高考志愿智能推荐系统 v5.0
================================================================================
 云端架构：
   1. Supabase 云端数据库 — 卡密管理（防 Streamlit Cloud 休眠丢数据）
   2. 前端卡密收费墙 — 激活码解锁 + 一次性核销
   3. 隐蔽式深度测评 — 宏观意愿题(10道) + 微观行为场景题(30道)
   4. 6步算法管线 — 测谎 → 红线过滤 → 特殊赛道 → 余弦匹配 → 现实折损 → 多样性打散
   5. 管理员可视化后台 — 卡密看板 + 批量制码 + 状态统计
================================================================================
 运行方式：
    pip install -r requirements.txt
    streamlit run app.py
================================================================================
"""

import streamlit as st
import pandas as pd
import json
import string
import secrets
from datetime import datetime
from typing import Optional

# Supabase SDK
from supabase import create_client, Client

# v5.0 引擎
from user_profile import (
    UserProfile,
    BEHAVIOR_DIMENSIONS,
    INDUSTRY_CLUSTERS,
    RIASEC_INFO,
)
from questionnaire import (
    MACRO_QUESTIONS,
    MICRO_QUESTIONS,
    score_all,
    build_user_from_answers,
    CONSISTENCY_RULES,
)
from recommendation_engine import (
    recommend_for_user,
    load_enhanced_majors,
    print_results,
    clamp,
)

# ========================================================================
# 全局配置
# ========================================================================
st.set_page_config(
    page_title="高考志愿智能推荐系统 v5.0",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Supabase 表名
TABLE_NAME = "keys_table"

# 专业数据文件
MAJORS_FILE = "enhanced_majors.json"

# 题目总数
TOTAL_MACRO = len(MACRO_QUESTIONS)    # 10
TOTAL_MICRO = len(MICRO_QUESTIONS)    # 30
TOTAL_QUESTIONS = TOTAL_MACRO + TOTAL_MICRO  # 40


# ========================================================================
# 自定义 CSS 主题
# ========================================================================
def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: "Inter", "Microsoft YaHei", "PingFang SC", sans-serif;
        }

        div[data-testid="stProgress"] > div > div {
            background: linear-gradient(90deg, #667EEA, #764BA2);
        }

        .stButton > button {
            border-radius: 10px;
            font-weight: 600;
            transition: all 0.2s ease;
            border: none;
        }
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(102,126,234,0.40);
        }

        .rcmd-card {
            background: linear-gradient(135deg, #667EEA 0%, #764BA2 100%);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 14px;
            color: #FFFFFF;
            box-shadow: 0 6px 24px rgba(102,126,234,0.35);
        }
        .rcmd-card h3, .rcmd-card h2 { color: #FFF !important; margin: 0; }

        .section-title {
            font-size: 22px;
            font-weight: 700;
            color: #2C3E50;
            margin-top: 24px;
            border-left: 4px solid #667EEA;
            padding-left: 16px;
        }

        .metric-box {
            background: #F8F9FA;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            border: 1px solid #E9ECEF;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ========================================================================
# 第1部分：Supabase 云端数据库层（保持不变）
# ========================================================================

@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


def generate_license_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"


def insert_keys(count: int) -> list[str]:
    count = min(count, 500)
    supabase = get_supabase_client()
    new_keys: list[str] = []
    for _ in range(count):
        key = generate_license_key()
        (
            supabase.table(TABLE_NAME)
            .insert({"license_key": key, "status": "unused"})
            .execute()
        )
        new_keys.append(key)
    return new_keys


def validate_key(license_key: str) -> tuple[bool, str]:
    key = license_key.strip().upper()
    supabase = get_supabase_client()
    result = (
        supabase.table(TABLE_NAME)
        .select("status")
        .eq("license_key", key)
        .execute()
    )
    rows = result.data
    if not rows:
        return False, "激活码不存在，请检查后重试。"
    if rows[0]["status"] == "used":
        return False, "该激活码已被使用，每个激活码仅限一人使用。"
    return True, "激活成功！请开始你的深度测评之旅。"


def mark_key_used(license_key: str) -> None:
    key = license_key.strip().upper()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    supabase = get_supabase_client()
    (
        supabase.table(TABLE_NAME)
        .update({"status": "used", "used_at": now})
        .eq("license_key", key)
        .execute()
    )


def get_keys_stats() -> dict:
    supabase = get_supabase_client()
    total_resp = (
        supabase.table(TABLE_NAME)
        .select("license_key", count="exact")
        .execute()
    )
    total = total_resp.count or 0
    used_resp = (
        supabase.table(TABLE_NAME)
        .select("license_key", count="exact")
        .eq("status", "used")
        .execute()
    )
    used = used_resp.count or 0
    unused = total - used
    rate = round(used / total * 100, 1) if total > 0 else 0.0
    return {"total": total, "used": used, "unused": unused, "rate": rate}


def get_all_keys() -> pd.DataFrame:
    supabase = get_supabase_client()
    result = (
        supabase.table(TABLE_NAME)
        .select("license_key, status, used_at")
        .order("license_key")
        .execute()
    )
    if result.data:
        return pd.DataFrame(result.data)
    return pd.DataFrame(columns=["license_key", "status", "used_at"])


# ========================================================================
# 第2部分：专业数据加载
# ========================================================================

@st.cache_data
def load_majors() -> list[dict]:
    """加载增强专业数据库（含五维标签）"""
    return load_enhanced_majors(MAJORS_FILE)


# ========================================================================
# 第3部分：可视化组件
# ========================================================================

def render_bar_chart(scores: dict, color_map: dict = None, height: int = 320):
    """柱状图（Plotly）"""
    import plotly.graph_objects as go

    items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    colors = [color_map.get(k, "#667EEA") for k, _ in items] if color_map else ["#667EEA"] * len(labels)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels, y=values, marker_color=colors,
            text=[f"{v:.0f}" for v in values], textposition="outside",
        )
    )
    fig.update_layout(
        xaxis=dict(showgrid=False),
        yaxis=dict(range=[0, 108], showgrid=True, gridcolor="#F0F0F0"),
        margin=dict(l=30, r=30, t=10, b=20),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ========================================================================
# 第4部分：用户画像采集
# ========================================================================

def render_user_profile_form() -> None:
    """Step 0：采集用户硬约束和家庭资源"""
    st.markdown("---")
    st.markdown('<p class="section-title">📋 基本信息（影响推荐精度）</p>', unsafe_allow_html=True)
    st.caption("以下信息仅用于算法匹配，不会上传或存储。")

    with st.form(key="user_profile_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("##### 🎯 学业信息")
            subjects = st.multiselect(
                "选考科目",
                options=["物理", "化学", "生物", "历史", "地理", "政治"],
                default=st.session_state.get("user_subjects", []),
                help="请选择你高考的选考科目",
            )
            score = st.number_input(
                "预估高考分数（裸分）",
                min_value=0, max_value=750, value=st.session_state.get("user_score", 500), step=1,
                help="不确定可填大概范围",
            )
            rank_pct = st.slider(
                "预估全省位次（前百分之几）",
                min_value=0.5, max_value=100.0,
                value=st.session_state.get("user_rank_pct", 50.0), step=0.5,
                help="数值越小越靠前。如全省前5%填5；前30%填30",
            )
            physical = st.multiselect(
                "体检限制（如有）",
                options=["色盲", "色弱", "裸眼视力<4.8", "身高不达标"],
                default=st.session_state.get("user_physical", []),
                help="无不填",
            )

        with col2:
            st.markdown("##### 🏠 家庭背景")
            econ = st.selectbox(
                "家庭经济水平",
                options=["低", "中", "高"],
                index=["低", "中", "高"].index(st.session_state.get("user_econ", "中")),
                help="低=低保/脱贫/务农；中=普通工薪；高=中产及以上",
            )
            city = st.selectbox(
                "家庭所在城市层级",
                options=["一线", "新一线", "二线", "三线及以下"],
                index=["一线", "新一线", "二线", "三线及以下"].index(
                    st.session_state.get("user_city", "新一线")
                ),
            )
            overseas = st.checkbox(
                "家庭有海外留学资源（亲属/经济能力）",
                value=st.session_state.get("user_overseas", False),
            )
            industry_conn = st.selectbox(
                "家庭行业人脉",
                options=["无", "医疗", "金融", "教育", "政府", "互联网", "制造"],
                index=["无", "医疗", "金融", "教育", "政府", "互联网", "制造"].index(
                    st.session_state.get("user_industry_conn", "无")
                ),
            )

        st.markdown("---")
        st.markdown("##### 🎯 特殊赛道意图（可选）")
        col_a, col_b = st.columns(2)
        with col_a:
            track = st.selectbox(
                "你是否对以下方向有明确意向？",
                options=["暂无", "医学", "师范", "军警"],
                index=["暂无", "医学", "师范", "军警"].index(
                    st.session_state.get("user_track", "暂无")
                ),
            )
        with col_b:
            if track != "暂无":
                stance = st.radio(
                    "你的态度是？",
                    options=["强烈意向", "可以接受", "极度抗拒"],
                    index=["强烈意向", "可以接受", "极度抗拒"].index(
                        st.session_state.get("user_stance", "可以接受")
                    ),
                )
            else:
                stance = None

        submitted = st.form_submit_button("💾 保存并进入测评", type="primary", use_container_width=True)

        if submitted:
            st.session_state.user_subjects = subjects
            st.session_state.user_score = score
            st.session_state.user_rank_pct = rank_pct
            st.session_state.user_physical = physical
            st.session_state.user_econ = econ
            st.session_state.user_city = city
            st.session_state.user_overseas = overseas
            st.session_state.user_industry_conn = industry_conn
            st.session_state.user_track = track
            st.session_state.user_stance = stance
            st.session_state.profile_done = True
            st.rerun()


# ========================================================================
# 第5部分：隐蔽式问卷渲染
# ========================================================================

def render_progress(answers: dict) -> None:
    done = len(answers)
    pct = done / TOTAL_QUESTIONS
    st.progress(pct, text=f"📝 答题进度：{done}/{TOTAL_QUESTIONS} 题（{int(pct*100)}%）")


def _render_question_block(
    questions: list[dict],
    block_title: str,
    block_desc: str,
    form_key: str,
) -> None:
    """渲染一个题目块（st.form）"""
    st.markdown(f"### {block_title}")
    st.caption(block_desc)

    with st.form(key=form_key):
        for q in questions:
            qid = q["id"]
            st.markdown(f"##### **{qid}. {q['question']}**")

            opt_keys = list(q["options"].keys())
            selected = st.radio(
                f"Q_{qid}",
                options=opt_keys,
                format_func=lambda k, q=q: f"{k}. {q['options'][k]['text']}",
                key=f"radio_{qid}",
                label_visibility="collapsed",
                index=None,
            )
            if selected:
                st.session_state.answers[qid] = selected

        st.form_submit_button(
            "💾 保存并继续",
            type="primary",
            use_container_width=True,
            on_click=lambda: st.rerun(),
        )


def render_questionnaire() -> None:
    """
    隐蔽式问卷：先10道宏观题，再30道微观题（分3块，每块10题）。
    每块一个 st.form，提交后进入下一块。
    """
    st.markdown("---")
    st.markdown('<p class="section-title">🧠 深度测评（40题）</p>', unsafe_allow_html=True)
    st.caption("没有标准答案，选最接近你真实做法的选项。你的诚实比「正确」更重要。")

    render_progress(st.session_state.answers)

    # ---- 第1块：宏观意愿题 M1-M10 ----
    unanswered_macro = [q for q in MACRO_QUESTIONS if q["id"] not in st.session_state.answers]
    if unanswered_macro:
        _render_question_block(
            unanswered_macro,
            block_title="🔭 未来向往（第1部分 / 共4部分）",
            block_desc="以下问题探测你对不同产业方向的真实向往程度。凭直觉选，不要过度思考。",
            form_key="form_macro",
        )
        return

    # ---- 第2块：微观行为 U1-U10 ----
    micro_1 = [q for q in MICRO_QUESTIONS[:10] if q["id"] not in st.session_state.answers]
    if micro_1:
        _render_question_block(
            micro_1,
            block_title="🔬 日常行为（第2部分 / 共4部分）",
            block_desc="实验课、小组作业、课余时间——你真实的行为模式是什么？",
            form_key="form_micro_1",
        )
        return

    # ---- 第3块：微观行为 U11-U20 ----
    micro_2 = [q for q in MICRO_QUESTIONS[10:20] if q["id"] not in st.session_state.answers]
    if micro_2:
        _render_question_block(
            micro_2,
            block_title="💡 思维与习惯（第3部分 / 共4部分）",
            block_desc="学习方式、信息摄入、压力应对——这些细节暴露你的底层天赋。",
            form_key="form_micro_2",
        )
        return

    # ---- 第4块：微观行为 U21-U30 ----
    micro_3 = [q for q in MICRO_QUESTIONS[20:30] if q["id"] not in st.session_state.answers]
    if micro_3:
        _render_question_block(
            micro_3,
            block_title="🧩 社交与日常（第4部分 / 共4部分）",
            block_desc="社交风格、整理习惯、自我驱动——最后10题，坚持就是胜利。",
            form_key="form_micro_3",
        )
        return

    # 全部答完 → 计算结果
    if len(st.session_state.answers) >= TOTAL_QUESTIONS:
        compute_and_show_results()


# ========================================================================
# 第6部分：结果计算与展示
# ========================================================================

def compute_and_show_results() -> None:
    """构建用户画像 → 运行6步管线 → 展示结果 + 核销"""

    # 构建用户画像
    macro_answers = {q["id"]: st.session_state.answers[q["id"]] for q in MACRO_QUESTIONS}
    micro_answers = {q["id"]: st.session_state.answers[q["id"]] for q in MICRO_QUESTIONS}

    with st.spinner("🔍 正在计算你的行为画像..."):
        user = build_user_from_answers(
            macro_answers=macro_answers,
            micro_answers=micro_answers,
            selected_subjects=st.session_state.get("user_subjects", []),
            estimated_score=st.session_state.get("user_score", 500),
            estimated_rank_percentile=st.session_state.get("user_rank_pct", 50.0),
            physical_conditions=st.session_state.get("user_physical", []),
            family_economic_level=st.session_state.get("user_econ", "中"),
            family_city_tier=st.session_state.get("user_city", "新一线"),
            family_has_overseas_resource=st.session_state.get("user_overseas", False),
            family_has_industry_connection=st.session_state.get("user_industry_conn", "无"),
            special_track_intent=(
                st.session_state.get("user_track")
                if st.session_state.get("user_track") != "暂无"
                else None
            ),
            special_track_stance=st.session_state.get("user_stance"),
        )

    with st.spinner("🎯 正在运行 6 步智能匹配管线..."):
        report = recommend_for_user(user, majors_file=MAJORS_FILE, top_n=10, verbose=False)

    st.session_state.report = report
    st.session_state.user = user

    # 一次性核销
    if not st.session_state.get("key_consumed", False):
        mark_key_used(st.session_state.license_key)
        st.session_state.key_consumed = True

    render_results_view(report, user)


def render_results_view(report: dict, user: UserProfile) -> None:
    """结果展示页"""
    results = report["results"]
    pipeline_log = report["pipeline_log"]

    st.markdown("---")
    st.markdown('<p class="section-title">📊 你的行为画像报告</p>', unsafe_allow_html=True)

    # ---- 行为维度柱状图 ----
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### 🧬 10维微观行为画像")
        behavior_color = {
            "逻辑推理": "#E74C3C", "动手实验": "#E67E22", "团队协作": "#2ECC71",
            "创造性思维": "#F39C12", "精细操作": "#9B59B6", "持续专注": "#3498DB",
            "沟通表达": "#1ABC9C", "数据敏感": "#E91E63", "抗压能力": "#FF5722",
            "记忆积累": "#607D8B",
        }
        st.plotly_chart(
            render_bar_chart(user.micro_behavior_vector, behavior_color),
            use_container_width=True,
        )
        top3 = user.get_top_behaviors(3)
        weak3 = user.get_weakest_behaviors(3)
        st.info(
            f"**优势维度**：{'、'.join(f'{k}({v:.0f})' for k, v in top3)}  \n"
            f"**短板维度**：{'、'.join(f'{k}({v:.0f})' for k, v in weak3)}"
        )

    with col2:
        st.markdown("##### 🏭 10大产业向往（已过测谎）")
        industry_color = {
            "AI与大模型": "#667EEA", "互联网与软件": "#764BA2", "半导体与芯片": "#E74C3C",
            "金融科技": "#F39C12", "智能制造": "#E67E22", "新能源": "#2ECC71",
            "生物医药": "#3498DB", "教育培训": "#1ABC9C", "政府公共": "#95A5A6",
            "文化传媒": "#E91E63",
        }
        st.plotly_chart(
            render_bar_chart(user.macro_industry_vector, industry_color),
            use_container_width=True,
        )

        # 推断人格
        dominant = user.get_dominant_personality()
        dom_info = RIASEC_INFO.get(dominant, {})
        st.info(
            f"**推断人格倾向**：{dom_info.get('icon', '')} {dom_info.get('name', dominant)}  \n"
            f"{dom_info.get('desc', '')}  \n"
            f"**测谎分数**：{user.lie_score:.2f} "
            f"({'✅ 高度一致' if user.lie_score < 0.15 else '⚠️ 部分矛盾' if user.lie_score < 0.35 else '🔴 显著矛盾'})"
        )

    # ---- 管线摘要 ----
    st.markdown("---")
    st.markdown('<p class="section-title">🔬 6步管线摘要</p>', unsafe_allow_html=True)

    col_a, col_b, col_c = st.columns(3)
    step0 = pipeline_log.get("step0", {})
    step1 = pipeline_log.get("step1", {})
    step4 = pipeline_log.get("step4", {})
    step5 = pipeline_log.get("step5", {})

    col_a.metric("Step 0 · 测谎检测", f"{step0.get('contradiction_count', 0)} 项矛盾")
    col_b.metric("Step 1 · 红线过滤", f"通过 {step1.get('survivors', 0)}/{step1.get('total_in', 0)} 专业")
    col_c.metric("Step 5 · 强穿透", f"{step5.get('bypass_count', 0)} 专业触发")

    # 测谎详情
    if step0.get("details"):
        with st.expander("🔍 查看测谎详情"):
            for cd in step0["details"]:
                st.caption(
                    f"**{cd['cluster']}**：{cd['label']}  "
                    f"（宏观 {cd['macro_original']:.0f} → {cd['macro_adjusted']:.0f}，"
                    f"微观均值 {cd['micro_avg']:.0f} < 阈值 {cd['threshold']}）"
                )

    # ---- Top 10 推荐 ----
    st.markdown("---")
    st.markdown('<p class="section-title">🎯 Top 10 专业推荐</p>', unsafe_allow_html=True)
    st.caption(
        "匹配逻辑：30%人格 + 30%产业向往 + 40%微观行为 → 余弦相似度匹配 → "
        "现实折损 → 多样性打散。**匹配分≠录取概率**，录取概率请结合分数另行评估。"
    )

    for idx, r in enumerate(results):
        rank = idx + 1
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
        major = r.major
        name = major.get("专业名称", "未知专业")
        code = major.get("专业代码", "")
        category = major.get("学科门类", "")
        zyl = major.get("专业类", "")

        label_icon = {
            "高优直达": "🚀",
            "排雷预警": "⚠️",
            "跨界Plan B": "🔄",
            "标准推荐": "✅",
        }.get(r.label, "✅")

        if rank <= 3:
            st.markdown(
                f"""
                <div class="rcmd-card">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <h3>{medal} 第 {rank} 名 {label_icon} {r.label}</h3>
                  <span style="opacity:0.85;">{category} · {zyl}</span>
                </div>
                <h2 style="margin:10px 0;">{name}</h2>
                <code>专业代码 {code} | 匹配分 {r.final_score:.3f} | 基础分 {r.base_score:.3f}</code>
                <p style="margin-top:14px;line-height:1.7;font-size:14px;">{r.reason}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            with st.container():
                st.markdown(
                    f"#### {medal} {name} {label_icon}  "
                    f"<small><code>({code})</code> | 匹配分 {r.final_score:.3f}</small>",
                    unsafe_allow_html=True,
                )
                st.caption(f"  {category} · {zyl} | {r.label}")
                with st.expander("📋 查看详细分析"):
                    st.write(f"**人格相似度**: {r.personality_sim:.3f}")
                    st.write(f"**产业相似度**: {r.industry_sim:.3f}")
                    st.write(f"**微观行为相似度**: {r.micro_sim:.3f}")
                    st.write(f"**现实折损系数**: {r.reality_penalty:.2f} "
                             f"(分数×{r.score_penalty:.2f} 资源×{r.resource_penalty:.2f})")
                    if r.bypassed:
                        st.success("🚀 已触发底层信号强穿透")
                    if r.boosted:
                        st.info("📈 已触发特殊赛道提权")
                    if r.warnings:
                        for w in r.warnings:
                            st.warning(w)
                    st.info(r.reason)

    st.markdown("---")
    st.info(
        "💡 **温馨提示**：匹配分衡量「你适不适合这个专业」，不等同于「你能不能考上」。"
        "实际填报请结合你的 **高考分数**、**院校偏好** 和 **城市选择** 综合决策。"
    )

    _, cbtn, _ = st.columns([0.35, 0.3, 0.35])
    with cbtn:
        if st.button("🔄 重新测评", use_container_width=True, key="restart_result"):
            st.session_state.answers = {}
            st.session_state.report = None
            st.session_state.user = None
            st.session_state.key_consumed = False
            st.session_state.profile_done = False
            st.rerun()


# ========================================================================
# 第7部分：UI 页面组件
# ========================================================================

def render_header() -> None:
    c1, c2 = st.columns([0.82, 0.18])
    with c1:
        st.title("🎓 高考志愿智能推荐系统 v5.0")
        st.caption(
            "**隐蔽式深度测评（40题）× 6步算法管线**  "
            "测谎 → 红线过滤 → 余弦匹配 → 现实折损 → 多样性打散 → Top 10 推荐"
        )
    with c2:
        st.image("https://img.icons8.com/emoji/96/graduation-cap-emoji.png", width=72)


def render_sidebar() -> None:
    """侧边栏：系统说明 + 管理员通道"""
    majors = load_majors()

    with st.sidebar:
        st.markdown("## 📖 系统说明")

        with st.expander("🧠 隐蔽式测评设计", expanded=False):
            st.caption(
                "**10道宏观题** — 探测你对10大产业集群的真实向往。\n\n"
                "**30道微观题** — 通过日常场景（实验课、小组作业、B站沉迷内容等）"
                "映射10个核心行为维度：逻辑推理、动手实验、团队协作、创造性思维、"
                "精细操作、持续专注、沟通表达、数据敏感、抗压能力、记忆积累。\n\n"
                "**测谎机制** — 宏观向往与微观行为矛盾时自动衰减，防止「叶公好龙」。"
            )

        with st.expander("🔬 6步算法管线", expanded=False):
            st.caption(
                "**Step 0** 情绪测谎 — 宏观vs微观矛盾检测\n"
                "**Step 1** 生死红线 — 选科不符/体检限制 → 物理移除\n"
                "**Step 2** 特殊赛道 — 医学/师范/军警的阻断与提权\n"
                "**Step 3** 基础匹配 — 余弦相似度(人格30%+产业30%+微观40%)\n"
                "**Step 4** 现实折损 — 分数位次×家庭资源折损\n"
                "**Step 5** 强穿透 — 微观极高分(≥95)拉满基础分\n"
                "**Step 6** 多样性打散 — Top3同门类→注入跨界Plan B"
            )

        st.markdown("---")

        st.markdown("### 📊 数据概况")
        c3, c4 = st.columns(2)
        c3.metric("专业总数", len(majors))
        cats = set(m.get("学科门类", "") for m in majors)
        c4.metric("学科门类", len(cats))
        c5, c6 = st.columns(2)
        zyls = set(m.get("专业类", "") for m in majors)
        c5.metric("专业类", len(zyls))
        c6.metric("测评题数", TOTAL_QUESTIONS)

        st.markdown("---")

        # ── 管理员通道 ──
        with st.expander("🔐 管理员通道", expanded=False):
            admin_pwd = st.text_input(
                "管理员主密码",
                type="password",
                key="admin_sidebar_password",
                placeholder="输入主密码即可解锁后台",
            )
            if admin_pwd == st.secrets["admin_password"]:
                st.session_state.is_admin = True
                st.success("✅ 管理员验证通过，后台已解锁")
            elif admin_pwd:
                st.session_state.is_admin = False
                st.error("❌ 密码错误")


def render_welcome_and_activation() -> None:
    """卡密收费墙 — 欢迎页 + 激活窗口"""
    st.markdown("---")
    col_img, col_form = st.columns([0.45, 0.55])

    with col_img:
        st.markdown(
            """
            <div style="
                background: linear-gradient(135deg, #667EEA, #764BA2);
                border-radius: 20px;
                padding: 48px 32px;
                text-align: center;
                color: white;
            ">
            <h1 style="color:white; font-size: 48px; margin:0;">🎓</h1>
            <h2 style="color:white; margin:12px 0;">发现最适合你的大学专业</h2>
            <p style="opacity:0.85; line-height:1.7;">
            40道隐蔽式深度测评<br>
            6步智能算法管线<br>
            33个核心专业精准匹配
            </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_form:
        st.markdown("### 🔑 输入激活码以解锁系统")
        st.caption("每个激活码仅供一人使用，激活后即刻解锁全部功能。")

        with st.form(key="activation_form"):
            user_key = st.text_input(
                "激活码",
                placeholder="例如：ABCD-EFGH-IJKL",
                key="activation_input",
            )
            submitted = st.form_submit_button(
                "🚀 激活并开始测评",
                type="primary",
                use_container_width=True,
            )

            if submitted:
                if not user_key.strip():
                    st.error("请输入激活码。")
                else:
                    valid, msg = validate_key(user_key)
                    if valid:
                        st.session_state.license_activated = True
                        st.session_state.license_key = user_key.strip().upper()
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)


# ========================================================================
# 第8部分：管理员控制面板（保持不变）
# ========================================================================

def render_admin_panel() -> None:
    if not st.session_state.get("is_admin"):
        return

    st.markdown("---")
    st.markdown('<p class="section-title">🛡️ 管理员控制面板</p>', unsafe_allow_html=True)

    # 统计卡片
    stats = get_keys_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📦 总生成数", stats["total"])
    c2.metric("✅ 已使用", stats["used"])
    c3.metric("📋 未使用", stats["unused"])
    c4.metric("📈 转化率", f"{stats['rate']}%")

    st.markdown("---")

    # A：卡密看板
    st.markdown("### 📋 激活码管理看板")
    keys_df = get_all_keys()
    if not keys_df.empty:
        st.dataframe(keys_df, use_container_width=True, hide_index=True)
        csv_data = keys_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 导出 CSV",
            data=csv_data,
            file_name=f"license_keys_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
    else:
        st.info("数据库中暂无激活码，请先批量生成。")

    st.markdown("---")

    # B：一键制码
    st.markdown("### 🔧 批量生成激活码")
    col_gen, col_info = st.columns([0.4, 0.6])
    with col_gen:
        gen_count = st.number_input("生成数量", min_value=1, max_value=500, value=10, step=1)
        if st.button("🎲 批量生成", type="primary", use_container_width=True):
            new_keys = insert_keys(gen_count)
            st.success(f"✅ 成功生成 {len(new_keys)} 个激活码！")
            with st.expander("查看新生成的激活码"):
                for k in new_keys:
                    st.code(k)
            st.rerun()

    with col_info:
        st.caption(
            "激活码格式为 `XXXX-XXXX-XXXX`（12 位大写字母+数字，密码学安全随机）。"
            "每个激活码仅限一人使用，使用后即刻核销。"
        )

    # 专业数据概览
    st.markdown("---")
    st.markdown("### 📊 专业数据概览")
    majors = load_majors()
    c1, c2, c3 = st.columns(3)
    c1.metric("专业总数", len(majors))
    cats = set(m.get("学科门类", "") for m in majors)
    c2.metric("学科门类", len(cats))
    zyls = set(m.get("专业类", "") for m in majors)
    c3.metric("专业类", len(zyls))


# ========================================================================
# 主应用入口
# ========================================================================

def main() -> None:
    inject_css()

    # Session State 初始化
    defaults = {
        "license_activated": False,
        "license_key": "",
        "answers": {},
        "profile_done": False,
        "report": None,
        "user": None,
        "key_consumed": False,
        "is_admin": False,
        # 用户画像
        "user_subjects": [],
        "user_score": 500,
        "user_rank_pct": 50.0,
        "user_physical": [],
        "user_econ": "中",
        "user_city": "新一线",
        "user_overseas": False,
        "user_industry_conn": "无",
        "user_track": "暂无",
        "user_stance": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    render_header()

    if not st.session_state.license_activated:
        render_sidebar()
        render_welcome_and_activation()
    else:
        render_sidebar()
        st.caption(f"🔑 当前激活码：`{st.session_state.license_key}` | 状态：已激活")

        if st.session_state.report is not None:
            render_results_view(st.session_state.report, st.session_state.user)
            _, cbtn, _ = st.columns([0.35, 0.3, 0.35])
            with cbtn:
                if st.button("🔄 重新测评", use_container_width=True, key="restart_result"):
                    st.session_state.answers = {}
                    st.session_state.report = None
                    st.session_state.user = None
                    st.session_state.key_consumed = False
                    st.session_state.profile_done = False
                    st.rerun()
        elif not st.session_state.profile_done:
            render_user_profile_form()
        else:
            render_questionnaire()

    if st.session_state.get("is_admin"):
        render_admin_panel()


if __name__ == "__main__":
    main()
