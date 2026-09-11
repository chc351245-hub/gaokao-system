# 高考志愿智能推荐系统 v6.0

基于三层递进漏斗算法的高考志愿推荐系统，通过40道隐蔽式深度测评题，从883个专业中为你匹配最适合的专业方向。

## 功能特点

- **隐蔽式测评设计**：10道宏观产业向往题 + 30道微观行为场景题
- **三层递进漏斗**：门类初筛 → 专业类 Top 8 → 专业微观狙击(≤6/类)
- **883个专业全覆盖**：涵盖13个学科门类、93个专业类
- **测谎机制**：宏观向往与微观行为矛盾检测，防止"叶公好龙"
- **家庭资源约束**：考虑经济水平、城市层级、行业人脉等现实因素

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行应用

```bash
streamlit run app.py
```

### 3. 部署到 Streamlit Cloud

1. 将本项目上传到 GitHub
2. 访问 [share.streamlit.io](https://share.streamlit.io)
3. 连接你的 GitHub 仓库
4. 选择 `app.py` 作为主文件
5. 点击 Deploy

## 项目结构

```
├── app.py                    # 主应用入口
├── funnel_engine.py          # 三层递进漏斗引擎
├── questionnaire.py          # 问卷模块（40题）
├── recommendation_engine.py  # 推荐引擎
├── user_profile.py           # 用户画像模块
├── gaokao_majors.xlsx        # 883个专业数据
├── label_checkpoints/        # 标签数据
│   ├── layer1_disciplines.json
│   ├── layer2_categories.json
│   ├── layer3_majors.json
│   └── enrollment_volume.json
├── requirements.txt          # Python依赖
└── README.md                 # 本文件
```

## 算法说明

### 三层递进漏斗

1. **第1层 - 学科门类初筛**：基于认知风格和人格倾向匹配13个门类
2. **第2层 - 专业类精选**：结合产业向往、家庭资源、分数段 → Top 8 截断
3. **第3层 - 专业微观狙击**：微观行为匹配 + 热度 + 红线过滤 → ≤6/类

### 五维标签体系

- **门槛标签**：选科要求、体检限制
- **微观行为标签**：10个核心行为维度匹配
- **产业映射标签**：专业与10大产业集群的关联度
- **资源敏感标签**：家庭资源对专业发展的影响
- **分数敏感标签**：不同分数段的录取难度

## 免责声明

本测评结果基于数据模型生成，仅供志愿填报参考。高考录取受政策、排位、招生计划等多重动态因素影响，可能存在数据偏差。最终志愿决策与风险需由本人及家属独立承担。

## 技术栈

- **前端框架**：Streamlit
- **数据处理**：Pandas, OpenPyXL
- **可视化**：Plotly
- **算法**：余弦相似度、多维度加权匹配

## License

MIT
