#!/usr/bin/env python3
"""Checks public/: every internal link, image and stylesheet points at a file that exists.

    python3 tools/check_site.py

Exits with status 1 and lists the problems if anything is broken. Standard library only.
"""
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

PUBLIC = Path(__file__).resolve().parent.parent / 'public'
ATTR = re.compile(r'\b(?:href|src)=["\']([^"\']+)["\']', re.I)


def resolves(path):
    p = unquote(path).lstrip('/')
    target = PUBLIC / p
    return target.is_file() or (target / 'index.html').is_file()


def internal(url):
    if not url or url.startswith(('#', 'mailto:', 'tel:', 'data:', 'javascript:')):
        return None
    u = urlparse(url)
    if u.scheme or u.netloc:
        return None
    return u.path or None


def main():
    bad, pages = [], 0
    redirects = {l.split()[0] for l in (PUBLIC / '_redirects').read_text().splitlines()
                 if l.strip() and not l.startswith('#')}
    for f in sorted(PUBLIC.rglob('*.html')):
        pages += 1
        s = f.read_text(encoding='utf-8')
        for url in ATTR.findall(s):
            p = internal(url)
            if p and p.startswith('/') and not resolves(p) and p not in redirects:
                bad.append('%s -> %s' % (f.relative_to(PUBLIC), url))
    # Only our own stylesheet: the OptimizePress CSS names many images for features these pages don't use.
    for f in sorted((PUBLIC / 'assets').glob('*.css')):
        s = f.read_text(encoding='utf-8', errors='replace')
        for url in re.findall(r'url\(["\']?([^)"\']+)', s):
            p = internal(url)
            if p and not (f.parent / p).resolve().is_file() and not resolves(p):
                bad.append('%s -> %s' % (f.relative_to(PUBLIC), url))
    print('checked %d html pages' % pages)
    if bad:
        print('PROBLEMS (%d):' % len(bad))
        print('\n'.join(sorted(set(bad))))
        return 1
    print('no broken internal links')
    return 0


if __name__ == '__main__':
    sys.exit(main())
