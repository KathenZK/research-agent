#!/usr/bin/env python3
"""Feishu integration: credential resolution, doc sync, and direct messaging via OpenClaw CLI."""

import os
import json
import re
import subprocess
import tempfile
import shutil
from datetime import datetime
from typing import List, Optional

from config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID, FEISHU_INDEX_DOC_TOKEN, FEISHU_DOC_SYNC_ENABLED, DATA_DIR
from models.opportunity import Opportunity


def _extract_real_feishu_doc_url(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r'https://(?:[\w-]+\.)?feishu\.cn/docx/[A-Za-z0-9]+', text)
    return m.group(0) if m else None


def _looks_like_placeholder(value: str) -> bool:
    v = (value or '').strip().lower()
    return not v or v in {'cli_xxx', 'xxx', 'ou_xxx', 'user_xxx', 'open_id_xxx', 'placeholder'}


def _resolve_feishu_credentials() -> tuple[Optional[str], Optional[str]]:
    app_id = FEISHU_APP_ID
    app_secret = FEISHU_APP_SECRET
    if not _looks_like_placeholder(app_id) and not _looks_like_placeholder(app_secret):
        return app_id, app_secret

    try:
        cfg_path = os.path.expanduser('~/.openclaw/openclaw.json')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        acct = (((cfg.get('channels') or {}).get('feishu') or {}).get('accounts') or {}).get('default') or {}
        app_id = acct.get('appId') or app_id
        app_secret = acct.get('appSecret') or app_secret
    except Exception:
        pass
    return app_id, app_secret


def _sanitize_secret_text(text: str, secrets: List[str]) -> str:
    sanitized = text or ''
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, '***')
    sanitized = re.sub(r'("app_id":"?)[^",\s]+', r'\1***', sanitized)
    sanitized = re.sub(r'("app_secret":"?)[^",\s]+', r'\1***', sanitized)
    return sanitized


def _resolve_feishu_runtime() -> tuple[Optional[str], Optional[str], Optional[str]]:
    node_candidates = []
    detected_node = shutil.which('node')
    if detected_node:
        node_candidates.append(detected_node)
    node_candidates.extend(['/opt/homebrew/bin/node', '/usr/local/bin/node'])

    node_bin = next((path for path in node_candidates if path and os.path.exists(path)), None)
    if not node_bin:
        return None, None, 'node runtime not found; install Node.js or add node to PATH'

    roots: List[str] = []
    existing_node_path = os.environ.get('NODE_PATH', '')
    if existing_node_path:
        roots.extend([p.strip() for p in existing_node_path.split(os.pathsep) if p.strip()])

    openclaw_bin = shutil.which('openclaw')
    if openclaw_bin:
        package_root = os.path.dirname(os.path.realpath(openclaw_bin))
        roots.append(os.path.join(package_root, 'node_modules'))

    roots.extend([
        '/opt/homebrew/lib/node_modules/openclaw/node_modules',
        '/usr/local/lib/node_modules/openclaw/node_modules',
    ])

    checked = []
    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        checked.append(root)
        if os.path.exists(os.path.join(root, '@larksuiteoapi', 'node-sdk')):
            return node_bin, root, None

    checked_text = ', '.join(checked) if checked else '(none)'
    return node_bin, None, f'@larksuiteoapi/node-sdk not found; checked NODE_PATH candidates: {checked_text}'


def _feishu_sync_blocker_message(text: str) -> Optional[str]:
    normalized = (text or '').lower()
    if not normalized:
        return None
    if 'node runtime not found' in normalized:
        return 'node runtime not found; install Node.js or add node to PATH'
    if '@larksuiteoapi/node-sdk not found' in text:
        return text.strip()
    if 'feishu_app_id / feishu_app_secret not configured' in normalized:
        return 'FEISHU_APP_ID / FEISHU_APP_SECRET not configured'
    if 'connect eperm 127.0.0.1:7897' in normalized:
        return 'outbound Feishu API access is blocked by the current proxy/network sandbox (cannot connect to 127.0.0.1:7897)'
    if 'getaddrinfo enotfound open.feishu.cn' in normalized or 'enotfound open.feishu.cn' in normalized:
        return 'outbound DNS/network access to open.feishu.cn is unavailable in the current environment'
    if any(token in normalized for token in ['econnrefused', 'etimedout', 'network error', 'socket hang up']) and 'feishu' in normalized:
        return 'outbound network access to Feishu API is unavailable in the current environment'
    return None


def sync_report_to_feishu(md_filename: str = 'latest_phase1.md', title: Optional[str] = None) -> Optional[str]:
    """将指定 markdown 报告同步到 Feishu Doc，并返回可验证的真实 docx URL。"""
    if not FEISHU_DOC_SYNC_ENABLED:
        print("Feishu doc sync disabled, skipping")
        return None
    app_id, app_secret = _resolve_feishu_credentials()
    if _looks_like_placeholder(app_id) or _looks_like_placeholder(app_secret):
        print("Feishu doc sync blocked: FEISHU_APP_ID / FEISHU_APP_SECRET not configured")
        return None

    md_path = os.path.join(DATA_DIR, md_filename)
    if not os.path.exists(md_path):
        print(f"{md_filename} not found, skipping Feishu doc sync")
        return None

    title = title or f"Solo Venture Screener-{datetime.now().strftime('%Y-%m-%d')}"
    node_bin, node_path, runtime_error = _resolve_feishu_runtime()
    if runtime_error:
        print(f"Feishu doc sync blocked: {runtime_error}")
        return None

    node_script = r'''
const fs = require('fs');
const os = require('os');
const path = require('path');
const Lark = require('@larksuiteoapi/node-sdk');

const appId = process.env.FEISHU_APP_ID || '';
const appSecret = process.env.FEISHU_APP_SECRET || '';
const indexToken = (process.env.FEISHU_INDEX_DOC_TOKEN || '').trim();
const title = process.env.FEISHU_DOC_TITLE || '机会洞察';
const mdPath = process.env.FEISHU_MD_PATH;

const client = new Lark.Client({
  appId,
  appSecret,
  appType: Lark.AppType.SelfBuild,
  domain: Lark.Domain.Feishu,
});

function cleanBlocksForDescendant(blocks) {
  return blocks.map((block) => {
    const { parent_id, ...cleanBlock } = block;
    if (cleanBlock.block_type === 32 && typeof cleanBlock.children === 'string') {
      cleanBlock.children = [cleanBlock.children];
    }
    if (cleanBlock.block_type === 31 && cleanBlock.table) {
      const prop = cleanBlock.table.property || {};
      cleanBlock.table = { property: { row_size: prop.row_size, column_size: prop.column_size, ...(prop.column_width ? {column_width: prop.column_width} : {}) } };
    }
    return cleanBlock;
  });
}

async function convertMarkdown(markdown) {
  const res = await client.docx.document.convert({ data: { content_type: 'markdown', content: markdown } });
  if (res.code !== 0) throw new Error('convert failed: ' + res.msg);
  return { blocks: res.data?.blocks || [], firstLevelBlockIds: res.data?.first_level_block_ids || [] };
}

async function clearDocumentContent(docToken) {
  const existing = await client.docx.documentBlock.list({ path: { document_id: docToken } });
  if (existing.code !== 0) throw new Error(existing.msg);
  const childIds = (existing.data?.items || []).filter(b => b.parent_id === docToken && b.block_type !== 1).map(b => b.block_id);
  if (childIds.length > 0) {
    const del = await client.docx.documentBlockChildren.batchDelete({ path: { document_id: docToken, block_id: docToken }, data: { start_index: 0, end_index: childIds.length } });
    if (del.code !== 0) throw new Error(del.msg);
  }
}

async function writeMarkdown(docToken, markdown) {
  await clearDocumentContent(docToken);
  const { blocks, firstLevelBlockIds } = await convertMarkdown(markdown);
  if (!blocks.length) return;
  const res = await client.docx.documentBlockDescendant.create({
    path: { document_id: docToken, block_id: docToken },
    data: { children_id: firstLevelBlockIds, descendants: cleanBlocksForDescendant(blocks), index: -1 }
  });
  if (res.code !== 0) throw new Error('descendant create failed: ' + res.msg + ' (code ' + res.code + ')');
}

async function listAllBlocks(docToken) {
  const res = await client.docx.documentBlock.list({ path: { document_id: docToken } });
  if (res.code !== 0) throw new Error(res.msg);
  return res.data?.items || [];
}

function headingLevel(type) {
  return ({3:1,4:2,5:3})[type] || null;
}

async function insertUnderDocList(docToken, lineMarkdown) {
  const blocks = await listAllBlocks(docToken);
  const heading = blocks.find(b => {
    const elems = b.text?.elements || [];
    const text = elems.map(e => e?.text_run?.content || '').join('');
    return text.trim() === '文档列表';
  });
  if (!heading) throw new Error('未找到"文档列表"区块');
  const parentId = heading.parent_id || docToken;
  const childrenRes = await client.docx.documentBlockChildren.get({ path: { document_id: docToken, block_id: parentId } });
  if (childrenRes.code !== 0) throw new Error(childrenRes.msg);
  const siblings = childrenRes.data?.items || [];
  const hIdx = siblings.findIndex(s => s.block_id === heading.block_id);
  if (hIdx < 0) throw new Error('未找到"文档列表"区块在父节点中的位置');
  const insertIndex = hIdx + 1;
  const { blocks: newBlocks, firstLevelBlockIds } = await convertMarkdown(lineMarkdown);
  const res = await client.docx.documentBlockDescendant.create({
    path: { document_id: docToken, block_id: parentId },
    data: { children_id: firstLevelBlockIds, descendants: cleanBlocksForDescendant(newBlocks), index: insertIndex }
  });
  if (res.code !== 0) throw new Error('index update failed: ' + res.msg + ' (code ' + res.code + ')');
}

(async () => {
  const out = { created: false, write_ok: false, index_update_ok: false, doc_url: '', title, error: '', warning: '' };
  try {
    const markdown = fs.readFileSync(mdPath, 'utf8');
    const created = await client.docx.document.create({ data: { title } });
    if (created.code !== 0) throw new Error('create failed: ' + created.msg);
    const docToken = created.data?.document?.document_id;
    if (!docToken) throw new Error('create failed: missing document_id');
    const docUrl = `https://feishu.cn/docx/${docToken}`;
    if (!/^https:\/\/(?:[\w-]+\.)?feishu\.cn\/docx\/[A-Za-z0-9]+$/.test(docUrl)) {
      throw new Error('returned doc URL is not a real Feishu docx URL');
    }
    out.created = true;
    out.doc_url = docUrl;

    await writeMarkdown(docToken, markdown);
    out.write_ok = true;

    if (indexToken) {
      try {
        const line = `- ${new Date().toISOString().slice(0,10)}: [${title}](${docUrl})`;
        await insertUnderDocList(indexToken, line);
        out.index_update_ok = true;
      } catch (err) {
        out.warning = err && err.message ? err.message : String(err);
      }
    }

    console.log(JSON.stringify(out));
  } catch (err) {
    out.error = err && err.message ? err.message : String(err);
    console.log(JSON.stringify(out));
    process.exitCode = 1;
  }
})();
'''

    script_path = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(node_script)
            script_path = f.name

        env = os.environ.copy()
        env.update({
            'FEISHU_APP_ID': app_id,
            'FEISHU_APP_SECRET': app_secret,
            'FEISHU_INDEX_DOC_TOKEN': FEISHU_INDEX_DOC_TOKEN,
            'FEISHU_DOC_TITLE': title,
            'FEISHU_MD_PATH': md_path,
        })

        env['NODE_PATH'] = f"{node_path}:{env.get('NODE_PATH', '')}" if env.get('NODE_PATH') else node_path
        result = subprocess.run(
            [node_bin, script_path],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        out = (result.stdout or '').strip() or (result.stderr or '').strip()
        out = _sanitize_secret_text(out, [app_id or '', app_secret or ''])
        url = _extract_real_feishu_doc_url(out)
        if result.returncode == 0 and url:
            print(f'Feishu daily doc: {url}')
            return url
        blocker = _feishu_sync_blocker_message(out)
        if blocker:
            print(f'Feishu doc sync blocked: {blocker}')
            return None
        raise RuntimeError(out or 'unknown feishu doc sync error')
    except Exception as e:
        err_text = _sanitize_secret_text(str(e), [app_id or '', app_secret or ''])
        blocker = _feishu_sync_blocker_message(err_text)
        if blocker:
            print(f'Feishu doc sync blocked: {blocker}')
        else:
            print(f'Feishu doc sync failed: {err_text}')
        return None
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def sync_top10_report_to_feishu() -> Optional[str]:
    """兼容旧调用。"""
    return sync_report_to_feishu(md_filename='latest_top10.md', title=f"机会洞察-{datetime.now().strftime('%Y-%m-%d')}")


def send_to_feishu(opportunities: List[Opportunity]):
    """发送到飞书（通过 OpenClaw CLI）

    修复点：某些环境下 openclaw 会输出 config warnings，
    但消息实际已发送。这里用"返回码 + 输出特征"双判定，避免误报失败。
    """
    if not FEISHU_USER_ID:
        print("FEISHU_USER_ID not configured, skipping Feishu notification")
        return
    if FEISHU_USER_ID.strip().lower() in {"ou_xxx", "user_xxx", "open_id_xxx", "placeholder"}:
        print("FEISHU_USER_ID is placeholder, skipping direct Feishu notification")
        return

    def _looks_delivered(stdout: str, stderr: str) -> bool:
        text = f"{stdout}\n{stderr}".lower()
        success_signals = [
            '"messageid"',
            '"chatid"',
            ' via ',
            'result',
            'sent',
            'delivered',
        ]
        return any(sig in text for sig in success_signals)

    try:
        import subprocess

        sent = 0
        failed = 0

        for opp in opportunities[:10]:
            msg = opp.to_message()
            cmd = [
                "openclaw", "message", "send",
                "--channel", "feishu",
                "--target", f"user:{FEISHU_USER_ID}",
                "--message", msg,
                "--silent"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            delivered = (result.returncode == 0) or _looks_delivered(result.stdout, result.stderr)

            if delivered:
                sent += 1
                if result.returncode != 0:
                    print(f"✅ Sent to Feishu (with warnings): {opp.title[:50]}...")
                else:
                    print(f"✅ Sent to Feishu: {opp.title[:50]}...")
            else:
                failed += 1
                err = (result.stderr or result.stdout or '').strip().replace('\n', ' ')
                print(f"⚠️  Send failed: {err[:160]}")

        print(f"✅ Feishu delivery summary: sent={sent}, failed={failed}, total={min(10, len(opportunities))}")

    except Exception as e:
        print(f"Error sending to Feishu: {e}")
