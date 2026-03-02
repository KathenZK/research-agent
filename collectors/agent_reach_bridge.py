#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from .reddit import RedditCollector

class AgentReachBridge:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.health_file = self.data_dir / 'agent_reach_health.json'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.health_file.exists():
            try:
                return json.loads(self.health_file.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {'updated_at': None, 'doctor_raw': '', 'platforms': {
            'x': {'healthy': False, 'failures': 0, 'cooldown_until': None, 'last_error': ''},
            'youtube': {'healthy': False, 'failures': 0, 'cooldown_until': None, 'last_error': ''},
            'reddit': {'healthy': False, 'failures': 0, 'cooldown_until': None, 'last_error': ''},
        }}

    def _save_state(self):
        self.state['updated_at'] = datetime.now().isoformat()
        self.health_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')

    def _run(self, cmd: List[str], timeout: int = 30) -> str:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or 'command failed').strip())
        return (p.stdout or '').strip()

    def check_health(self) -> Dict[str, bool]:
        health = {'x': False, 'youtube': False, 'reddit': False}
        try:
            self.state['doctor_raw'] = self._run(['agent-reach', 'doctor'], timeout=45)
        except Exception as e:
            self.state['doctor_raw'] = f'doctor failed: {e}'

        try:
            self._run(['xreach', '--help'], timeout=10)
            health['x'] = True
        except Exception:
            pass
        try:
            self._run(['yt-dlp', '--version'], timeout=10)
            health['youtube'] = True
        except Exception:
            pass
        health['reddit'] = True

        for k, v in health.items():
            self.state['platforms'][k]['healthy'] = v
        self._save_state()
        return health

    def _in_cooldown(self, platform: str) -> bool:
        t = self.state['platforms'][platform].get('cooldown_until')
        if not t:
            return False
        try:
            return datetime.now() < datetime.fromisoformat(t)
        except Exception:
            return False

    def _mark_success(self, platform: str):
        p = self.state['platforms'][platform]
        p['failures'] = 0
        p['last_error'] = ''
        p['cooldown_until'] = None

    def _mark_failure(self, platform: str, err: str):
        p = self.state['platforms'][platform]
        p['failures'] = int(p.get('failures', 0)) + 1
        p['last_error'] = err[:300]
        if p['failures'] >= 3:
            p['cooldown_until'] = (datetime.now() + timedelta(hours=24)).isoformat()

    def _mk_id(self, platform: str, title: str, url: str) -> str:
        raw = f'{platform}|{title}|{url}'.encode('utf-8', errors='ignore')
        return f"ar_{platform}_{hashlib.sha1(raw).hexdigest()[:16]}"

    def fetch_x(self, limit: int = 10, query: str = 'AI agent saas automation indie') -> List[Dict[str, Any]]:
        if self._in_cooldown('x'):
            return []
        try:
            out = self._run(['xreach', 'search', query, '--json'], timeout=45)
            data = json.loads(out)
            candidates = data if isinstance(data, list) else next((data.get(k) for k in ('results','tweets','data','items') if isinstance(data.get(k), list)), [])
            items: List[Dict[str, Any]] = []
            for r in candidates[:limit]:
                title = r.get('text') or r.get('content') or r.get('full_text') or ''
                if not title:
                    continue
                url = r.get('url') or r.get('tweet_url') or ''
                if not url:
                    tid = r.get('id') or r.get('tweet_id')
                    user = (r.get('author') or {}).get('username') or r.get('username') or 'i'
                    if tid:
                        url = f'https://x.com/{user}/status/{tid}'
                score = int(r.get('like_count',0) or 0) + int(r.get('retweet_count',0) or 0)
                items.append({'id': self._mk_id('x', title[:120], url), 'title': title[:200], 'source': 'x', 'url': url,
                              'score': score, 'description': title[:500], 'author': r.get('username') or ((r.get('author') or {}).get('username','')), 'created_at': r.get('created_at','')})
            self._mark_success('x'); self._save_state(); return items
        except Exception as e:
            self._mark_failure('x', str(e)); self._save_state(); return []

    def fetch_youtube(self, limit: int = 10, query: str = 'AI SaaS automation product') -> List[Dict[str, Any]]:
        if self._in_cooldown('youtube'):
            return []
        try:
            out = self._run(['yt-dlp', f'ytsearch{limit}:{query}', '--dump-single-json', '--no-warnings', '--flat-playlist'], timeout=60)
            data = json.loads(out)
            entries = data.get('entries', []) if isinstance(data, dict) else []
            items: List[Dict[str, Any]] = []
            for r in entries[:limit]:
                title = r.get('title') or ''
                if not title:
                    continue
                vid = r.get('id', '')
                url = r.get('url')
                if vid and (not url or not str(url).startswith('http')):
                    url = f'https://www.youtube.com/watch?v={vid}'
                items.append({'id': self._mk_id('youtube', title[:120], url or ''), 'title': title[:200], 'source': 'youtube', 'url': url or '',
                              'score': int(r.get('view_count',0) or 0), 'description': (r.get('description') or '')[:500], 'author': r.get('channel',''), 'created_at': r.get('upload_date','')})
            self._mark_success('youtube'); self._save_state(); return items
        except Exception as e:
            self._mark_failure('youtube', str(e)); self._save_state(); return []

    def fetch_reddit(self, limit: int = 10) -> List[Dict[str, Any]]:
        if self._in_cooldown('reddit'):
            return []
        try:
            items = RedditCollector().fetch(limit=limit)
            self._mark_success('reddit'); self._save_state(); return items
        except Exception as e:
            self._mark_failure('reddit', str(e)); self._save_state(); return []
