"""
================================================================================
 隐蔽式问卷题库 (Covert Questionnaire)
================================================================================
 设计原则：
   1. 所有题目面向18岁高中生日常场景，不使用任何专业术语
   2. 宏观意愿题(10道) 探测产业向往与价值观
   3. 微观行为题(30道) 通过具体场景探测10个行为维度
   4. 测谎规则对：宏观-微观矛盾检测

 行为维度（10个）：
   逻辑推理 | 动手实验 | 团队协作 | 创造性思维 | 精细操作
   持续专注 | 沟通表达 | 数据敏感 | 抗压能力 | 记忆积累

 产业集群（10个）：
   AI与大模型 | 互联网与软件 | 半导体与芯片 | 金融科技 | 智能制造
   新能源 | 生物医药 | 教育培训 | 政府公共 | 文化传媒

 注意：所有中文引用使用「」角括号，避免与Python字符串引号冲突
================================================================================
"""

from typing import Any
from user_profile import (
    BEHAVIOR_DIMENSIONS,
    INDUSTRY_CLUSTERS,
    UserProfile,
)

# ============================================================================
# 第1部分：宏观意愿题（10题）
# ============================================================================

MACRO_QUESTIONS = [
    # ---- M1：身份认同 ----
    {
        "id": "M1",
        "question": "十年后的同学聚会，你最希望别人因为什么记住你？",
        "options": {
            "A": {
                "text": "创办了一家有影响力的公司",
                "industry_weights": {"AI与大模型": 0.3, "互联网与软件": 0.3, "金融科技": 0.2, "智能制造": 0.2},
                "value_weights": {"经济回报": 0.7, "社会影响力": 0.3},
            },
            "B": {
                "text": "在某个技术领域做到了顶尖水平",
                "industry_weights": {"AI与大模型": 0.4, "半导体与芯片": 0.3, "新能源": 0.2, "智能制造": 0.1},
                "value_weights": {"成长导向": 0.6, "社会影响力": 0.4},
            },
            "C": {
                "text": "帮助了很多人，改变了他们的生活",
                "industry_weights": {"生物医药": 0.4, "教育培训": 0.4, "政府公共": 0.2},
                "value_weights": {"社会影响力": 0.8, "稳定偏好": 0.2},
            },
            "D": {
                "text": "创作了打动人心的作品",
                "industry_weights": {"文化传媒": 0.8, "互联网与软件": 0.2},
                "value_weights": {"社会影响力": 0.7, "成长导向": 0.3},
            },
        },
    },

    # ---- M2：自由时间偏好 ----
    {
        "id": "M2",
        "question": "暑假你有完全自由的30天，你最可能怎么过？",
        "options": {
            "A": {
                "text": "学一门编程语言或搭一个硬件项目",
                "industry_weights": {"AI与大模型": 0.3, "互联网与软件": 0.3, "半导体与芯片": 0.2, "智能制造": 0.2},
                "value_weights": {"成长导向": 0.8, "经济回报": 0.2},
            },
            "B": {
                "text": "读一堆书并写详细的读书笔记",
                "industry_weights": {"教育培训": 0.4, "文化传媒": 0.3, "政府公共": 0.3},
                "value_weights": {"成长导向": 0.6, "稳定偏好": 0.4},
            },
            "C": {
                "text": "组织朋友做一个社区公益或商业小项目",
                "industry_weights": {"互联网与软件": 0.2, "金融科技": 0.3, "教育培训": 0.3, "文化传媒": 0.2},
                "value_weights": {"社会影响力": 0.5, "经济回报": 0.3, "成长导向": 0.2},
            },
            "D": {
                "text": "旅行、拍摄、写游记或做Vlog",
                "industry_weights": {"文化传媒": 0.8, "互联网与软件": 0.2},
                "value_weights": {"成长导向": 0.5, "社会影响力": 0.3, "稳定偏好": 0.2},
            },
        },
    },

    # ---- M3：问题解决偏好 ----
    {
        "id": "M3",
        "question": "你更愿意解决哪类问题？",
        "options": {
            "A": {
                "text": "技术难题——比如让程序跑得更快、让机器更精准",
                "industry_weights": {"AI与大模型": 0.3, "互联网与软件": 0.2, "半导体与芯片": 0.2, "智能制造": 0.2, "新能源": 0.1},
                "value_weights": {"成长导向": 0.7, "经济回报": 0.3},
            },
            "B": {
                "text": "人的问题——比如帮朋友化解矛盾、让团队更团结",
                "industry_weights": {"教育培训": 0.4, "政府公共": 0.4, "文化传媒": 0.2},
                "value_weights": {"社会影响力": 0.8, "稳定偏好": 0.2},
            },
            "C": {
                "text": "策略问题——比如怎么让一个活动更成功、生意更赚钱",
                "industry_weights": {"金融科技": 0.4, "互联网与软件": 0.3, "智能制造": 0.2, "新能源": 0.1},
                "value_weights": {"经济回报": 0.6, "社会影响力": 0.4},
            },
            "D": {
                "text": "知识问题——比如搞清楚一个自然现象的深层原因",
                "industry_weights": {"生物医药": 0.5, "AI与大模型": 0.2, "新能源": 0.2, "半导体与芯片": 0.1},
                "value_weights": {"成长导向": 0.8, "社会影响力": 0.2},
            },
        },
    },

    # ---- M4：职业崇拜 ----
    {
        "id": "M4",
        "question": "你心目中「酷」的职业更接近哪一种？",
        "options": {
            "A": {
                "text": "AI研究员、火箭工程师或芯片架构师",
                "industry_weights": {"AI与大模型": 0.4, "半导体与芯片": 0.3, "智能制造": 0.2, "新能源": 0.1},
                "value_weights": {"成长导向": 0.6, "社会影响力": 0.2, "经济回报": 0.2},
            },
            "B": {
                "text": "外科医生、救援队长或无国界医生",
                "industry_weights": {"生物医药": 0.8, "政府公共": 0.2},
                "value_weights": {"社会影响力": 0.7, "稳定偏好": 0.3},
            },
            "C": {
                "text": "投资人、创业者或顶级律师",
                "industry_weights": {"金融科技": 0.6, "互联网与软件": 0.2, "政府公共": 0.2},
                "value_weights": {"经济回报": 0.6, "社会影响力": 0.4},
            },
            "D": {
                "text": "导演、作家或独立音乐人",
                "industry_weights": {"文化传媒": 0.9, "互联网与软件": 0.1},
                "value_weights": {"社会影响力": 0.5, "成长导向": 0.5},
            },
        },
    },

    # ---- M5：成就感来源 ----
    {
        "id": "M5",
        "question": "你觉得什么最能给你带来持续的成就感？",
        "options": {
            "A": {
                "text": "看到自己做的产品被很多人使用",
                "industry_weights": {"互联网与软件": 0.4, "AI与大模型": 0.3, "智能制造": 0.2, "新能源": 0.1},
                "value_weights": {"社会影响力": 0.5, "经济回报": 0.3, "成长导向": 0.2},
            },
            "B": {
                "text": "攻克了一个困扰很久的技术或理论难题",
                "industry_weights": {"AI与大模型": 0.3, "半导体与芯片": 0.3, "生物医药": 0.2, "新能源": 0.2},
                "value_weights": {"成长导向": 0.8, "社会影响力": 0.2},
            },
            "C": {
                "text": "学生/病人/客户因为你而变得更好",
                "industry_weights": {"教育培训": 0.5, "生物医药": 0.4, "政府公共": 0.1},
                "value_weights": {"社会影响力": 0.8, "稳定偏好": 0.2},
            },
            "D": {
                "text": "自己的作品被人欣赏和记住",
                "industry_weights": {"文化传媒": 0.8, "互联网与软件": 0.2},
                "value_weights": {"社会影响力": 0.6, "成长导向": 0.4},
            },
        },
    },

    # ---- M6：风险态度 ----
    {
        "id": "M6",
        "question": "你对「稳定」的态度是？",
        "options": {
            "A": {
                "text": "稳定很重要，倾向于有编制或大平台的工作",
                "industry_weights": {"政府公共": 0.5, "教育培训": 0.3, "生物医药": 0.2},
                "value_weights": {"稳定偏好": 0.9, "社会影响力": 0.1},
            },
            "B": {
                "text": "适度不确定性可以接受，但要有基本保障",
                "industry_weights": {"生物医药": 0.2, "智能制造": 0.2, "新能源": 0.2, "教育培训": 0.2, "金融科技": 0.2},
                "value_weights": {"稳定偏好": 0.4, "风险容忍度": 0.3, "成长导向": 0.3},
            },
            "C": {
                "text": "稳定不是首要考虑，成长空间更重要",
                "industry_weights": {"互联网与软件": 0.3, "AI与大模型": 0.3, "金融科技": 0.2, "新能源": 0.2},
                "value_weights": {"成长导向": 0.7, "风险容忍度": 0.3},
            },
            "D": {
                "text": "喜欢高风险高回报的节奏",
                "industry_weights": {"金融科技": 0.5, "互联网与软件": 0.3, "AI与大模型": 0.2},
                "value_weights": {"风险容忍度": 0.7, "经济回报": 0.3},
            },
        },
    },

    # ---- M7：大学目标 ----
    {
        "id": "M7",
        "question": "你理想中的大学四年最想获得什么？",
        "options": {
            "A": {
                "text": "过硬的专业硬技能，毕业即高薪",
                "industry_weights": {"AI与大模型": 0.3, "互联网与软件": 0.3, "半导体与芯片": 0.2, "金融科技": 0.2},
                "value_weights": {"经济回报": 0.7, "成长导向": 0.3},
            },
            "B": {
                "text": "深厚的理论功底，为读研读博打基础",
                "industry_weights": {"生物医药": 0.3, "AI与大模型": 0.2, "新能源": 0.2, "半导体与芯片": 0.2, "教育培训": 0.1},
                "value_weights": {"成长导向": 0.8, "稳定偏好": 0.2},
            },
            "C": {
                "text": "广泛的人脉和综合能力，未来做什么都行",
                "industry_weights": {"金融科技": 0.3, "互联网与软件": 0.2, "政府公共": 0.3, "教育培训": 0.2},
                "value_weights": {"社会影响力": 0.5, "经济回报": 0.3, "风险容忍度": 0.2},
            },
            "D": {
                "text": "找到自己真正热爱的事业方向",
                "industry_weights": {"文化传媒": 0.4, "教育培训": 0.3, "生物医药": 0.3},
                "value_weights": {"成长导向": 0.6, "社会影响力": 0.4},
            },
        },
    },

    # ---- M8：工作节奏 ----
    {
        "id": "M8",
        "question": "你最能接受哪种工作节奏？",
        "options": {
            "A": {
                "text": "高强度高回报——忙但成长快、收入高",
                "industry_weights": {"AI与大模型": 0.3, "互联网与软件": 0.3, "金融科技": 0.4},
                "value_weights": {"经济回报": 0.6, "风险容忍度": 0.4},
            },
            "B": {
                "text": "规律稳定——朝九晚五，有充足个人时间",
                "industry_weights": {"政府公共": 0.5, "教育培训": 0.3, "生物医药": 0.2},
                "value_weights": {"稳定偏好": 0.9, "社会影响力": 0.1},
            },
            "C": {
                "text": "项目制——忙一阵松一阵，有张有弛",
                "industry_weights": {"智能制造": 0.3, "新能源": 0.3, "半导体与芯片": 0.2, "文化传媒": 0.2},
                "value_weights": {"风险容忍度": 0.4, "成长导向": 0.3, "稳定偏好": 0.3},
            },
            "D": {
                "text": "自由安排——只要能交付成果，时间自己定",
                "industry_weights": {"互联网与软件": 0.4, "文化传媒": 0.3, "AI与大模型": 0.3},
                "value_weights": {"风险容忍度": 0.5, "成长导向": 0.3, "经济回报": 0.2},
            },
        },
    },

    # ---- M9：深耕领域 ----
    {
        "id": "M9",
        "question": "如果必须选一个领域深耕十年，你会选？",
        "options": {
            "A": {
                "text": "计算机、AI或电子硬件",
                "industry_weights": {"AI与大模型": 0.35, "互联网与软件": 0.3, "半导体与芯片": 0.25, "智能制造": 0.1},
                "value_weights": {"经济回报": 0.5, "成长导向": 0.5},
            },
            "B": {
                "text": "医学、生物学或化学",
                "industry_weights": {"生物医药": 0.9, "新能源": 0.1},
                "value_weights": {"社会影响力": 0.6, "成长导向": 0.3, "稳定偏好": 0.1},
            },
            "C": {
                "text": "金融、经济或法律",
                "industry_weights": {"金融科技": 0.6, "政府公共": 0.3, "互联网与软件": 0.1},
                "value_weights": {"经济回报": 0.6, "社会影响力": 0.4},
            },
            "D": {
                "text": "物理、数学或基础研究",
                "industry_weights": {"AI与大模型": 0.3, "半导体与芯片": 0.3, "新能源": 0.2, "智能制造": 0.2},
                "value_weights": {"成长导向": 0.8, "社会影响力": 0.2},
            },
            "E": {
                "text": "教育、心理或社会工作",
                "industry_weights": {"教育培训": 0.7, "政府公共": 0.2, "文化传媒": 0.1},
                "value_weights": {"社会影响力": 0.7, "稳定偏好": 0.3},
            },
        },
    },

    # ---- M10：敬佩对象 ----
    {
        "id": "M10",
        "question": "你更佩服哪类人？",
        "options": {
            "A": {
                "text": "攻克技术难题的工程师或科学家",
                "industry_weights": {"AI与大模型": 0.3, "半导体与芯片": 0.3, "新能源": 0.2, "智能制造": 0.2},
                "value_weights": {"成长导向": 0.7, "社会影响力": 0.3},
            },
            "B": {
                "text": "救死扶伤的医生或冲在一线的记者",
                "industry_weights": {"生物医药": 0.6, "文化传媒": 0.3, "政府公共": 0.1},
                "value_weights": {"社会影响力": 0.8, "风险容忍度": 0.2},
            },
            "C": {
                "text": "白手起家的企业家或顶级投资人",
                "industry_weights": {"互联网与软件": 0.3, "金融科技": 0.5, "AI与大模型": 0.2},
                "value_weights": {"经济回报": 0.6, "风险容忍度": 0.4},
            },
            "D": {
                "text": "影响大众思想的作家、艺术家或教师",
                "industry_weights": {"文化传媒": 0.5, "教育培训": 0.5},
                "value_weights": {"社会影响力": 0.7, "成长导向": 0.3},
            },
        },
    },
]

# ============================================================================
# 第2部分：微观行为场景题（30题，6个场景块 x 5题）
# ============================================================================

DIM_KEYS = {
    "逻辑推理": "logic", "动手实验": "hands_on", "团队协作": "team",
    "创造性思维": "creative", "精细操作": "detail", "持续专注": "focus",
    "沟通表达": "comm", "数据敏感": "data_sense", "抗压能力": "stress_tol",
    "记忆积累": "memory",
}

# -----------------------------------------------------------------------
# Block A：实验课与动手场景（5题）
# -----------------------------------------------------------------------
BLOCK_A = [
    {
        "id": "U1", "block": "A",
        "question": "化学实验课，做完规定步骤后还剩10分钟，你会？",
        "options": {
            "A": {"text": "严格清洗仪器并整理实验台", "dims": {"detail": 4, "focus": 2}},
            "B": {"text": "尝试改一个变量看看结果会怎样", "dims": {"hands_on": 3, "logic": 3, "creative": 2}},
            "C": {"text": "和同学讨论实验结果与理论公式的偏差", "dims": {"team": 3, "logic": 3, "comm": 2}},
            "D": {"text": "帮没做完的同学一起完成实验", "dims": {"team": 4, "comm": 2, "hands_on": 1}},
        },
    },
    {
        "id": "U2", "block": "A",
        "question": "物理实验数据与理论值偏差很大，你的第一反应是？",
        "options": {
            "A": {"text": "仔细回溯每一步操作找具体原因", "dims": {"logic": 4, "detail": 3, "focus": 2}},
            "B": {"text": "立刻重新做一遍实验确认数据", "dims": {"hands_on": 3, "focus": 3, "stress_tol": 2}},
            "C": {"text": "问老师或同学有没有遇到同样问题", "dims": {"comm": 3, "team": 3, "logic": 1}},
            "D": {"text": "在实验报告里系统分析所有可能的误差来源", "dims": {"logic": 3, "memory": 2, "detail": 2}},
        },
    },
    {
        "id": "U3", "block": "A",
        "question": "生物课上要解剖青蛙，你的真实感受是？",
        "options": {
            "A": {"text": "有点紧张但很期待，想看清楚内部结构", "dims": {"hands_on": 3, "logic": 3, "focus": 2}},
            "B": {"text": "不太舒服，更愿意看别人做然后记笔记", "dims": {"memory": 3, "logic": 2, "detail": 2}},
            "C": {"text": "主动要求主刀，操作时极度专注", "dims": {"hands_on": 4, "focus": 3, "detail": 3}},
            "D": {"text": "画下解剖过程的示意图来帮助理解", "dims": {"creative": 4, "memory": 3, "hands_on": 1}},
        },
    },
    {
        "id": "U4", "block": "A",
        "question": "学校科技节让你自由组队做一个作品，你自然想做？",
        "options": {
            "A": {"text": "负责核心的技术实现部分（编程/电路/结构）", "dims": {"hands_on": 3, "logic": 3, "focus": 2}},
            "B": {"text": "负责整体设计和创意方向", "dims": {"creative": 4, "comm": 3, "team": 1}},
            "C": {"text": "负责项目管理和进度协调", "dims": {"team": 4, "comm": 3, "detail": 1}},
            "D": {"text": "负责写设计文档和做最终展示PPT", "dims": {"comm": 3, "detail": 3, "creative": 2}},
        },
    },
    {
        "id": "U5", "block": "A",
        "question": "你拆过闹钟、旧手机或小电器来看里面什么样吗？",
        "options": {
            "A": {"text": "经常拆，我从小就喜欢拆东西看里面的结构", "dims": {"hands_on": 5, "logic": 3, "creative": 2}},
            "B": {"text": "拆过一两次，装回去多出几个螺丝", "dims": {"hands_on": 3, "creative": 2, "logic": 1}},
            "C": {"text": "没拆过但挺想试试的", "dims": {"hands_on": 1, "creative": 1}},
            "D": {"text": "完全没兴趣，坏了就直接换新的", "dims": {}},
        },
    },
]

# -----------------------------------------------------------------------
# Block B：小组作业与协作场景（5题）
# -----------------------------------------------------------------------
BLOCK_B = [
    {
        "id": "U6", "block": "B",
        "question": "小组项目有成员一直划水不做，你会？",
        "options": {
            "A": {"text": "直接找他谈，明确分配任务和截止时间", "dims": {"comm": 3, "stress_tol": 3, "team": 2}},
            "B": {"text": "自己多做一些保证项目质量不受影响", "dims": {"stress_tol": 3, "focus": 3, "hands_on": 2}},
            "C": {"text": "和组长商量重新分工或换人", "dims": {"team": 4, "comm": 3, "logic": 1}},
            "D": {"text": "不太在意，只要最后能交差就行", "dims": {"stress_tol": 1, "detail": -1}},
        },
    },
    {
        "id": "U7", "block": "B",
        "question": "小组讨论时你的想法和大家都不一样，你会？",
        "options": {
            "A": {"text": "用数据和逻辑清晰论证自己的观点，坚持到底", "dims": {"logic": 3, "comm": 3, "stress_tol": 3}},
            "B": {"text": "先认真听大家说完再决定要不要坚持", "dims": {"team": 3, "comm": 3, "logic": 2}},
            "C": {"text": "如果气氛紧张就算了，少数服从多数", "dims": {"team": 3, "stress_tol": -1, "comm": 1}},
            "D": {"text": "不做争论，事后整理文字材料发给所有人", "dims": {"comm": 2, "detail": 2, "memory": 2}},
        },
    },
    {
        "id": "U8", "block": "B",
        "question": "你是小组里最擅长某方面的人，你的态度是？",
        "options": {
            "A": {"text": "主动扛起最难模块，把它做到极致", "dims": {"hands_on": 3, "focus": 3, "stress_tol": 2}},
            "B": {"text": "先给组员做培训让大家都上手", "dims": {"comm": 4, "team": 4, "memory": 2}},
            "C": {"text": "做好自己分内的事，不抢别人发挥的空间", "dims": {"team": 3, "detail": 2, "hands_on": 2}},
            "D": {"text": "有点烦，为什么每次都是我做最难的", "dims": {"stress_tol": -2, "team": -1}},
        },
    },
    {
        "id": "U9", "block": "B",
        "question": "小组展示前一晚，发现PPT有几页数据错了，你会？",
        "options": {
            "A": {"text": "通宵校正所有数据，确保第二天万无一失", "dims": {"stress_tol": 4, "focus": 4, "detail": 3}},
            "B": {"text": "先大概修复最关键的几页，现场临场发挥补充", "dims": {"comm": 3, "stress_tol": 3, "logic": 2}},
            "C": {"text": "在群里紧急呼叫大家一起来处理", "dims": {"team": 4, "comm": 3, "stress_tol": 2}},
            "D": {"text": "很焦虑不知道怎么办，希望有人能出来解决", "dims": {"stress_tol": -3, "team": 1}},
        },
    },
    {
        "id": "U10", "block": "B",
        "question": "做小组项目时你最喜欢的环节是？",
        "options": {
            "A": {"text": "收集和分析数据，得出有说服力的结论", "dims": {"data_sense": 4, "logic": 3, "detail": 2}},
            "B": {"text": "动手做原型或做实验来验证想法", "dims": {"hands_on": 4, "creative": 3, "logic": 2}},
            "C": {"text": "做最终的展示汇报和现场答辩", "dims": {"comm": 4, "stress_tol": 2, "creative": 1}},
            "D": {"text": "统筹安排确保每个人都在正确的时间做正确的事", "dims": {"team": 4, "detail": 3, "logic": 2}},
        },
    },
]

# -----------------------------------------------------------------------
# Block C：课余时间与自发学习（5题）
# -----------------------------------------------------------------------
BLOCK_C = [
    {
        "id": "U11", "block": "C",
        "question": "刷B站/抖音时你最容易沉迷哪类内容？",
        "options": {
            "A": {"text": "硬核科普、技术拆解、数码产品深度评测", "dims": {"hands_on": 3, "logic": 3, "data_sense": 2}},
            "B": {"text": "知识区深度分析：历史、经济、国际政治解读", "dims": {"logic": 3, "memory": 3, "comm": 1}},
            "C": {"text": "创意手工、绘画、音乐制作或旅行Vlog", "dims": {"creative": 4, "hands_on": 2, "comm": 1}},
            "D": {"text": "社会热点深度讨论、人物访谈或辩论赛", "dims": {"comm": 3, "team": 2, "creative": 2}},
        },
    },
    {
        "id": "U12", "block": "C",
        "question": "遇到不懂的问题（比如飞机为什么能飞），你通常？",
        "options": {
            "A": {"text": "马上搜原理图、看公式推导，直到彻底搞懂为止", "dims": {"logic": 4, "focus": 3, "data_sense": 2}},
            "B": {"text": "看个大概解释就行，不求甚解", "dims": {"logic": 1, "focus": 1}},
            "C": {"text": "找相关的科普视频边看边学", "dims": {"memory": 3, "logic": 2, "focus": 1}},
            "D": {"text": "随口问问身边的人，没人知道就算了", "dims": {"comm": 2, "logic": 1}},
        },
    },
    {
        "id": "U13", "block": "C",
        "question": "寒暑假你最有可能会？",
        "options": {
            "A": {"text": "自学一门技能（编程/剪辑/乐器）并做出一个成品", "dims": {"hands_on": 3, "creative": 3, "focus": 4, "stress_tol": 2}},
            "B": {"text": "系统性地预习下学期的理科课程", "dims": {"memory": 3, "focus": 3, "logic": 2, "detail": 2}},
            "C": {"text": "打工/实习/参加社会实践", "dims": {"comm": 3, "team": 3, "stress_tol": 2, "hands_on": 1}},
            "D": {"text": "好好休息，上学已经很累了", "dims": {"focus": -1, "stress_tol": 1}},
        },
    },
    {
        "id": "U14", "block": "C",
        "question": "你玩游戏或解谜时最享受什么？",
        "options": {
            "A": {"text": "复杂的策略规划和资源优化", "dims": {"logic": 4, "data_sense": 4, "focus": 2}},
            "B": {"text": "探索开放世界、发现隐藏内容和彩蛋", "dims": {"creative": 4, "focus": 3, "hands_on": 1}},
            "C": {"text": "和队友精密配合完成高难度挑战", "dims": {"team": 4, "comm": 3, "stress_tol": 2}},
            "D": {"text": "收集养成，看着数值增长和成就解锁", "dims": {"data_sense": 3, "focus": 3, "memory": 2}},
        },
    },
    {
        "id": "U15", "block": "C",
        "question": "你看到一个有意思的数学证明题或编程挑战，你会？",
        "options": {
            "A": {"text": "立刻开始尝试，不解决出来不罢休", "dims": {"logic": 5, "focus": 4, "stress_tol": 3}},
            "B": {"text": "在脑子里过一遍思路，想不出来就看答案", "dims": {"logic": 3, "focus": 2}},
            "C": {"text": "把题目存下来慢慢琢磨，不急", "dims": {"focus": 2, "memory": 2, "logic": 2}},
            "D": {"text": "跳过，课内的题都做不完", "dims": {"logic": 0, "focus": 0}},
        },
    },
]

# -----------------------------------------------------------------------
# Block D：压力与挫折情境（5题）
# -----------------------------------------------------------------------
BLOCK_D = [
    {
        "id": "U16", "block": "D",
        "question": "月考成绩突然大幅下滑（比如从年级前50掉到200名），你的反应是？",
        "options": {
            "A": {"text": "冷静分析每道错题，找出所有失分原因并制定改进计划", "dims": {"logic": 3, "detail": 3, "stress_tol": 3, "focus": 2}},
            "B": {"text": "非常沮丧，需要好几天时间来消化情绪", "dims": {"stress_tol": -3, "focus": -1}},
            "C": {"text": "更努力地刷题，相信量变一定会引起质变", "dims": {"focus": 3, "stress_tol": 3, "memory": 2}},
            "D": {"text": "马上找老师或学霸请教学习方法和解题技巧", "dims": {"comm": 3, "team": 2, "logic": 2}},
        },
    },
    {
        "id": "U17", "block": "D",
        "question": "你准备了很久的一个竞赛/比赛输了，你的反应更接近？",
        "options": {
            "A": {"text": "复盘每一个细节找出差距，下次一定会更好", "dims": {"logic": 3, "focus": 3, "stress_tol": 3, "detail": 2}},
            "B": {"text": "难过一阵但很快转移注意力到别的事上", "dims": {"stress_tol": 2, "comm": 2}},
            "C": {"text": "觉得自己可能不适合这个领域，想换一个方向", "dims": {"stress_tol": -2, "logic": -1}},
            "D": {"text": "更加倍努力训练，用实力证明自己", "dims": {"focus": 4, "stress_tol": 4, "hands_on": 2}},
        },
    },
    {
        "id": "U18", "block": "D",
        "question": "面对同时到来的三个deadline（作业/社团/竞赛），你会？",
        "options": {
            "A": {"text": "列优先级和时间表，逐个击破，一个都不掉链子", "dims": {"detail": 4, "logic": 3, "stress_tol": 3, "focus": 2}},
            "B": {"text": "先做最紧急的，其他的能拖就拖", "dims": {"stress_tol": 2, "focus": 1, "detail": -1}},
            "C": {"text": "申请延期或找人帮忙分担一部分", "dims": {"comm": 3, "team": 3, "stress_tol": 2}},
            "D": {"text": "三件事同时开工，在焦虑中爆肝全部完成", "dims": {"stress_tol": 4, "focus": 4, "detail": -2}},
        },
    },
    {
        "id": "U19", "block": "D",
        "question": "下周你要在全校升旗仪式上做一个5分钟的演讲，你什么状态？",
        "options": {
            "A": {"text": "充分准备，提前写好逐字稿并反复演练几遍", "dims": {"detail": 4, "focus": 3, "stress_tol": 2, "comm": 2}},
            "B": {"text": "有点紧张但知道上台后就能自然发挥", "dims": {"comm": 3, "stress_tol": 3, "creative": 1}},
            "C": {"text": "非常紧张焦虑，恨不得找理由推掉", "dims": {"comm": -3, "stress_tol": -4}},
            "D": {"text": "不紧张，甚至有点享受这种被所有人关注的感觉", "dims": {"comm": 5, "stress_tol": 4}},
        },
    },
    {
        "id": "U20", "block": "D",
        "question": "别人当众批评你的作品或方案时，你通常？",
        "options": {
            "A": {"text": "认真听完，合理的地方改进，不合理的地方解释", "dims": {"logic": 3, "stress_tol": 3, "comm": 3, "detail": 2}},
            "B": {"text": "表面接受但心里不太舒服，不太想再讨论", "dims": {"stress_tol": -2, "comm": -1}},
            "C": {"text": "据理力争，用证据和数据说明自己为什么这么做", "dims": {"logic": 4, "stress_tol": 3, "comm": 3}},
            "D": {"text": "不太在意别人的负面评价", "dims": {"stress_tol": 4, "comm": 1}},
        },
    },
]

# -----------------------------------------------------------------------
# Block E：社交与信息处理（5题）
# -----------------------------------------------------------------------
BLOCK_E = [
    {
        "id": "U21", "block": "E",
        "question": "朋友向你倾诉最近很烦很迷茫，你通常？",
        "options": {
            "A": {"text": "帮他分析问题的前因后果，给出具体可行的建议", "dims": {"logic": 3, "comm": 3, "team": 2}},
            "B": {"text": "先共情安慰，让他感受到被理解和支持", "dims": {"comm": 4, "team": 4, "logic": 1}},
            "C": {"text": "分享你自己类似的经历和你是怎么走过来的", "dims": {"comm": 3, "memory": 3, "team": 2}},
            "D": {"text": "不太擅长处理这种情况，安静听他说完就好", "dims": {"comm": 2, "team": 1}},
        },
    },
    {
        "id": "U22", "block": "E",
        "question": "你对数字、图表和数据的敏感度？",
        "options": {
            "A": {"text": "看到数据就忍不住想分析背后的趋势和规律", "dims": {"data_sense": 5, "logic": 4, "detail": 2}},
            "B": {"text": "能看懂基本的图表但不会主动去深究", "dims": {"data_sense": 2, "logic": 1}},
            "C": {"text": "用图表和数字来支撑自己的观点时特别有说服力", "dims": {"data_sense": 3, "comm": 3, "logic": 2}},
            "D": {"text": "看到数字多的表格就头疼，直接跳过", "dims": {"data_sense": -2, "detail": -1}},
        },
    },
    {
        "id": "U23", "block": "E",
        "question": "写作文或周记时，你更擅长写哪种？",
        "options": {
            "A": {"text": "议论文：论点清晰、逻辑严密、论据扎实", "dims": {"logic": 4, "comm": 3, "detail": 2}},
            "B": {"text": "记叙文：细节丰富、情感真实、画面感强", "dims": {"creative": 4, "comm": 3, "memory": 2}},
            "C": {"text": "说明文：条理清晰、信息完整、结构分明", "dims": {"detail": 4, "logic": 2, "memory": 2}},
            "D": {"text": "都不太擅长，每次写作文都很痛苦", "dims": {"comm": -2, "creative": -1}},
        },
    },
    {
        "id": "U24", "block": "E",
        "question": "在班级或社团中，你更接近什么角色？",
        "options": {
            "A": {"text": "技术/知识担当：大家遇到难题会来问你", "dims": {"logic": 3, "memory": 2, "comm": 2}},
            "B": {"text": "组织者：策划活动、协调资源、推动执行", "dims": {"team": 4, "comm": 3, "stress_tol": 2}},
            "C": {"text": "气氛组：活跃气氛、调解矛盾、凝聚人心", "dims": {"comm": 4, "team": 4, "creative": 1}},
            "D": {"text": "独行侠：做好自己的事，不太参与集体事务", "dims": {"focus": 3, "team": -2}},
        },
    },
    {
        "id": "U25", "block": "E",
        "question": "看到一个引发热议的社会新闻，你的习惯是？",
        "options": {
            "A": {"text": "查多方信息源，交叉验证不同说法后形成自己的判断", "dims": {"logic": 4, "data_sense": 3, "detail": 2}},
            "B": {"text": "看几篇深度分析文章，理解各方的立场和逻辑", "dims": {"memory": 3, "logic": 2, "comm": 2}},
            "C": {"text": "和朋友们讨论，在交流碰撞中理清自己的想法", "dims": {"comm": 4, "team": 3, "logic": 1}},
            "D": {"text": "大概知道怎么回事就行，不会花时间深究", "dims": {"logic": 0, "data_sense": 0}},
        },
    },
]

# -----------------------------------------------------------------------
# Block F：日常习惯与信息摄入（5题）
# -----------------------------------------------------------------------
BLOCK_F = [
    {
        "id": "U26", "block": "F",
        "question": "你整理学习笔记的习惯是？",
        "options": {
            "A": {"text": "有完整的知识体系，按科目/专题精确分类索引", "dims": {"detail": 5, "memory": 3, "logic": 3}},
            "B": {"text": "有笔记但比较随意，自己看得懂就行", "dims": {"memory": 3, "detail": 2}},
            "C": {"text": "用思维导图和可视化方式整理，一目了然", "dims": {"creative": 4, "memory": 3, "logic": 2}},
            "D": {"text": "基本不整理笔记，靠刷题和翻课本复习", "dims": {"memory": -1, "detail": -1, "hands_on": 2}},
        },
    },
    {
        "id": "U27", "block": "F",
        "question": "记忆类任务（背单词/古文/公式/反应方程式）对你来说？",
        "options": {
            "A": {"text": "有一套自己的记忆方法体系，效率还不错", "dims": {"memory": 4, "detail": 3, "logic": 2}},
            "B": {"text": "不太喜欢记东西但肯花时间死磕", "dims": {"memory": 3, "focus": 3, "stress_tol": 2}},
            "C": {"text": "很痛苦，能理解原理但就是记不住", "dims": {"memory": -2, "logic": 1}},
            "D": {"text": "更倾向于理解推导过程而非机械记忆", "dims": {"logic": 3, "memory": 0, "focus": 1}},
        },
    },
    {
        "id": "U28", "block": "F",
        "question": "在做需要耐心和精细度的事（拼复杂模型/刻章/焊接/缝纫）时？",
        "options": {
            "A": {"text": "非常享受，能全神贯注做几个小时直到完美", "dims": {"detail": 5, "focus": 4, "hands_on": 3}},
            "B": {"text": "能做但时间长了会觉得烦", "dims": {"detail": 3, "focus": 2, "hands_on": 2}},
            "C": {"text": "不太擅长精细活，手比较笨", "dims": {"detail": -2, "hands_on": -1}},
            "D": {"text": "完全没耐心做这种事，恨不得快点结束", "dims": {"detail": -4, "focus": -2}},
        },
    },
    {
        "id": "U29", "block": "F",
        "question": "你对整理东西（文件/房间/电脑文件/手机App）的态度？",
        "options": {
            "A": {"text": "有近乎强迫症的整理习惯，分类和命名系统很完善", "dims": {"detail": 5, "data_sense": 2, "focus": 2}},
            "B": {"text": "定期整理保持基本的秩序但不会过度", "dims": {"detail": 3, "data_sense": 1}},
            "C": {"text": "乱但有自己独特的逻辑，别人看不懂但我知道东西在哪", "dims": {"creative": 3, "logic": 1}},
            "D": {"text": "比较乱，经常找不到东西", "dims": {"detail": -3, "data_sense": -1}},
        },
    },
    {
        "id": "U30", "block": "F",
        "question": "老师布置的选做拓展题（不记分、不检查），你会做吗？",
        "options": {
            "A": {"text": "全部认真做完，还主动找更多类似的题来练", "dims": {"focus": 5, "logic": 3, "stress_tol": 3}},
            "B": {"text": "挑自己感兴趣的做", "dims": {"logic": 2, "focus": 2, "creative": 1}},
            "C": {"text": "如果看到同学都在做就跟着做", "dims": {"team": 3, "focus": 1}},
            "D": {"text": "一般不碰，必做的已经够多了", "dims": {"focus": -1, "stress_tol": 1}},
        },
    },
]

MICRO_QUESTIONS = BLOCK_A + BLOCK_B + BLOCK_C + BLOCK_D + BLOCK_E + BLOCK_F

# ============================================================================
# 第3部分：测谎规则对
# ============================================================================

CONSISTENCY_RULES = [
    {"macro_cluster": "AI与大模型", "expected_micro_dims": ["逻辑推理", "持续专注", "动手实验"], "threshold": 40, "severity": 0.5, "label": "向往AI但实际缺乏逻辑与动手热情"},
    {"macro_cluster": "互联网与软件", "expected_micro_dims": ["逻辑推理", "动手实验", "创造性思维"], "threshold": 40, "severity": 0.5, "label": "向往互联网但缺乏动手与创造冲动"},
    {"macro_cluster": "半导体与芯片", "expected_micro_dims": ["逻辑推理", "精细操作", "持续专注"], "threshold": 40, "severity": 0.5, "label": "向往芯片产业但缺乏精密与专注力"},
    {"macro_cluster": "金融科技", "expected_micro_dims": ["数据敏感", "沟通表达", "逻辑推理"], "threshold": 40, "severity": 0.5, "label": "向往金融但缺乏数据敏感与表达力"},
    {"macro_cluster": "生物医药", "expected_micro_dims": ["记忆积累", "持续专注", "精细操作", "抗压能力"], "threshold": 35, "severity": 0.5, "label": "向往医学但缺乏记忆、专注与抗压能力"},
    {"macro_cluster": "教育培训", "expected_micro_dims": ["沟通表达", "团队协作", "记忆积累"], "threshold": 40, "severity": 0.5, "label": "向往教育但缺乏沟通与耐心"},
    {"macro_cluster": "文化传媒", "expected_micro_dims": ["创造性思维", "沟通表达"], "threshold": 40, "severity": 0.5, "label": "向往传媒但缺乏创意与表达力"},
    {"macro_cluster": "政府公共", "expected_micro_dims": ["沟通表达", "团队协作", "记忆积累"], "threshold": 40, "severity": 0.5, "label": "向往体制内但缺乏协作与记忆能力"},
    {"macro_cluster": "智能制造", "expected_micro_dims": ["动手实验", "逻辑推理", "精细操作"], "threshold": 40, "severity": 0.5, "label": "向往制造业但缺乏动手与逻辑能力"},
    {"macro_cluster": "新能源", "expected_micro_dims": ["动手实验", "逻辑推理", "持续专注"], "threshold": 40, "severity": 0.5, "label": "向往新能源但缺乏动手与研究定力"},
]

# ============================================================================
# 第4部分：问卷评分函数
# ============================================================================

def score_macro_questions(answers: dict[str, str]) -> tuple[dict[str, float], dict[str, float]]:
    industry_raw = {ind: 0.0 for ind in INDUSTRY_CLUSTERS}
    value_raw = {"稳定偏好": 0.0, "成长导向": 0.0, "风险容忍度": 0.0, "社会影响力": 0.0, "经济回报": 0.0}
    answered_count = 0
    for q in MACRO_QUESTIONS:
        chosen = answers.get(q["id"])
        if chosen and chosen in q["options"]:
            answered_count += 1
            opt = q["options"][chosen]
            for ind, weight in opt["industry_weights"].items():
                industry_raw[ind] += weight * 10
            for val, weight in opt["value_weights"].items():
                value_raw[val] += weight * 10
    max_possible = max(answered_count, 1) * 10 * 1.0
    industry_vector = {k: min(100.0, round(v / max_possible * 100, 1)) for k, v in industry_raw.items()}
    value_vector = {k: min(100.0, round(v / max_possible * 100, 1)) for k, v in value_raw.items()}
    return industry_vector, value_vector

def score_micro_questions(answers: dict[str, str]) -> dict[str, float]:
    raw = {dim: 0.0 for dim in BEHAVIOR_DIMENSIONS}
    max_possible = {dim: 0.0 for dim in BEHAVIOR_DIMENSIONS}
    for q in MICRO_QUESTIONS:
        for opt in q["options"].values():
            for dim_key, delta in opt["dims"].items():
                dim_name = _resolve_dim(dim_key)
                if delta > 0:
                    max_possible[dim_name] += delta
        chosen = answers.get(q["id"])
        if chosen and chosen in q["options"]:
            for dim_key, delta in q["options"][chosen]["dims"].items():
                dim_name = _resolve_dim(dim_key)
                raw[dim_name] += delta
    behavior_vector = {}
    for dim in BEHAVIOR_DIMENSIONS:
        mx = max_possible[dim]
        if mx > 0:
            normalized = raw[dim] / mx * 100.0
            behavior_vector[dim] = min(100.0, max(0.0, round(normalized, 1)))
        else:
            behavior_vector[dim] = 50.0
    return behavior_vector

def _resolve_dim(dim_key: str) -> str:
    mapping = {"logic": "逻辑推理", "hands_on": "动手实验", "team": "团队协作", "creative": "创造性思维", "detail": "精细操作", "focus": "持续专注", "comm": "沟通表达", "data_sense": "数据敏感", "stress_tol": "抗压能力", "memory": "记忆积累"}
    return mapping.get(dim_key, dim_key)

def score_all(macro_answers, micro_answers):
    return score_macro_questions(macro_answers)[0], score_macro_questions(macro_answers)[1], score_micro_questions(micro_answers)

def build_user_from_answers(macro_answers, micro_answers, selected_subjects=None, estimated_score=0, estimated_rank_percentile=100.0, physical_conditions=None, family_economic_level="中", family_city_tier="新一线", family_has_overseas_resource=False, family_has_industry_connection="无", special_track_intent=None, special_track_stance=None):
    industry_vector, value_vector, behavior_vector = score_all(macro_answers, micro_answers)
    user = UserProfile(selected_subjects=selected_subjects or [], estimated_score=estimated_score, estimated_rank_percentile=estimated_rank_percentile, physical_conditions=physical_conditions or [], family_economic_level=family_economic_level, family_city_tier=family_city_tier, family_has_overseas_resource=family_has_overseas_resource, family_has_industry_connection=family_has_industry_connection, special_track_intent=special_track_intent, special_track_stance=special_track_stance, macro_industry_vector=industry_vector, macro_value_vector=value_vector, micro_behavior_vector=behavior_vector)
    user.infer_personality_from_behavior()
    return user

if __name__ == "__main__":
    import random
    random.seed(42)
    macro_answers = {f"M{i}": random.choice(["A", "B", "C", "D"]) for i in range(1, 11)}
    macro_answers["M9"] = random.choice(["A", "B", "C", "D", "E"])
    micro_answers = {f"U{i}": random.choice(["A", "B", "C", "D"]) for i in range(1, 31)}
    ind_vec, val_vec, beh_vec = score_all(macro_answers, micro_answers)
    print("=" * 60)
    print("宏观产业向量:")
    for k, v in sorted(ind_vec.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * int(v / 5)
        print(f"  {k:12s}: {v:5.1f}  {bar}")
    print()
    print("微观行为向量:")
    for k, v in sorted(beh_vec.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * int(v / 5)
        print(f"  {k:8s}: {v:5.1f}  {bar}")
