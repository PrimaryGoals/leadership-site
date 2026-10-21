#!/usr/bin/env python3
"""Static site generator for primarygoals.org.

    python3 build.py            # writes the finished site into ./public

Reads ./content (pages/, posts/, site.json) and copies ./static verbatim.
Python 3.8+, standard library only. Contains no credentials and makes no
network requests.

URL structure matches the old WordPress site: pages and posts live at the same
paths they had there (/about/, /theory/learning/, /<post-slug>/ ...).
Extra pages generated here: /blog/ (when the old page was empty: a list of all
posts), /site-map/ (every page and post), /404.html.
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / 'content'
STATIC = ROOT / 'static'
OUT = ROOT / 'public'

SITE = json.loads((CONTENT / 'site.json').read_text(encoding='utf-8'))
SITE_URL = SITE['url']
NAME = 'Primary Goals'
TAGLINE = 'Leadership, teams and organizational development'
CSS_VERSION = '1'

esc = html.escape


def parse_front(path):
    s = path.read_text(encoding='utf-8')
    if not s.startswith('---\n'):
        raise ValueError('missing front matter: %s' % path)
    head, body = s[4:].split('\n---\n', 1)
    return json.loads(head), body.rstrip('\n')


def load(folder):
    out = []
    for p in sorted((CONTENT / folder).glob('*.html')):
        meta, raw = parse_front(p)
        meta['raw'] = raw
        out.append(meta)
    return out


# --------------------------------------------------------------------------
# Body rendering: reproduces WordPress's wpautop()
# --------------------------------------------------------------------------

ALLBLOCKS = (r'(?:table|thead|tfoot|caption|col|colgroup|tbody|tr|td|th|div|dl|dd|dt|ul|ol|li|pre|'
             r'form|map|area|blockquote|address|math|style|p|h[1-6]|hr|fieldset|legend|section|'
             r'article|aside|hgroup|header|footer|nav|figure|figcaption|details|menu|summary)')


def wpautop(pee):
    """Port of WordPress's wpautop(): blank lines become paragraphs, single newlines become <br />."""
    if not pee.strip():
        return ''
    pee = pee.replace('\r\n', '\n').replace('\r', '\n') + '\n'
    pee = re.sub(r'<br\s*/?>\s*<br\s*/?>', '\n\n', pee)
    pee = re.sub(r'(<' + ALLBLOCKS + r'[\s/>])', r'\n\n\1', pee)
    pee = re.sub(r'(</' + ALLBLOCKS + r'>)', r'\1\n\n', pee)
    pee = re.sub(r'\n\n+', '\n\n', pee)
    chunks = [c for c in re.split(r'\n\s*\n', pee) if c != '']
    pee = ''.join('<p>' + c.strip('\n') + '</p>\n' for c in chunks)
    pee = re.sub(r'<p>\s*</p>', '', pee)
    pee = re.sub(r'<p>([^<]+)</(div|address|form)>', r'<p>\1</p></\2>', pee)
    pee = re.sub(r'<p>\s*(</?' + ALLBLOCKS + r'[^>]*>)\s*</p>', r'\1', pee)
    pee = re.sub(r'<p>(<li.+?)</p>', r'\1', pee)
    pee = re.sub(r'<p>\s*(</?' + ALLBLOCKS + r'[^>]*>)', r'\1', pee)
    pee = re.sub(r'(</?' + ALLBLOCKS + r'[^>]*>)\s*</p>', r'\1', pee)
    pee = pee.replace('<br>', '<br />').replace('<br/>', '<br />')
    pee = re.sub(r'(?<!<br />)\s*\n', '<br />\n', pee)
    pee = re.sub(r'(</?' + ALLBLOCKS + r'[^>]*>)\s*<br />', r'\1', pee)
    pee = re.sub(r'<br />(\s*</?(?:p|li|div|dl|dd|dt|th|pre|td|ul|ol)[^>]*>)', r'\1', pee)
    pee = re.sub(r'\n</p>$', '</p>', pee)
    return pee


def render_body(raw):
    s = re.sub(r'<!--\s*/?wp:.*?-->', '', raw)
    return wpautop(s)


# --------------------------------------------------------------------------
# Page shell: the same header, menu and footer on every page
# --------------------------------------------------------------------------

def nav_html(current, items=None):
    out = []
    for n in SITE['nav'] if items is None else items:
        cls = []
        if n['href'] == current:
            cls.append('current')
        if n['children']:
            cls.append('has-sub')
        sub = '<ul>%s</ul>' % nav_html(current, n['children']) if n['children'] else ''
        out.append('<li%s><a href="%s">%s</a>%s</li>' % (
            ' class="%s"' % ' '.join(cls) if cls else '', esc(n['href']), esc(n['label']), sub))
    return ''.join(out)


def document(title, path, body, description='', noindex=False):
    full = NAME if path == '/' else '%s – %s' % (title, NAME)
    return '\n'.join([
        '<!doctype html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>%s</title>' % esc(full),
        '<meta name="description" content="%s">' % esc(description or TAGLINE),
        '<meta name="robots" content="noindex,follow">' if noindex else '',
        '<link rel="canonical" href="%s%s">' % (SITE_URL, esc(path)),
        '<link rel="stylesheet" href="/assets/site.css?v=%s">' % CSS_VERSION,
        '</head>',
        '<body>',
        '<a class="skip" href="#content">Skip to content</a>',
        '<header class="top"><div class="wrap">',
        '<a class="brand" href="/" rel="home">%s</a>' % esc(NAME),
        '<nav aria-label="Primary"><ul>%s</ul></nav>' % nav_html(path),
        '</div></header>',
        body,
        '<footer class="foot"><div class="wrap"><p>© Primary Goals · '
        '<a href="/site-map/">Site map</a></p></div></footer>',
        '</body></html>',
    ])


def article(title, raw, date=''):
    when = '<p class="meta">%s</p>' % esc(date) if date else ''
    return ('<main id="content"><div class="wrap"><article><h1>%s</h1>%s'
            '<div class="prose">%s</div></article></div></main>' % (esc(title), when, render_body(raw)))


def listing(title, entries):
    lis = ''.join('<li><a href="%s">%s</a>%s</li>' % (
        esc(p), esc(t), (' <span class="meta">%s</span>' % esc(d)) if d else '') for p, t, d in entries)
    return ('<main id="content"><div class="wrap"><article><h1>%s</h1><ul class="list">%s</ul>'
            '</article></div></main>' % (esc(title), lis))


def main():
    pages, posts = load('pages'), load('posts')
    out = {}

    def add(path, content):
        if path in out:
            raise SystemExit('URL collision: %s' % path)
        out[path] = content

    ordered_posts = sorted(posts, key=lambda p: p['date'], reverse=True)
    for p in pages:
        if p['path'] == '/blog/' and not re.sub(r'<[^>]+>|\s', '', p['raw']):
            add(p['path'], document(p['title'], p['path'], listing(
                p['title'], [(q['path'], q['title'], q['date']) for q in ordered_posts])))
        else:
            add(p['path'], document(p['title'], p['path'], article(p['title'], p['raw'])))
    for p in posts:
        add(p['path'], document(p['title'], p['path'], article(p['title'], p['raw'], p['date'])))

    allp = sorted(((q['path'], q['title'], '') for q in pages + posts), key=lambda e: e[0])
    add('/site-map/', document('Site map', '/site-map/', listing('Site map', allp)))
    body = ('<main id="content"><div class="wrap"><article><h1>Page not found</h1>'
            '<div class="prose"><p>That page doesn’t exist here. Try the <a href="/">home page</a> '
            'or the <a href="/site-map/">site map</a>.</p></div></article></div></main>')
    out['/404.html'] = document('Page not found', '/404.html', body, noindex=True)

    urls = ''.join('<url><loc>%s%s</loc></url>' % (SITE_URL, esc(p)) for p in sorted(out) if p.endswith('/'))
    out['/sitemap.xml'] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>\n' % urls)
    out['/robots.txt'] = 'User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n' % SITE_URL
    out['/_headers'] = '\n'.join([
        '/*',
        '  X-Content-Type-Options: nosniff',
        '  Referrer-Policy: strict-origin-when-cross-origin',
        '  X-Frame-Options: SAMEORIGIN',
        '',
        '/wp-content/*',
        '  Cache-Control: public, max-age=31536000',
        '',
        '# Keep the temporary pages.dev addresses (previews) out of search engines',
        'https://:project.pages.dev/*',
        '  X-Robots-Tag: noindex',
        'https://:version.:project.pages.dev/*',
        '  X-Robots-Tag: noindex',
        '',
    ])
    out['/_redirects'] = '# Old WordPress addresses that moved\n/feed / 301\n/feed/ / 301\n'

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(STATIC, OUT)
    for path, content in out.items():
        target = OUT / path.lstrip('/') / 'index.html' if path.endswith('/') else OUT / path.lstrip('/')
        if target.exists():
            raise SystemExit('Refusing to overwrite a static file: %s' % path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    n_files = sum(1 for _ in OUT.rglob('*') if _.is_file())
    print('built %d pages; %d files in public/' % (len(out), n_files))


if __name__ == '__main__':
    sys.exit(main())
