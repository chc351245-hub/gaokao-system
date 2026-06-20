"""
================================================================================
 高考志愿性格与兴趣智能推荐系统 v4.0
================================================================================
 云端架构：
   1. Supabase 云端数据库 — 卡密管理（防 Streamlit Cloud 休眠丢数据）
   2. 前端卡密收费墙 — 激活码解锁 + 一次性核销
   3. 双维深度测评 — 霍兰德 RIASEC (20题) × MBTI精简版 (16题)
   4. 智能匹配引擎 — 交叉矩阵 → Top 10 专业 + 个性化推荐理由
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
from typing import Optional, Tuple

# Supabase SDK
from supabase import create_client, Client

# ========================================================================
# 全局配置
# ========================================================================
st.set_page_config(
    page_title="高考志愿智能推荐系统 v4.0",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Supabase 表名
TABLE_NAME = "keys_table"

# 专业数据文件
MAJORS_FILE = "gaokao_majors.json"


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
# 第1部分：Supabase 云端数据库层
# ========================================================================

@st.cache_resource
def get_supabase_client() -> Client:
    """
    创建并缓存 Supabase 客户端。
    连接信息从 st.secrets 安全读取，绝不硬编码在代码中。

    st.secrets 中需要配置：
      SUPABASE_URL  — 你的 Supabase 项目 URL
      SUPABASE_KEY  — 你的 service_role 或 anon key
    """
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


# -----------------------------------------------------------------------
# 激活码 CRUD（全部操作 Supabase 云数据库）
# -----------------------------------------------------------------------

def generate_license_key() -> str:
    """
    使用 secrets 模块生成密码学安全的 12 位激活码。
    格式：XXXX-XXXX-XXXX（大写字母 + 数字）
    """
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"


def insert_keys(count: int) -> list[str]:
    """
    管理员一键制码：批量生成卡密并 INSERT 写入 Supabase。
    每张卡密初始状态为 'unused'。

    参数:
        count: 生成数量（最大 500）
    返回:
        新生成的激活码列表
    """
    count = min(count, 500)
    supabase = get_supabase_client()
    new_keys: list[str] = []

    # 逐条插入（Supabase Python SDK 的批量 upsert 需要主键，
    # 这里使用逐条 insert 保证可靠性）
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
    """
    校验激活码是否可用（查询 Supabase 云端）。

    参数:
        license_key: 用户输入的激活码（自动去空格、转大写）
    返回:
        (is_valid, message)
        - (True, "激活成功")         — 有效且未使用
        - (False, "激活码不存在")    — 数据库中无此码
        - (False, "激活码已被使用")  — status = 'used'
    """
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

    return True, "激活成功！请开始你的性格测评之旅。"


def mark_key_used(license_key: str) -> None:
    """
    一次性核销：将激活码标记为 used，记录当前时间。
    在结果页首次渲染成功后调用。
    """
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
    """从 Supabase 获取激活码总览统计数据"""
    supabase = get_supabase_client()

    # 总数
    total_resp = (
        supabase.table(TABLE_NAME)
        .select("id", count="exact")
        .execute()
    )
    total = total_resp.count or 0

    # 已使用数
    used_resp = (
        supabase.table(TABLE_NAME)
        .select("id", count="exact")
        .eq("status", "used")
        .execute()
    )
    used = used_resp.count or 0

    unused = total - used
    rate = round(used / total * 100, 1) if total > 0 else 0.0

    return {"total": total, "used": used, "unused": unused, "rate": rate}


def get_all_keys() -> pd.DataFrame:
    """从 Supabase 获取全部激活码列表（供管理员看板）"""
    supabase = get_supabase_client()

    result = (
        supabase.table(TABLE_NAME)
        .select("id, license_key, status, used_at")
        .order("id")
        .execute()
    )

    if result.data:
        return pd.DataFrame(result.data)
    return pd.DataFrame(columns=["id", "license_key", "status", "used_at"])


# ========================================================================
# 第2部分：专业数据加载
# ========================================================================

@st.cache_data
def load_majors() -> pd.DataFrame:
    """加载专业 JSON 数据（883 条），缓存。"""
    with open(MAJORS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    # 将「专业类」为 "-" 或空值的条目补全为 "交叉学科类"
    # （交叉学科门类下的新兴专业暂无明确专业类归属）
    df["专业类"] = df["专业类"].fillna("交叉学科类")
    df["专业类"] = df["专业类"].replace(["", "-"], "交叉学科类")

    # 过滤掉学科门类为空的行（理论上不存在，做防御）
    df = df[df["学科门类"].notna() & (df["学科门类"] != "")]

    return df


# ========================================================================
# 第3部分：双维测评题库
# ========================================================================

# ── 霍兰德 RIASEC 六维度定义 ──
RIASEC = {
    "R": {"name": "现实型 (Realistic)", "icon": "🔧", "color": "#E74C3C",
          "desc": "动手操作，喜爱工具与机械，偏好户外与体力活动"},
    "I": {"name": "研究型 (Investigative)", "icon": "🔬", "color": "#3498DB",
          "desc": "观察思考，喜爱分析探索，偏好科学与实验"},
    "A": {"name": "艺术型 (Artistic)", "icon": "🎨", "color": "#F39C12",
          "desc": "创意表达，喜爱文学艺术，偏好自由与美感"},
    "S": {"name": "社会型 (Social)", "icon": "🤝", "color": "#2ECC71",
          "desc": "助人为乐，喜爱教导服务，偏好人际沟通"},
    "E": {"name": "企业型 (Enterprising)", "icon": "📢", "color": "#E91E63",
          "desc": "领导说服，喜爱管理影响，偏好目标与成就"},
    "C": {"name": "常规型 (Conventional)", "icon": "📋", "color": "#9B59B6",
          "desc": "条理规范，喜爱整理数据，偏好秩序与系统"},
}

# ── RIASEC 题目（20 题）──
RIASEC_QUESTIONS = [
    # ---- 第1步：动手与实践 (5题) ----
    {"id": 1, "step": 1, "question": "学校组织科技节，你会最想",
     "options": {"A": {"text": "亲手组装调试一台无人机或机器人", "dims": ["R"]},
                 "B": {"text": "设计研究课题并撰写科学小论文参赛", "dims": ["I"]},
                 "C": {"text": "拍摄科普短视频吸引同学们关注科学", "dims": ["A"]}}},
    {"id": 2, "step": 1, "question": "看到街边有人修理摩托车，你的第一反应是",
     "options": {"A": {"text": "停下来看，好奇内部结构怎么运作", "dims": ["I", "R"]},
                 "B": {"text": "觉得师傅手艺真好，也想去学一门手艺", "dims": ["R"]},
                 "C": {"text": "想到修车师傅很辛苦，行业需要更多关注", "dims": ["S"]}}},
    {"id": 3, "step": 1, "question": "一套新家具送到家，你会",
     "options": {"A": {"text": "照着说明书一步步组装，享受动手过程", "dims": ["R", "C"]},
                 "B": {"text": "扔掉说明书，凭感觉自由拼装", "dims": ["A", "R"]},
                 "C": {"text": "喊家人一起组装，边聊天边干活", "dims": ["S"]}}},
    {"id": 4, "step": 1, "question": "在实验室做化学实验时，你更看重",
     "options": {"A": {"text": "严格按步骤操作并精确记录每一个数据", "dims": ["C"]},
                 "B": {"text": "探究 '为什么会这样'，尝试改变变量看结果", "dims": ["I"]},
                 "C": {"text": "和搭档配合默契，享受共同完成实验的乐趣", "dims": ["S"]}}},
    {"id": 5, "step": 1, "question": "如果让你暑假打工赚钱，你会选",
     "options": {"A": {"text": "去餐厅或工厂做具体的事情", "dims": ["R"]},
                 "B": {"text": "自己摆摊做小生意", "dims": ["E"]},
                 "C": {"text": "做家教或辅导低年级同学", "dims": ["S", "I"]}}},
    # ---- 第2步：思维与表达 (5题) ----
    {"id": 6, "step": 2, "question": "面对一道极难的数学压轴题，你的态度是",
     "options": {"A": {"text": "特别兴奋，一定要钻研到底直到解出来", "dims": ["I"]},
                 "B": {"text": "按部就班套用公式，把步骤写得清清楚楚", "dims": ["C"]},
                 "C": {"text": "更喜欢和同学讨论交流解法，集思广益", "dims": ["S"]}}},
    {"id": 7, "step": 2, "question": "辩论赛中你觉得哪个角色最适合你",
     "options": {"A": {"text": "一辩：用严密逻辑论证己方观点框架", "dims": ["I", "C"]},
                 "B": {"text": "三辩：犀利质询对方漏洞，气势压倒", "dims": ["E"]},
                 "C": {"text": "四辩：结合情感与价值观做有感染力的总结", "dims": ["A", "S"]}}},
    {"id": 8, "step": 2, "question": "拿到一本新书，你最可能选",
     "options": {"A": {"text": "科普、侦探推理或科幻小说", "dims": ["I"]},
                 "B": {"text": "历史传记、文学名著或励志故事", "dims": ["A", "S"]},
                 "C": {"text": "商业案例、名人创业传记", "dims": ["E"]}}},
    {"id": 9, "step": 2, "question": "小组做项目时，你自然承担的角色是",
     "options": {"A": {"text": "主动分配任务、推动进度、做最终检查", "dims": ["E"]},
                 "B": {"text": "负责查资料、分析数据和归纳关键发现", "dims": ["I"]},
                 "C": {"text": "协调组内关系，照顾每个人的感受", "dims": ["S"]}}},
    {"id": 10, "step": 2, "question": "老师布置自由命题议论文，你会选",
     "options": {"A": {"text": "《人工智能将如何重塑未来社会》", "dims": ["I"]},
                 "B": {"text": "《论同理心在当代教育中的缺失》", "dims": ["S", "A"]},
                 "C": {"text": "《创业精神与青年人的时代使命》", "dims": ["E"]}}},
    # ---- 第3步：社会与职业倾向 (5题) ----
    {"id": 11, "step": 3, "question": "学校组织社会实践，你倾向于",
     "options": {"A": {"text": "设计问卷，做数据分析写调查报告", "dims": ["I", "C"]},
                 "B": {"text": "去养老院或福利院做志愿者", "dims": ["S"]},
                 "C": {"text": "组织义卖活动，带领大家募集善款", "dims": ["E", "S"]}}},
    {"id": 12, "step": 3, "question": "你整理学习资料的习惯是",
     "options": {"A": {"text": "按科目和时间精确归档，建立检索系统", "dims": ["C"]},
                 "B": {"text": "随手放但大概知道在哪，相信直觉", "dims": ["A"]},
                 "C": {"text": "用彩色标签和活页夹做美观又好用的分类", "dims": ["C", "A"]}}},
    {"id": 13, "step": 3, "question": "如果让你设计一款校园 App，你会做",
     "options": {"A": {"text": "高效的时间管理与待办事项工具", "dims": ["C", "E"]},
                 "B": {"text": "学生互助答疑平台", "dims": ["S"]},
                 "C": {"text": "创意图片编辑与分享社区", "dims": ["A"]}}},
    {"id": 14, "step": 3, "question": "社团换届竞选，你上台主要讲",
     "options": {"A": {"text": "详细的年度工作方案和可量化目标", "dims": ["C", "E"]},
                 "B": {"text": "我对社团的感情，如何让每个人找到归属感", "dims": ["S", "A"]},
                 "C": {"text": "我的领导风格为什么能带来更多资源和奖项", "dims": ["E"]}}},
    {"id": 15, "step": 3, "question": "导师交给你从没做过的任务，你会",
     "options": {"A": {"text": "先找文献教程研究清楚原理再动手", "dims": ["I"]},
                 "B": {"text": "马上动手尝试，在实践中边做边学", "dims": ["R", "E"]},
                 "C": {"text": "先列详细的步骤计划和时间表再执行", "dims": ["C"]}}},
    # ---- 第4步：价值观与长远规划 (5题) ----
    {"id": 16, "step": 4, "question": "业余时间你最可能去",
     "options": {"A": {"text": "科技馆、博物馆或航模俱乐部", "dims": ["I", "R"]},
                 "B": {"text": "音乐会、画展或书店泡一个下午", "dims": ["A"]},
                 "C": {"text": "社区志愿服务或公益活动", "dims": ["S"]}}},
    {"id": 17, "step": 4, "question": "影响你选专业最重要的因素是",
     "options": {"A": {"text": "专业是否契合我的兴趣和天赋优势", "dims": ["I", "A"]},
                 "B": {"text": "专业未来的就业前景和薪资水平", "dims": ["E", "C"]},
                 "C": {"text": "专业是否能让我帮助别人或推动社会进步", "dims": ["S"]}}},
    {"id": 18, "step": 4, "question": "如果要参加课外竞赛，你会选",
     "options": {"A": {"text": "理科学科竞赛或信息学奥赛", "dims": ["I"]},
                 "B": {"text": "创业大赛、商业模拟赛或模拟联合国", "dims": ["E", "S"]},
                 "C": {"text": "作文大赛、英语演讲比赛或海报设计赛", "dims": ["A"]}}},
    {"id": 19, "step": 4, "question": "你心目中「成功的人生」更接近",
     "options": {"A": {"text": "在某个领域成为顶尖专家，获得行业尊重", "dims": ["I", "C"]},
                 "B": {"text": "开创自己的事业，实现财务自由", "dims": ["E"]},
                 "C": {"text": "拥有和谐的家庭与人际关系，过充实平静的生活", "dims": ["S", "A"]}}},
    {"id": 20, "step": 4, "question": "你理想中的大学专业学习氛围是",
     "options": {"A": {"text": "实验室和图书馆是主战场，沉下心来钻研", "dims": ["I"]},
                 "B": {"text": "团队合作、项目实践和跨学科交流频繁", "dims": ["S", "E"]},
                 "C": {"text": "自由开放的艺术氛围，鼓励个性表达", "dims": ["A"]}}},
]

# ── MBTI 精简版题目（16 题）──
MBTI_QUESTIONS = [
    # ---- E/I 社交能量（第5步：5题）----
    {"id": 21, "step": 5, "axis": "EI",
     "question": "周末两天完全没安排，你会",
     "options": {"A": {"text": "有点无聊，想找朋友出去", "dim": "E", "score": 5},
                 "B": {"text": "太好了，可以安静做自己的事", "dim": "I", "score": 5}}},
    {"id": 22, "step": 5, "axis": "EI",
     "question": "参加完大型聚会后，你通常",
     "options": {"A": {"text": "感觉充满能量，还想继续聊", "dim": "E", "score": 5},
                 "B": {"text": "感觉精疲力尽，需要独处充电", "dim": "I", "score": 5}}},
    {"id": 23, "step": 5, "axis": "EI",
     "question": "遇到困难时你第一时间",
     "options": {"A": {"text": "打电话找朋友聊，在交流中理清思路", "dim": "E", "score": 5},
                 "B": {"text": "关起门自己先想清楚，解决不了再求助", "dim": "I", "score": 5}}},
    {"id": 24, "step": 5, "axis": "EI",
     "question": "在图书馆自习时你更喜欢",
     "options": {"A": {"text": "和几个同学坐一块区域互相督促", "dim": "E", "score": 5},
                 "B": {"text": "找安静角落戴上耳机独自学习", "dim": "I", "score": 5}}},
    {"id": 25, "step": 5, "axis": "EI",
     "question": "班级讨论时你通常是",
     "options": {"A": {"text": "抢着发言的活跃分子之一", "dim": "E", "score": 5},
                 "B": {"text": "先听完所有人观点，最后才表达自己", "dim": "I", "score": 5}}},
    # ---- T/F 决策方式（第6步：6题）----
    {"id": 26, "step": 6, "axis": "TF",
     "question": "朋友向你倾诉烦恼，你的第一反应",
     "options": {"A": {"text": "帮他分析问题根源，给出解决方案", "dim": "T", "score": 5},
                 "B": {"text": "先共情安慰，让他感觉被理解", "dim": "F", "score": 5}}},
    {"id": 27, "step": 6, "axis": "TF",
     "question": "小组决策出现分歧，你会",
     "options": {"A": {"text": "摆出数据和事实，让客观证据说话", "dim": "T", "score": 5},
                 "B": {"text": "先照顾大家感受，尽量找折中方案", "dim": "F", "score": 5}}},
    {"id": 28, "step": 6, "axis": "TF",
     "question": "评价一部电影好坏，你更看重",
     "options": {"A": {"text": "剧情逻辑是否严密、设定自洽", "dim": "T", "score": 5},
                 "B": {"text": "能否打动人心，情感表达是否真实", "dim": "F", "score": 5}}},
    {"id": 29, "step": 6, "axis": "TF",
     "question": "如果要劝退一个表现不佳的组员，你",
     "options": {"A": {"text": "列出失误清单，客观说明原因", "dim": "T", "score": 5},
                 "B": {"text": "非常为难，担心伤害他的自尊", "dim": "F", "score": 5}}},
    {"id": 30, "step": 6, "axis": "TF",
     "question": "有人说「公平比情面重要」，你",
     "options": {"A": {"text": "同意——规则面前人人平等", "dim": "T", "score": 5},
                 "B": {"text": "不太同意——法外有人情，应具体分析", "dim": "F", "score": 5}}},
    {"id": 31, "step": 6, "axis": "TF",
     "question": "贫困母亲为救孩子偷窃，作为法官你",
     "options": {"A": {"text": "依法判处——动机无论，违法必承担后果", "dim": "T", "score": 5},
                 "B": {"text": "从轻发落——情有可原，惩戒非唯一目的", "dim": "F", "score": 5}}},
    # ---- J/P 生活风格（第7步：5题）----
    {"id": 32, "step": 7, "axis": "JP",
     "question": "出门旅行，你的行李准备方式是",
     "options": {"A": {"text": "提前两天列清单分类装好", "dim": "J", "score": 5},
                 "B": {"text": "出发前半小时匆忙塞箱子", "dim": "P", "score": 5}}},
    {"id": 33, "step": 7, "axis": "JP",
     "question": "截止日期还有一周的作业，你",
     "options": {"A": {"text": "第一天做好计划，每天完成一部分", "dim": "J", "score": 5},
                 "B": {"text": "截止前夜通宵赶完，压力就是动力", "dim": "P", "score": 5}}},
    {"id": 34, "step": 7, "axis": "JP",
     "question": "你的书桌/房间通常是",
     "options": {"A": {"text": "整洁有序，各就各位", "dim": "J", "score": 5},
                 "B": {"text": "有点乱但自己知道东西在哪", "dim": "P", "score": 5}}},
    {"id": 35, "step": 7, "axis": "JP",
     "question": "你对「计划赶不上变化」的态度",
     "options": {"A": {"text": "不太认同——做好规划才能减少变数", "dim": "J", "score": 5},
                 "B": {"text": "完全认同——随性而为才是生活乐趣", "dim": "P", "score": 5}}},
    {"id": 36, "step": 7, "axis": "JP",
     "question": "你对「按部就班」这个词的感觉",
     "options": {"A": {"text": "安心可靠——有节奏的生活让我踏实", "dim": "J", "score": 5},
                 "B": {"text": "束缚沉闷——生活应该充满惊喜和变化", "dim": "P", "score": 5}}},
]

ALL_QUESTIONS = RIASEC_QUESTIONS + MBTI_QUESTIONS
TOTAL_QUESTIONS = len(ALL_QUESTIONS)

STEPS = {
    1: ("第1步 · 动手与实践", "动手操作与空间感知倾向"),
    2: ("第2步 · 思维与表达", "逻辑思考与沟通风格"),
    3: ("第3步 · 社会与职业倾向", "社会参与与职业偏好"),
    4: ("第4步 · 价值观与长远规划", "人生目标与内在驱动力"),
    5: ("第5步 · 社交能量来源", "你从哪里获取心理能量"),
    6: ("第6步 · 决策与判断方式", "你如何做出重要决定"),
    7: ("第7步 · 生活与工作风格", "你的日常节奏与组织偏好"),
}


# ========================================================================
# 第4部分：评分引擎
# ========================================================================

def calc_riasec_scores(answers: dict) -> dict[str, float]:
    """霍兰德 RIASEC 六维度归一化得分 (0-100)"""
    raw = {d: 0.0 for d in "RIASEC"}
    for q in RIASEC_QUESTIONS:
        chosen = answers.get(q["id"])
        if chosen and chosen in q["options"]:
            for dim in q["options"][chosen]["dims"]:
                raw[dim] += 1.0

    max_possible = _riasec_max()
    scores = {}
    for d in "RIASEC":
        scores[d] = min(100.0, round(raw[d] / max_possible[d] * 100, 1) if max_possible[d] > 0 else 0.0)
    return scores


def _riasec_max() -> dict[str, float]:
    mx = {d: 0.0 for d in "RIASEC"}
    for q in RIASEC_QUESTIONS:
        for opt in q["options"].values():
            for d in opt["dims"]:
                mx[d] += 1.0
    for d in mx:
        mx[d] = max(mx[d], 1.0)
    return mx


def calc_mbti_scores(answers: dict) -> dict[str, float]:
    """MBTI 六子维度归一化得分 (0-100)"""
    raw = {"E": 0.0, "I": 0.0, "T": 0.0, "F": 0.0, "J": 0.0, "P": 0.0}
    for q in MBTI_QUESTIONS:
        chosen = answers.get(q["id"])
        if chosen and chosen in q["options"]:
            dim = q["options"][chosen]["dim"]
            raw[dim] += q["options"][chosen]["score"]

    max_possible = _mbti_max()
    scores = {}
    for d in raw:
        scores[d] = min(100.0, round(raw[d] / max_possible[d] * 100, 1) if max_possible[d] > 0 else 0.0)
    return scores


def _mbti_max() -> dict[str, float]:
    mx = {"E": 0.0, "I": 0.0, "T": 0.0, "F": 0.0, "J": 0.0, "P": 0.0}
    for q in MBTI_QUESTIONS:
        for opt in q["options"].values():
            mx[opt["dim"]] += opt["score"]
    for d in mx:
        mx[d] = max(mx[d], 1.0)
    return mx


# ========================================================================
# 第5部分：双维交叉匹配引擎
# ========================================================================

MENLEI_MATCH = {
    "理学":   ("I", "T", "基础研究，需要深度思考与逻辑推理"),
    "工学":   ("R", "T", "工程应用，动手能力与理性分析并重"),
    "医学":   ("I", "T", "生命科学，严谨实证与人文关怀兼备"),
    "农学":   ("R", "T", "大地与生命，实践探索与科学精神"),
    "哲学":   ("I", "T", "思辨之域，抽象推理与逻辑严谨"),
    "经济学": ("E", "T", "资源配置，数据分析与战略决策"),
    "法学":   ("E", "T", "规则与正义，逻辑思维与价值判断"),
    "教育学": ("S", "F", "知识传承，共情沟通与人格塑造"),
    "文学":   ("A", "F", "语言艺术，感性表达与文化沉淀"),
    "历史学": ("I", "T", "时间的学问，沉心考证与批判思维"),
    "管理学": ("E", "T", "组织效率，领导协调与系统规划"),
    "艺术学": ("A", "F", "美的创造，个性表达与感性直觉"),
}

ZHUANYELEI_MATCH = {}
for _zl in ["计算机类", "电子信息类", "自动化类", "电气类", "机械类", "土木类",
            "数学类", "物理学类", "化学类", "生物科学类", "统计学类",
            "航空航天类", "兵器类", "核工程类", "材料类", "能源动力类",
            "化工与制药类", "交通运输类", "农业工程类", "林业工程类",
            "环境科学与工程类", "生物医学工程类", "安全科学与工程类",
            "生物工程类", "公安技术类"]:
    ZHUANYELEI_MATCH[_zl] = (["I", "R"], "T")

for _zl in ["临床医学类", "基础医学类", "口腔医学类", "药学类",
            "中药学类", "法医学类", "医学技术类"]:
    ZHUANYELEI_MATCH[_zl] = (["I", "S"], "T")

for _zl in ["中医学类", "中西医结合类"]:
    ZHUANYELEI_MATCH[_zl] = (["I", "S"], "F")

for _zl in ["护理学类"]:
    ZHUANYELEI_MATCH[_zl] = (["S", "R"], "F")

for _zl in ["中国语言文学类", "外国语言文学类"]:
    ZHUANYELEI_MATCH[_zl] = (["A", "S"], "F")

for _zl in ["新闻传播学类"]:
    ZHUANYELEI_MATCH[_zl] = (["A", "E"], "F")

for _zl in ["法学类", "政治学类", "公安学类"]:
    ZHUANYELEI_MATCH[_zl] = (["E", "S"], "T")

for _zl in ["社会学类", "民族学类", "马克思主义理论类"]:
    ZHUANYELEI_MATCH[_zl] = (["S", "I"], "F")

for _zl in ["经济学类", "金融学类", "财政学类", "经济与贸易类"]:
    ZHUANYELEI_MATCH[_zl] = (["E", "C"], "T")

for _zl in ["管理科学与工程类", "工商管理类", "农业经济管理类",
            "图书情报与档案管理类", "物流管理与工程类", "工业工程类",
            "电子商务类", "旅游管理类"]:
    ZHUANYELEI_MATCH[_zl] = (["E", "C"], "T")

for _zl in ["公共管理类"]:
    ZHUANYELEI_MATCH[_zl] = (["S", "E"], "F")

for _zl in ["教育学类", "体育学类"]:
    ZHUANYELEI_MATCH[_zl] = (["S"], "F")

for _zl in ["音乐与舞蹈学类", "戏剧与影视学类", "美术学类",
            "设计学类", "艺术学理论类"]:
    ZHUANYELEI_MATCH[_zl] = (["A"], "F")

for _zl in ["历史学类", "哲学类"]:
    ZHUANYELEI_MATCH[_zl] = (["I", "A"], "T")

for _zl in ["建筑类"]:
    ZHUANYELEI_MATCH[_zl] = (["A", "R"], "F")

for _zl in ["纺织类", "轻工类"]:
    ZHUANYELEI_MATCH[_zl] = (["R", "A"], "T")

for _zl in ["植物生产类", "动物生产类", "林学类", "水产类", "草学类",
            "自然保护与环境生态类", "动物医学类"]:
    ZHUANYELEI_MATCH[_zl] = (["R", "I"], "T")

for _zl in ["食品科学与工程类"]:
    ZHUANYELEI_MATCH[_zl] = (["I", "R"], "T")

for _zl in ["心理学类"]:
    ZHUANYELEI_MATCH[_zl] = (["I", "S"], "F")


def match_majors_combined(
    df: pd.DataFrame,
    riasec_scores: dict,
    mbti_scores: dict,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    双维综合匹配 — 交叉矩阵评分。

    评分逻辑（每行可累计）：
    ┌──────────────────────────────────┬──────┐
    │ 条件                             │ 加分 │
    ├──────────────────────────────────┼──────┤
    │ 学科门类 primary RIASEC 命中     │ +5   │
    │ 学科门类 MBTI T/F 匹配           │ +3   │
    │ 专业类精细 RIASEC 命中           │ +3   │
    │ 专业类精细 MBTI T/F 匹配         │ +2   │
    │ 最高 RIASEC 维度专属加成         │ +3   │
    └──────────────────────────────────┴──────┘
    """
    riasec_top = sorted(riasec_scores.items(), key=lambda x: x[1], reverse=True)
    top_riasec_set = {d for d, _ in riasec_top[:3]}
    user_tf = "T" if mbti_scores["T"] >= mbti_scores["F"] else "F"

    df = df.copy()

    def score_row(row) -> int:
        total = 0
        ml = row["学科门类"]
        zyl = row.get("专业类", "")

        ml_info = MENLEI_MATCH.get(ml)
        if ml_info:
            ml_riasec, ml_tf, _ = ml_info
            if ml_riasec in top_riasec_set:
                total += 5
            if ml_tf == user_tf:
                total += 3

        zl_info = ZHUANYELEI_MATCH.get(zyl)
        if zl_info:
            zl_dims, zl_tf = zl_info
            if top_riasec_set & set(zl_dims):
                total += 3
            if zl_tf == user_tf:
                total += 2
            if riasec_top[0][0] in zl_dims:
                total += 3

        return total

    df["匹配分数"] = df.apply(score_row, axis=1)
    matched = df[df["匹配分数"] > 0].sort_values("匹配分数", ascending=False)

    if len(matched) < top_n:
        remain = top_n - len(matched)
        others = df[~df.index.isin(matched.index)].sample(
            min(remain, len(df) - len(matched)), random_state=42
        )
        matched = pd.concat([matched, others])

    return matched.head(top_n)


def generate_reason(
    row: pd.Series,
    riasec_scores: dict,
    mbti_scores: dict,
) -> str:
    """为推荐专业生成个性化解释"""
    riasec_top = sorted(riasec_scores.items(), key=lambda x: x[1], reverse=True)
    top_d_name = RIASEC[riasec_top[0][0]]["name"].split(" ")[0]
    user_tf = "逻辑分析型" if mbti_scores["T"] >= mbti_scores["F"] else "情感共鸣型"
    user_ei = "与人交流协作" if mbti_scores["E"] >= mbti_scores["I"] else "独立深入思考"

    zyl = row.get("专业类", "")
    major = row.get("专业名称", "该专业")

    custom = {
        "计算机类": f"你兼具'{top_d_name}'特质和{user_tf}思维，这正是{major}所看重的核心素养。",
        "临床医学类": f"医学需理性与共情的平衡。你的双维测试结果恰好在两者间有良好表现，{major}值得认真考虑。",
        "中国语言文学类": f"你的感性细腻与表达欲能在{major}中找到最自然的出口。",
        "设计学类": f"你的创造力与审美敏感度，恰是{major}最看重的天赋。",
    }
    if zyl in custom:
        return custom[zyl]

    return (
        f"你的霍兰德'{top_d_name}'特质与 MBTI {user_tf}倾向共同指向{major}（{zyl}）。"
        f"该专业需要{user_ei}的能力，与你的性格画像高度一致。"
    )


# ========================================================================
# 第6部分：可视化组件
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
# 第7部分：UI 页面组件
# ========================================================================

def render_header() -> None:
    c1, c2 = st.columns([0.82, 0.18])
    with c1:
        st.title("🎓 高考志愿智能推荐系统 v4.0")
        st.caption(
            "**霍兰德 RIASEC (20题) × MBTI 精简版 (16题)**  "
            "双维深度测评 · 883 个本科专业 · 智能匹配引擎"
        )
    with c2:
        st.image("https://img.icons8.com/emoji/96/graduation-cap-emoji.png", width=72)


def render_sidebar(df: pd.DataFrame) -> None:
    """侧边栏：系统说明 + 数据概况 + 管理员通道"""
    with st.sidebar:
        st.markdown("## 📖 系统说明")

        with st.expander("🔬 霍兰德 RIASEC", expanded=False):
            for d, info in RIASEC.items():
                st.caption(f"{info['icon']} **{info['name']}** — {info['desc']}")

        with st.expander("🧠 MBTI 精简版", expanded=False):
            st.caption("**E/I** 社交能量 · **T/F** 决策方式 · **J/P** 生活风格")

        st.markdown("---")

        st.markdown("### 📊 数据概况")
        c3, c4 = st.columns(2)
        c3.metric("专业总数", len(df))
        c4.metric("学科门类", df["学科门类"].nunique())
        c5, c6 = st.columns(2)
        c5.metric("专业类", df["专业类"].nunique())
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
            基于权威心理学理论<br>
            36 道深度情景测评<br>
            883 个本科专业精准匹配
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


def render_progress(answers: dict) -> None:
    done = len(answers)
    pct = done / TOTAL_QUESTIONS
    st.progress(pct, text=f"📝 答题进度：{done}/{TOTAL_QUESTIONS} 题（{int(pct*100)}%）")


def render_questionnaire() -> None:
    """分步答题引擎（7 步骤，每步一个 st.form）"""
    st.markdown("---")
    st.markdown('<p class="section-title">📋 双维深度测评</p>', unsafe_allow_html=True)

    render_progress(st.session_state.answers)

    for step_num in sorted(STEPS.keys()):
        step_qs = [q for q in ALL_QUESTIONS
                   if q["step"] == step_num
                   and q["id"] not in st.session_state.answers]
        if not step_qs:
            continue

        step_title, step_desc = STEPS[step_num]
        st.markdown(f"### {step_title}")
        st.caption(step_desc)

        with st.form(key=f"step_form_{step_num}"):
            for q in step_qs:
                prefix = "🔬" if q["id"] <= 20 else "🧠"
                st.markdown(f"##### {prefix} **{q['id']}. {q['question']}**")

                opt_keys = list(q["options"].keys())
                selected = st.radio(
                    f"Q{q['id']}",
                    options=opt_keys,
                    format_func=lambda k, q=q: f"{k}. {q['options'][k]['text']}",
                    key=f"radio_{q['id']}",
                    label_visibility="collapsed",
                    index=None,
                )
                if selected:
                    st.session_state.answers[q["id"]] = selected

            st.form_submit_button(
                "💾 保存并进入下一步",
                type="primary",
                use_container_width=True,
                on_click=lambda: st.rerun(),
            )
        return

    # 全部答完 → 触发结果
    if len(st.session_state.answers) >= TOTAL_QUESTIONS:
        compute_and_show_results()


def compute_and_show_results() -> None:
    """计算得分 + 匹配专业 + 一次性核销"""
    with st.spinner("🔍 正在计算你的性格画像..."):
        st.session_state.riasec_scores = calc_riasec_scores(st.session_state.answers)
        st.session_state.mbti_scores = calc_mbti_scores(st.session_state.answers)

    with st.spinner("🎯 正在匹配最适合你的专业..."):
        df = load_majors()
        st.session_state.matched = match_majors_combined(
            df,
            st.session_state.riasec_scores,
            st.session_state.mbti_scores,
        )

    # 一次性核销
    if not st.session_state.get("key_consumed", False):
        mark_key_used(st.session_state.license_key)
        st.session_state.key_consumed = True

    render_results_view(
        st.session_state.riasec_scores,
        st.session_state.mbti_scores,
        st.session_state.matched,
    )


def render_results_view(
    riasec_scores: dict,
    mbti_scores: dict,
    matched: pd.DataFrame,
) -> None:
    """结果展示页"""
    st.markdown("---")
    st.markdown('<p class="section-title">📊 你的性格画像报告</p>', unsafe_allow_html=True)

    riasec_top = sorted(riasec_scores.items(), key=lambda x: x[1], reverse=True)
    user_tf = "理性 (T)" if mbti_scores["T"] >= mbti_scores["F"] else "感性 (F)"
    user_ei = "外向 (E)" if mbti_scores["E"] >= mbti_scores["I"] else "内向 (I)"
    user_jp = "计划 (J)" if mbti_scores["J"] >= mbti_scores["P"] else "随性 (P)"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 🔬 霍兰德 RIASEC")
        riasec_color = {d: RIASEC[d]["color"] for d in RIASEC}
        st.plotly_chart(render_bar_chart(riasec_scores, riasec_color), use_container_width=True)
        top_d = riasec_top[0][0]
        st.info(f"**核心倾向：{RIASEC[top_d]['icon']} {RIASEC[top_d]['name']}**\n\n{RIASEC[top_d]['desc']}")

    with c2:
        st.markdown("##### 🧠 MBTI 精简评估")
        mbti_color = {"E": "#2ECC71", "I": "#3498DB", "T": "#E74C3C", "F": "#F39C12", "J": "#9B59B6", "P": "#1ABC9C"}
        st.plotly_chart(render_bar_chart(mbti_scores, mbti_color), use_container_width=True)
        st.info(f"**决策：{user_tf}**  ·  **社交：{user_ei}**  ·  **节奏：{user_jp}**")

    st.markdown("---")
    st.markdown('<p class="section-title">🎯 Top 10 专业推荐</p>', unsafe_allow_html=True)
    st.caption(
        f"匹配逻辑：最高维度 **{RIASEC[riasec_top[0][0]]['name'].split(' ')[0]}** "
        f"+ MBTI **{user_tf}** → 从 883 个专业中精选 Top 10"
    )

    for idx, (_, row) in enumerate(matched.iterrows()):
        rank = idx + 1
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

        if rank <= 3:
            st.markdown(
                f"""
                <div class="rcmd-card">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <h3>{medal} 第 {rank} 名</h3>
                  <span style="opacity:0.85;">{row['学科门类']} · {row['专业类']}</span>
                </div>
                <h2 style="margin:10px 0;">{row['专业名称']}</h2>
                <code>专业代码 {row.get('专业代码', '')}</code>
                <p style="margin-top:14px;line-height:1.7;font-size:14px;">
                  {generate_reason(row, riasec_scores, mbti_scores)}
                </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            with st.container():
                st.markdown(
                    f"#### {medal} {row['专业名称']}  "
                    f"<small><code>({row.get('专业代码', '')})</code></small>",
                    unsafe_allow_html=True,
                )
                st.caption(f"  {row['学科门类']} · {row['专业类']}  |  匹配分数：{row.get('匹配分数', '-')}")
                with st.expander(" 查看匹配理由"):
                    st.success(generate_reason(row, riasec_scores, mbti_scores))

    st.markdown("---")
    st.info(
        "💡 **温馨提示**：性格测试结果仅供选专业参考。"
        "实际填报请结合你的 **高考分数**、**院校偏好**、**城市选择** 和 **个人志向** 综合决策。"
    )

    _, cbtn, _ = st.columns([0.35, 0.3, 0.35])
    with cbtn:
        if st.button("🔄 重新测评", use_container_width=True, key="restart_result"):
            st.session_state.answers = {}
            st.session_state.riasec_scores = None
            st.session_state.mbti_scores = None
            st.session_state.matched = None
            st.session_state.key_consumed = False
            st.rerun()


# ========================================================================
# 第8部分：管理员控制面板
# ========================================================================

def render_admin_panel(df_majors: pd.DataFrame) -> None:
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
    c1, c2, c3 = st.columns(3)
    c1.metric("专业总数", len(df_majors))
    c2.metric("学科门类", df_majors["学科门类"].nunique())
    c3.metric("专业类", df_majors["专业类"].nunique())


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
        "riasec_scores": None,
        "mbti_scores": None,
        "matched": None,
        "key_consumed": False,
        "is_admin": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    df = load_majors()

    render_header()

    if not st.session_state.license_activated:
        render_sidebar(df)
        render_welcome_and_activation()
    else:
        render_sidebar(df)
        st.caption(f"🔑 当前激活码：`{st.session_state.license_key}` | 状态：已激活")

        if st.session_state.matched is not None:
            render_results_view(
                st.session_state.riasec_scores,
                st.session_state.mbti_scores,
                st.session_state.matched,
            )
            _, cbtn, _ = st.columns([0.35, 0.3, 0.35])
            with cbtn:
                if st.button("🔄 重新测评", use_container_width=True, key="restart_result"):
                    st.session_state.answers = {}
                    st.session_state.riasec_scores = None
                    st.session_state.mbti_scores = None
                    st.session_state.matched = None
                    st.session_state.key_consumed = False
                    st.rerun()
        else:
            render_questionnaire()

    if st.session_state.get("is_admin"):
        render_admin_panel(df)


if __name__ == "__main__":
    main()
