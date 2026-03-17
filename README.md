# Research Agent - 产品机会调研

自动调研 Hacker News、Product Hunt 等平台，发现产品机会。

## 快速开始

### 1. 安装依赖

```bash
cd /path/to/research-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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
- 终端输出 Phase 1 screener（今日唯一候选 + 继续观察 + 今天不值得做）
- 每日报告会显式输出“今日最该调整的一条筛选规则”
- JSON 保存到 `data/` 目录
- Markdown 报告保存为 `data/phase1_report_*.md` 与 `data/latest_phase1.md`
- 深筛周报可额外生成 `data/weekly_report_*.md` 与 `data/latest_weekly.md`
- 日志保存到 `logs/` 目录

## 深筛周报

基于最近几天的 `data/opportunities_*.json` 历史快照做二次归纳，不重新调用采集和分析接口：

```bash
python3 main.py --weekly-report
python3 main.py --weekly-report --weekly-days 10
```

周报会固定输出四块：
- 反复出现的痛点
- 重复出现的切口
- 最常见伪机会类型
- 本周唯一值得认真验证的方向

这个模式默认只写本地 markdown，不改动现有每日 Feishu 同步和索引行为。

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
--weekly-report 基于历史快照生成深筛周报
--weekly-days   深筛周报回看天数 (默认 7)
--enable-app-store-reviews    启用 App Store 差评采集
--app-store-review-limit      App Store 差评采集数量 (默认 8)
--enable-github-pain-issues   启用 GitHub issue 痛点采集
--github-pain-limit           GitHub issue 痛点采集数量 (默认 8)
--enable-github-issues  显式启用 GitHub issue 创建
--enable-mvp-generation 显式启用 MVP 自动生成
--debug         调试模式
--test          测试模式
```

默认保持保守：`App Store reviews` 和 `GitHub issue pains` 都是显式开启，避免日常自动化因为新源噪音突然放量。

## 输出示例

```
今日唯一候选 | 做 7 天 MVP 验证 | 信号 高
切口名称：退款滥用审计报告
目标用户：月销 5-50 万美元的 Shopify 商家运营负责人
高频场景：出现退款争议、退款滥用或高风险订单时
当前替代方案：人工流程、Excel/表单，加上通用风控工具
为什么现有方案不好：现有方案不会只为这一个结果优化，最后还是要人工兜底
为什么现在值得做：14 天收钱窗口明确，首批 20 用户来源具体
为什么适合用户：不需要换系统，只要直接拿到审计结果就能试用
6 周最小收费版本：先卖每周一次的退款滥用审计报告试点
首批 20 用户从哪里来：从 Shopify 退款求助帖、DTC 创始人社群和支付风控讨论串外联
验证动作（landing page / 7 day MVP / 丢弃）：做 7 天 MVP 验证
不该做大的边界：别做完整风控平台
最终结论：做 7 天 MVP 验证

继续观察：
1. 做 landing page 验证 | 信号 高 | AI playbook setup for engineering teams

今天不值得做：
- 项目管理型机会: 红海主战场，首客名单和首单动作都还是模板话
- 通用 AI 编程助手型机会: 容易撞上大厂原生能力，没有先收钱的窄切口
- 白噪音/专注型机会: 需求泛而弱，分发与付费证据都不够硬
```

## Feishu Doc 验证

`sync_report_to_feishu()` 会优先尝试真实 Feishu DocX 写入；若运行环境、凭据或网络不满足条件，会输出明确 blocker，而不是只打印笼统的失败/跳过。

当前仓库已完成一次真实端到端验收：

- 2026-03-17：成功创建并写入 Feishu Doc，返回真实 docx URL：`https://feishu.cn/docx/FDXqd8UfxodCBKx1vgoc44SMnBd`

之前也验证过两类真实 blocker，代码仍会显式报告：

- `EPERM 127.0.0.1:7897`：当前代理/沙箱不允许连到本地代理。
- `ENOTFOUND open.feishu.cn`：当前环境没有可用的 Feishu 外网 DNS/网络访问。

典型 blocker 输出示例：

```text
Feishu doc sync blocked: node runtime not found; install Node.js or add node to PATH
Feishu doc sync blocked: @larksuiteoapi/node-sdk not found; checked NODE_PATH candidates: ...
Feishu doc sync blocked: FEISHU_APP_ID / FEISHU_APP_SECRET not configured
Feishu doc sync blocked: outbound Feishu API access is blocked by the current proxy/network sandbox (cannot connect to 127.0.0.1:7897)
Feishu doc sync blocked: outbound DNS/network access to open.feishu.cn is unavailable in the current environment
```

## 扩展数据源

当前新增了两类高价值、低摩擦数据源：

- `App Store reviews`
  用法：`python3 main.py --enable-app-store-reviews --app-store-review-limit 8`
  采集逻辑：抓取 Business / Productivity 榜单头部 App 的近期差评，优先保留 1-3 星、文本足够长的真实抱怨。

- `GitHub issue pains`
  用法：`python3 main.py --enable-github-pain-issues --github-pain-limit 8`
  采集逻辑：抓取一组高杠杆开源产品仓库中高评论的 open issue，优先保留带 enhancement / bug / feature request 等痛点讨论。

## License

MIT
