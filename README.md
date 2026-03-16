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
- 终端输出 Phase 1 solo-venture screener（Top1/Top0 + 过滤样本）
- JSON 保存到 `data/` 目录
- Markdown 报告保存为 `data/phase1_report_*.md` 与 `data/latest_phase1.md`
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
--enable-github-issues  显式启用 GitHub issue 创建
--enable-mvp-generation 显式启用 MVP 自动生成
--debug         调试模式
--test          测试模式
```

## 输出示例

```
Top1 | 保留观察 | 等级 B
切入 wedge：不要复刻原产品，而是切其中最窄、最容易先收钱的工作流。
14 天收钱：先卖一个可人工兜底的轻服务版本，验证是否有人愿意付首单。
前 20 个用户：从原始帖子评论区、相关社区和现有人脉里做定向外联。

过滤样本：
1. 暂不投入 | 等级 C | 14 天内收钱路径不够清晰
2. 直接过滤 | 等级 D | 前 20 个用户来源不够具体
```

## 扩展数据源

编辑 `collectors/` 目录添加新的数据源：

- `appstore.py` - Appstore 榜单
- `xiaohongshu.py` - 小红书
- `weibo.py` - 微博热点

## License

MIT
