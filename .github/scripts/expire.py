#!/usr/bin/env python3
"""刪除過期分享並把 repo 歷史壓成 1 個 commit。

用法：expire.py [--repo .] [--now ISO時間] [--no-push]
exit：0 成功／1 閉環檢查不符
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

TTL = dt.timedelta(hours=72)


def parse_iso(text):
    t = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def expiry_of(folder):
    """回傳到期時間；判斷不了回 None。"""
    try:
        return parse_iso(json.loads((folder / '.share.json').read_text())['expires_utc'])
    except Exception:
        pass
    m = re.match(r'(\d{8}-\d{6})-', folder.name)
    if m:
        try:
            created = dt.datetime.strptime(m.group(1), '%Y%m%d-%H%M%S').replace(tzinfo=dt.timezone.utc)
            return created + TTL
        except ValueError:
            pass
    return None


def is_expired(entry, now):
    exp = expiry_of(entry)
    return exp is None or exp <= now


def remove_expired(repo, now):
    removed = []
    base = repo / 'p'
    if not base.is_dir():
        return removed
    for entry in sorted(base.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
            removed.append(entry.name)
        elif is_expired(entry, now):
            shutil.rmtree(entry)
            removed.append(entry.name)
    return removed


def git(repo, *args):
    cmd = ['git', '-C', str(repo), '-c', 'user.name=share-preview-bot',
           '-c', 'user.email=share-preview-bot@users.noreply.github.com', *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f'git {args[0]} 失敗：{res.stderr.strip()[:300]}')
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='.')
    ap.add_argument('--now')
    ap.add_argument('--no-push', action='store_true')
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    now = parse_iso(args.now) if args.now else dt.datetime.now(dt.timezone.utc)

    for name in remove_expired(repo, now):
        print(f'removed p/{name}')

    git(repo, 'checkout', '--orphan', 'snapshot-tmp')
    git(repo, 'add', '-A')
    git(repo, 'commit', '--allow-empty', '-m', f'snapshot {now.strftime("%Y-%m-%dT%H:%M:%SZ")}')
    git(repo, 'branch', '-M', 'main')

    problems = []
    if args.no_push:
        label = 'HEAD'
    else:
        git(repo, 'push', '--force', 'origin', 'HEAD:main')
        git(repo, 'fetch', 'origin')
        label = 'origin/main'
    count = git(repo, 'rev-list', '--count', label).stdout.strip()
    if count != '1':
        problems.append(f'{label} 應只有 1 個 commit，實際 {count}')
    base = repo / 'p'
    if base.is_dir():
        left = [e.name for e in base.iterdir() if is_expired(e, now)]
        if left:
            problems.append(f'p/ 仍有過期項目：{left}')
    if problems:
        for item in problems:
            print(f'FAIL: {item}', file=sys.stderr)
        return 1
    print('EXPIRE_OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
