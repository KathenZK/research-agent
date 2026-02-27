# Research Agent - 战略投资情报系统

> **版本**: v1.0  
> **最后更新**: 2026-02-27  
> **状态**: ✅ 生产就绪

---

## 📋 目录

- [功能概述](#功能概述)
- [技术架构](#技术架构)
- [消息源](#消息源)
- [分析框架](#分析框架)
- [配置说明](#配置说明)
- [使用指南](#使用指南)
- [待办事项](#待办事项)

---

## 功能概述

Research Agent 是一个自动化战略投资情报系统，模拟大公司战略投资部门的工作流程：

1. **市场监控** - 实时监控多个消息源
2. **机会发现** - AI 分析识别商业机会
3. **深度分析** - 尽职调查级项目评估
4. **商业化建议** - 可落地的商业化方案

### 核心价值

- ⏰ **效率提升**: 自动收集分析，节省 90% 人工调研时间
- 📊 **分析深度**: 每个项目输出 200+ 字详细分析
- 🎯 **决策支持**: 提供盈利模式、竞争对手、商业化建议
- 📈 **可扩展**: 模块化设计，可添加新消息源

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Research Agent v1.0                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Collectors  │  │  Collectors  │  │  Collectors  │      │
│  │   Hacker     │  │   Product    │  │   Twitter    │      │
│  │    News      │  │    Hunt      │  │   (TODO)     │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         └─────────────────┴─────────────────┘               │
│                           │                                 │
│                  ┌────────▼────────┐                        │
│                  │   Analyzer      │                        │
│                  │  (Bailian API)  │                        │
│                  │ qwen3-coder-plus│                        │
│                  └────────┬────────┘                        │
│                           │                                 │
│         ┌─────────────────┼─────────────────┐              │
│         │                 │                 │              │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐     │
│  │    JSON      │  │   Feishu     │  │   Console    │     │
│  │   Export     │  │  Notification│  │    Output    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 核心组件

| 组件 | 文件 | 功能 |
|------|------|------|
| **主程序** | `main.py` | 流程控制、参数解析 |
| **配置** | `config.py` | 环境变量加载、配置验证 |
| **收集器** | `collectors/` | HN, PH 数据抓取 |
| **分析器** | `analyzers/bailian.py` | AI 分析、重试机制 |
| **数据模型** | `models/opportunity.py` | 机会数据结构 |

---

## 消息源

### 已支持

| 消息源 | 类型 | 更新频率 | 状态 |
|--------|------|---------|------|
| **Hacker News** | 科技新闻 | 实时 | ✅ |
| **Product Hunt** | 新产品 | 每日 | ✅ (RSS) |

### 计划中

| 消息源 | 类型 | 优先级 | 预计完成 |
|--------|------|--------|---------|
| **Twitter/X** | 社交媒体 | 🔴 高 | Phase 1 |
| **36 氪** | 科技媒体 | 🔴 高 | Phase 1 |
| **虎嗅** | 商业媒体 | 🟡 中 | Phase 1 |
| **Crunchbase** | 投融资数据 | 🟡 中 | Phase 1 |
| **微信公众号** | 自媒体 | 🟡 中 | Phase 2 |
| **小红书** | 生活方式 | 🟢 低 | Phase 2 |
| **IT 桔子** | 投融资数据 | 🟢 低 | Phase 2 |

---

## 分析框架

### 输出字段

每个项目机会包含以下分析维度：

| 字段 | 字数 | 说明 |
|------|------|------|
| **项目介绍** | 200 字 | 做什么、解决什么问题、目标用户 |
| **盈利模式** | 150 字 | 如何赚钱、定价策略 |
| **竞争对手** | 150 字 | 市场格局、竞品分析 |
| **建议方向** | 150 字 | 可落地的商业化建议 |
| **评分** | 0-100 | 综合评估分数 |

### 评分标准

| 分数段 | 标准 | 建议 |
|--------|------|------|
| **90-100** | 明确痛点 + 付费意愿强 + 竞争少 + 市场大 | 立即跟进 |
| **70-89** | 有需求 + 有市场 + 可差异化 | 深入研究 |
| **50-69** | 一般机会，需要验证 | 保持关注 |
| **0-49** | 不建议做 | 跳过 |

---

## 配置说明

### 环境变量

创建 `.env` 文件：

```bash
# 阿里百炼 API (Coding Plan 专属)
BAILIAN_API_KEY=sk-sp-xxxxxxxxxxxxxxxx
BAILIAN_BASE_URL=https://coding.dashscope.aliyuncs.com/apps/anthropic
BAILIAN_MODEL=qwen3-coder-plus
BAILIAN_TIMEOUT=60

# 飞书通知 (可选)
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_USER_ID=ou_xxx

# 调试模式
DEBUG=false
```

### 依赖安装

```bash
cd ~/.openclaw/workspace/agents/research
pip3 install -r requirements.txt
```

### 定时任务

已配置 macOS LaunchAgent，每天 9:00 AM 自动执行：

```bash
# 查看状态
launchctl list | grep research-agent

# 手动触发
python3 main.py --hn-limit 10 --ph-limit 5 --min-score 60
```

---

## 使用指南

### 基本用法

```bash
# 默认运行
python3 main.py

# 自定义参数
python3 main.py --hn-limit 20 --ph-limit 10 --min-score 50

# 调试模式
python3 main.py --debug
```

### 输出示例

```
================================================================================
发现 2 个产品机会
================================================================================

#1 [HN] 评分：78/100
   标题：We deserve a better streams API for JavaScript
   链接：https://blog.cloudflare.com/a-better-web-streams-api/

   📖 项目介绍
   这是一个针对 JavaScript Web Streams API 的技术改进方案...

   💰 盈利模式
   作为 Cloudflare 基础设施服务的一部分...

   🏆 竞争对手
   Node.js 内置 Stream API、RxJS 响应式编程库...

   💡 建议方向
   可以构建专门的流处理开发工具平台...

   🔗 相关链接
   - 原始链接：https://blog.cloudflare.com/a-better-web-streams-api/
   - https://www.google.com/search?q=...
   - https://www.google.com/search?q=...+competitors+alternatives

--------------------------------------------------------------------------------
```

---

## 待办事项

### Phase 1 (本周)

- [ ] 添加 Twitter/X 收集器 (xurl)
- [ ] 添加 36 氪 RSS 收集器
- [ ] 添加虎嗅 RSS 收集器
- [ ] 添加 Crunchbase API 集成
- [ ] 改进分析模板 (TAM/SAM/SOM)

### Phase 2 (下周)

- [ ] 微信公众号接入 (新榜 API)
- [ ] 小红书爬虫研究
- [ ] 商业评估模型完善
- [ ] 竞争格局图谱可视化

### Phase 3 (长期)

- [ ] 实时监控和告警
- [ ] Grafana 数据看板
- [ ] PDF 报告自动生成
- [ ] 飞书多维表格集成

---

## 项目结构

```
research-agent/
├── main.py                 # 主程序
├── config.py              # 配置管理
├── requirements.txt       # Python 依赖
├── .env                   # 环境变量 (不提交)
├── .env.example          # 环境变量模板
├── analyzers/
│   ├── __init__.py
│   └── bailian.py        # 百炼 AI 分析器
├── collectors/
│   ├── __init__.py
│   ├── hn.py             # Hacker News 收集器
│   └── ph.py             # Product Hunt 收集器
├── models/
│   ├── __init__.py
│   └── opportunity.py    # 机会数据模型
├── data/                  # 输出数据
│   ├── opportunities_*.json
│   └── latest.json
└── logs/                  # 日志文件
    └── *.log
```

---

## 相关链接

- **GitHub 仓库**: https://github.com/KathenZK/research-agent
- **API 文档**: https://help.aliyun.com/zh/dashscope/
- **问题反馈**: GitHub Issues

---

*最后更新：2026-02-27 23:15*
