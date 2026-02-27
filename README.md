# Research Agent - 产品机会调研

自动调研 Hacker News、Product Hunt 等平台，发现产品机会。

## 快速开始

### 1. 安装依赖

```bash
cd ~/.openclaw/workspace/agents/research
pip3 install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写：

```bash
BAILIAN_API_KEY=sk-your-api-key-here
FEISHU_USER_ID=ou_xxx  # 可选，用于飞书推送
```

获取阿里百炼 API Key: https://bailian.console.aliyun.com

### 3. 测试运行

```bash
python3 main.py --test
```

### 4. 正常运行

```bash
python3 main.py
```

输出：
- 终端显示 Top 5 机会
- JSON 保存到 `data/` 目录
- 日志保存到 `logs/` 目录

## 配置 OpenClaw Cron

```bash
# 添加定时任务（每天早上 9 点）
openclaw cron add \
  --name "research-agent" \
  --cron "0 9 * * *" \
  --message "run research agent"

# 查看任务
openclaw cron list

# 手动测试
openclaw cron run research-agent
```

## 参数说明

```bash
python3 main.py --help

--hn-limit      HN 获取数量 (默认 30)
--ph-limit      PH 获取数量 (默认 20)
--min-score     最低分数阈值 (默认 60)
--debug         调试模式
--test          测试模式
```

## 输出示例

```
🔥 【机会 #47173121】

📌 标题：Statement from Dario Amodei on our discussions with the Department of War
🔗 来源：HN
📊 评分：85/100
🔗 链接：https://www.anthropic.com/news/...

📝 摘要：
Anthropic 与美国国防部合作，AI 安全讨论...

💡 建议方向：
AI 安全合规工具，面向政府/企业客户

🏷️ 标签：AI, GovTech, B2B
```

## 扩展数据源

编辑 `collectors/` 目录添加新的数据源：

- `appstore.py` - Appstore 榜单
- `xiaohongshu.py` - 小红书
- `weibo.py` - 微博热点

## License

MIT
