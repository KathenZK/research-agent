# Phase 1 实施计划 - 快速增强

> **时间**: 2026-02-28 ~ 2026-03-02  
> **目标**: 从 Demo 到可用的战略投资工具  
> **优先级**: 🔴 高

---

## 📋 任务清单

### 1. Twitter/X 集成 🔴

**目标**: 添加 Twitter 作为消息源，监控科技圈动态

**技术方案**:
- 使用已安装的 `xurl` 工具
- 需要配置 Twitter API (OAuth 2.0)

**实现步骤**:
1. 配置 xurl (已完成 API Key 配置)
2. 创建 `collectors/twitter.py`
3. 监控关键词：`AI startup`, `launch`, `funding`, `YC`
4. 集成到主程序

**代码框架**:
```python
# collectors/twitter.py
import subprocess
import json

class TwitterCollector:
    @staticmethod
    def search(keywords: list, limit: int = 20) -> list:
        """搜索 Twitter"""
        results = []
        for keyword in keywords:
            # 使用 xurl search
            cmd = f'xurl search "{keyword}" -n {limit}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            tweets = json.loads(result.stdout)
            results.extend(tweets.get('data', []))
        return results
```

**预计时间**: 2 小时

---

### 2. 36 氪 RSS 集成 🔴

**目标**: 监控国内科技媒体

**技术方案**:
- RSS 订阅 + BeautifulSoup 解析

**RSS 源**:
- 36 氪：`https://36kr.com/feed`
- 虎嗅：`https://www.huxiu.com/rss/0.xml`

**实现步骤**:
1. 创建 `collectors/chinese_media.py`
2. 使用 `feedparser` 解析 RSS
3. 提取标题、链接、发布时间、摘要
4. 过滤关键词（AI、融资、创业）

**代码框架**:
```python
# collectors/chinese_media.py
import feedparser
from datetime import datetime, timedelta

class ChineseMediaCollector:
    RSS_FEEDS = {
        '36kr': 'https://36kr.com/feed',
        'huxiu': 'https://www.huxiu.com/rss/0.xml'
    }
    
    @staticmethod
    def fetch(hours: int = 24) -> list:
        """获取最近 N 小时的文章"""
        items = []
        for source, url in ChineseMediaCollector.RSS_FEEDS.items():
            feed = feedparser.parse(url)
            for entry in feed.entries:
                # 过滤和转换
                if ChineseMediaCollector._is_relevant(entry.title):
                    items.append({
                        'id': entry.id,
                        'title': entry.title,
                        'url': entry.link,
                        'source': source,
                        'published': entry.published,
                        'summary': entry.summary[:500]
                    })
        return items
```

**预计时间**: 1 小时

---

### 3. Crunchbase API 集成 🟡

**目标**: 获取全球投融资数据

**技术方案**:
- Crunchbase API v4
- 免费额度：200 次/月

**实现步骤**:
1. 注册 Crunchbase API Key
2. 创建 `collectors/crunchbase.py`
3. 监控关键词：`AI startup funding`, `seed round`, `Series A`
4. 提取：公司名、融资金额、投资方、行业

**API 文档**: https://developer.crunchbase.com/

**代码框架**:
```python
# collectors/crunchbase.py
import requests

class CrunchbaseCollector:
    API_KEY = 'YOUR_API_KEY'
    BASE_URL = 'https://api.crunchbase.com/api/v4'
    
    @staticmethod
    def search_funding(keywords: list, limit: int = 10) -> list:
        """搜索融资事件"""
        results = []
        for keyword in keywords:
            response = requests.get(
                f'{CrunchbaseCollector.BASE_URL}/searches/organizations',
                headers={'X-cb-user-key': CrunchbaseCollector.API_KEY},
                params={'query': keyword, 'limit': limit}
            )
            results.extend(response.json().get('entities', []))
        return results
```

**预计时间**: 3 小时 (含 API 申请)

---

### 4. 分析模板改进 🔴

**目标**: 投资尽调级分析框架

**新增分析维度**:

| 维度 | 说明 | 字数 |
|------|------|------|
| **市场规模** | TAM/SAM/SOM 分析 | 150 字 |
| **进入壁垒** | 技术/资金/监管壁垒 | 100 字 |
| **风险评估** | 市场/技术/团队风险 | 150 字 |
| **投资建议** | 跟投/领投/观望 | 100 字 |

**更新后的 Prompt**:
```
请作为战略投资总监分析这个项目：

1. 项目介绍 (200 字)
2. 市场规模 - TAM/SAM/SOM (150 字)
3. 盈利模式 (150 字)
4. 竞争格局 (150 字)
5. 进入壁垒 (100 字)
6. 风险评估 (150 字)
7. 投资建议 (100 字)

输出 JSON 格式...
```

**预计时间**: 2 小时

---

## 📅 时间表

| 日期 | 任务 | 产出 |
|------|------|------|
| **Day 1 (2/28)** | Twitter 集成 + 36 氪集成 | 2 个新收集器 |
| **Day 2 (3/1)** | Crunchbase 集成 + 分析模板 | 投融资数据 + 尽调框架 |
| **Day 3 (3/2)** | 测试 + 文档 + 部署 | 生产就绪 |

---

## 🎯 验收标准

### 功能验收

- [ ] 至少 5 个消息源 (HN, PH, Twitter, 36 氪，Crunchbase)
- [ ] 每个项目输出 800+ 字分析
- [ ] 包含 TAM/SAM/SOM 分析
- [ ] 包含风险评估
- [ ] 包含投资建议

### 质量验收

- [ ] 无 API 错误 (重试机制生效)
- [ ] 分析深度达到投资经理水平
- [ ] 输出格式结构化 (JSON + Markdown)
- [ ] 文档完整

---

## 📊 预期效果

### 改进前 vs 改进后

| 指标 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| **消息源** | 2 个 | 5 个 | +150% |
| **分析字数** | 200 字 | 800+ 字 | +300% |
| **分析维度** | 3 个 | 7 个 | +133% |
| **决策支持** | 基础建议 | 投资建议 | 质的飞跃 |

### 示例输出

```
#1 [36Kr] 评分：85/100
   标题：AI 初创公司 X 完成千万美元 A 轮融资

   📖 项目介绍 (200 字)
   ...
   
   📊 市场规模 (150 字)
   TAM: 全球 AI 市场 $190B (2024)
   SAM: 中国 AI 企业服务市场 $45B
   SOM: 可获取市场 $2B (首年目标 1%)
   
   💰 盈利模式 (150 字)
   SaaS 订阅制 + 定制化实施
   ARPU: ¥50,000/年
   LTV/CAC: 4.5x
   
   🏆 竞争格局 (150 字)
   直接竞品：A 公司、B 公司
   间接竞品：传统软件厂商
   竞争优势：技术壁垒 + 先发优势
   
   🚧 进入壁垒 (100 字)
   技术壁垒：专利 3 项
   资金壁垒：需要¥20M 启动
   监管壁垒：需要 AI 算法备案
   
   ⚠️ 风险评估 (150 字)
   市场风险：巨头入场竞争
   技术风险：模型迭代速度
   团队风险：核心人员流失
   
   💡 投资建议 (100 字)
   建议：跟投 A 轮
   理由：市场空间大 + 团队背景强
   估值：¥80M Pre-money 合理
```

---

## 🔗 相关资源

- [Twitter API 文档](https://developer.twitter.com/en/docs)
- [Crunchbase API 文档](https://developer.crunchbase.com/)
- [36 氪 RSS](https://36kr.com/feed)
- [投资分析框架](https://www.investopedia.com/terms/t/tam-sam-som.asp)

---

*创建时间：2026-02-27 23:15*
