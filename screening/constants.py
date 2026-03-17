#!/usr/bin/env python3
"""Constants used by the Phase 2 screening pipeline."""

import os
from typing import Dict, List, Tuple

from config import DATA_DIR

# ---------------------------------------------------------------------------
# Thresholds & limits
# ---------------------------------------------------------------------------

PHASE1_KEEP_MIN_SCORE = 75
PHASE1_FILTER_LIMIT = 5
PHASE2_WATCH_LIMIT = 3
PHASE2_KEEP_MIN_SCORE = 83
PHASE2_WATCH_MIN_SCORE = 72

FINAL_ACTION_LANDING_PAGE = '做 landing page 验证'
FINAL_ACTION_7DAY_MVP = '做 7 天 MVP 验证'
FINAL_ACTION_DROP = '丢弃'

# ---------------------------------------------------------------------------
# Source quality mapping
# ---------------------------------------------------------------------------

SOURCE_QUALITY: Dict[str, str] = {
    'appstore_reviews': 'pain',
    'github_issues': 'pain',
    'reddit_pain': 'pain',
    'saas_reviews': 'pain',
    'v2ex': 'pain',
    'zhihu': 'pain',
    'sspai': 'discussion',
    'reddit': 'discussion',
    'reddit_r/saas': 'discussion',
    'reddit_r/entrepreneur': 'discussion',
    'github': 'discussion',
    'github_trending': 'discussion',
    'x': 'discussion',
    'hn': 'hype',
    'ph': 'hype',
    'indiehackers': 'story',
    '36kr': 'news',
    'huxiu': 'news',
    'tiehan': 'news',
}

SOURCE_QUALITY_SCORE: Dict[str, int] = {
    'pain': 5,
    'discussion': 2,
    'hype': -3,
    'story': -5,
    'news': -4,
}

# ---------------------------------------------------------------------------
# Category profiles
# ---------------------------------------------------------------------------

PHASE2_CATEGORY_PROFILES = [
    {
        'name': 'billing_analytics',
        'terms': ['stripe', 'billing', 'mrr', 'churn', 'failed payment', 'subscription analytics', '支付', '订阅分析', '营收分析'],
        'category_label': '支付/订阅分析',
        'avoid_label': '完整的 Stripe 分析仪表盘',
        'default_target': '使用 Stripe 的 20-200 人 SaaS 团队创始人或营收负责人',
        'trigger': '每周复盘 MRR、流失和失败扣款时',
        'deliverable': '一份可直接执行的 failed payment 与流失诊断报告',
        'first_users_hint': '去 Indie Hackers、Stripe 开发者社区和讨论 churn / failed payment 的 SaaS 创始人帖子里定向约 20 人',
        'crowded': True,
    },
    {
        'name': 'project_management',
        'terms': ['project management', 'task management', 'kanban', 'roadmap', 'sprint', '项目管理', '任务管理', '协作工具'],
        'category_label': '项目管理',
        'avoid_label': '一个新的项目管理工具',
        'default_target': '2-10 人远程产品团队的创始人或项目负责人',
        'trigger': '周会前或 sprint 切换时',
        'deliverable': '一份自动清理过期任务并标出 blocker 的周会摘要',
        'first_users_hint': '去 Indie Hackers、Linear/Jira/Notion 模板帖和远程团队社群里约首批 20 个团队负责人',
        'crowded': True,
    },
    {
        'name': 'ai_coding',
        'terms': ['code generation', 'coding assistant', 'ai coding', 'developer tool', '开发工具', '代码生成', 'claude code', 'copilot', 'agent computer'],
        'category_label': 'AI 开发工具',
        'avoid_label': '一个通用 AI 编程助手',
        'default_target': '维护单一代码栈的 3-20 人开发团队负责人',
        'trigger': '需要新建模块、补测试或做迁移时',
        'deliverable': '一个针对单一框架的脚手架、测试补全或迁移包',
        'first_users_hint': '去 GitHub issues/discussions、Claude Code/Copilot 讨论区和开发者社群里找首批 20 个团队',
        'crowded': True,
    },
    {
        'name': 'transcription',
        'terms': ['speech to text', 'voice', 'dictation', 'transcription', '语音', '转文字', '语音输入', '语音识别'],
        'category_label': '语音转写',
        'avoid_label': '一个通用语音输入工具',
        'default_target': '每天要开会、访谈或写长文的 Mac 知识工作者',
        'trigger': '会议、访谈或边走边记刚结束时',
        'deliverable': '一份结构化纪要、待办列表和可直接发送的草稿',
        'first_users_hint': '去写作者社区、播客/访谈从业者群和高频会议团队里约首批 20 个重度用户',
        'crowded': True,
    },
    {
        'name': 'focus_audio',
        'terms': ['white noise', 'focus app', 'meditation', '白噪音', '专注', 'focus', '音频'],
        'category_label': '专注/白噪音',
        'avoid_label': '一个白噪音或专注应用',
        'default_target': '需要长时间深度工作的远程知识工作者',
        'trigger': '准备进入 60-90 分钟深度工作前',
        'deliverable': '一套带番茄钟和专注复盘的深度工作 session',
        'first_users_hint': '去深度工作、ADHD、远程办公社区里找愿意做 7 天专注实验的首批用户',
        'crowded': True,
    },
    {
        'name': 'content_training',
        'terms': ['how i', 'best practice', 'playbook', 'training', 'course', '教程', '培训', '内容'],
        'category_label': '内容/培训',
        'avoid_label': '一个泛 AI 编程内容站或培训课',
        'default_target': '想把 AI 编程流程标准化的 3-20 人工程团队负责人',
        'trigger': '团队开始要求统一 prompt、review checklist 和交付规范时',
        'deliverable': '一份基于真实代码库的 AI 编程 playbook 与评审清单',
        'first_users_hint': '去 HN 评论区、工程管理社群和已有 AI 编程实践分享帖下定向约访 20 个团队负责人',
        'crowded': False,
    },
]

# ---------------------------------------------------------------------------
# Term lists
# ---------------------------------------------------------------------------

PHASE2_BIG_PLAYER_TERMS = {
    'apple': 'Apple',
    'ios': 'Apple',
    'macos': 'Apple',
    'google': 'Google',
    'microsoft': 'Microsoft',
    'openai': 'OpenAI',
    'anthropic': 'Anthropic',
    'claude': 'Claude',
    'github copilot': 'GitHub Copilot',
    'copilot': 'GitHub Copilot',
    'notion': 'Notion',
    'linear': 'Linear',
    'jira': 'Jira',
    'slack': 'Slack',
    'figma': 'Figma',
    'stripe': 'Stripe',
    'deepgram': 'Deepgram',
}

PHASE2_HEAVY_DELIVERY_TERMS = [
    'implementation service', 'consulting service', 'custom implementation', 'system integration',
    'enterprise onboarding', 'deployment service', 'marketplace', 'two-sided', 'hardware', 'logistics',
    '代运营', '咨询服务', '定制开发', '实施服务', '系统集成', '私有化部署', '硬件', '供应链', '双边市场'
]
PHASE2_GENERIC_ACQUISITION_TERMS = ['seo', 'product hunt', 'social media', '社交媒体', '付费广告', '广告', '联盟', 'app store', 'aso']
PHASE2_SPECIFIC_ACQUISITION_TERMS = ['评论区', '帖子', '私信', '外联', '邮件', '名单', '社群', 'issue', 'discussion', 'subreddit', 'slack', 'discord', '论坛', '微信群', '评论者', '创始人', '群', '用户访谈']
PHASE2_VAGUE_ACQUISITION_TERMS = ['cold outreach', 'outbound', 'linkedin', '朋友圈', '转介绍', 'partnership', 'bd', '销售', '社群运营', '社区运营', 'founder network']
PHASE2_SIGNAL_WEAK_TERMS = ['融资', 'funding', 'launch', 'show hn', 'how i', 'essay', 'story', '案例', '教程', 'newsletter']
PHASE2_PLATFORM_DEPENDENCY_TERMS = ['api变更', 'api 变更', '官方', '自带', '依赖单一', '单一平台', 'policy', 'policies', '平台策略']
PHASE2_GENERIC_PLAN_TERMS = ['先做mvp', '先做 MVP', '根据反馈迭代', '再迭代', '验证需求', '上线看看', '先上线', 'build mvp', 'iterate', 'launch on product hunt']
PHASE2_CONCRETE_PLAN_TERMS = ['试点', '审计', '脚本', '人工', '报价', '收取', '收费', '外联', '迁移', '报告', '清单', '访谈', '名单', 'pilot', 'audit', 'migration', 'report']
PHASE2_CONCRETE_DELIVERABLE_TERMS = ['审计', '报告', '清单', '脚本', '迁移', 'migration', 'report', 'audit', 'playbook', '摘要', '诊断', '回复建议', 'review', 'checklist', '试点', 'pilot']
PHASE2_GENERIC_WEDGE_TERMS = ['tool', 'tools', 'platform', 'assistant', 'copilot', 'workspace', 'system', '产品', '工具', '平台', '系统', '应用']
PHASE2_TRIGGER_HINTS = [
    (('refund', '退款', 'chargeback', '高风险订单'), '出现退款争议、退款滥用或高风险订单时'),
    (('failed payment', '支付失败', '扣款失败'), 'failed payment 开始堆积时'),
    (('churn', '流失'), '流失率抬头时'),
    (('support', '客服', 'ticket', '工单'), '工单积压或回复超时时'),
    (('migration', '迁移'), '准备做迁移或切换栈时'),
    (('playbook', '评审清单', '代码库'), '团队准备把 AI 编程流程落进真实代码库时'),
]
PHASE2_DELIVERABLE_HINTS = [
    (('refund', '退款', 'chargeback'), '一份退款滥用审计报告'),
    (('failed payment', '支付失败', '扣款失败'), '一份 failed payment 与流失诊断报告'),
    (('support', '客服', 'ticket', '工单'), '一份工单分流与回复建议清单'),
    (('migration', '迁移'), '一个单一框架迁移包'),
    (('playbook', '评审清单', '代码库'), '一份基于真实代码库的 AI 编程评审清单与 playbook'),
]

# ---------------------------------------------------------------------------
# Feedback file path
# ---------------------------------------------------------------------------

FEEDBACK_FILE: str = os.path.join(DATA_DIR, 'feedback.json')

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    'PHASE1_KEEP_MIN_SCORE',
    'PHASE1_FILTER_LIMIT',
    'PHASE2_WATCH_LIMIT',
    'PHASE2_KEEP_MIN_SCORE',
    'PHASE2_WATCH_MIN_SCORE',
    'FINAL_ACTION_LANDING_PAGE',
    'FINAL_ACTION_7DAY_MVP',
    'FINAL_ACTION_DROP',
    'SOURCE_QUALITY',
    'SOURCE_QUALITY_SCORE',
    'PHASE2_CATEGORY_PROFILES',
    'PHASE2_BIG_PLAYER_TERMS',
    'PHASE2_HEAVY_DELIVERY_TERMS',
    'PHASE2_GENERIC_ACQUISITION_TERMS',
    'PHASE2_SPECIFIC_ACQUISITION_TERMS',
    'PHASE2_VAGUE_ACQUISITION_TERMS',
    'PHASE2_SIGNAL_WEAK_TERMS',
    'PHASE2_PLATFORM_DEPENDENCY_TERMS',
    'PHASE2_GENERIC_PLAN_TERMS',
    'PHASE2_CONCRETE_PLAN_TERMS',
    'PHASE2_CONCRETE_DELIVERABLE_TERMS',
    'PHASE2_GENERIC_WEDGE_TERMS',
    'PHASE2_TRIGGER_HINTS',
    'PHASE2_DELIVERABLE_HINTS',
    'FEEDBACK_FILE',
]
