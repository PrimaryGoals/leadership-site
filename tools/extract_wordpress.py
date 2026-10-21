#!/usr/bin/env python3
"""One-time importer: WordPress export (WXR .xml) -> plain content files.

    python3 tools/extract_wordpress.py /path/to/export.xml content/

Writes every published page and post as an HTML file with a JSON front matter
block (content/pages/<n>-<slug>.html, content/posts/<slug>.html) plus
site.json (title, tagline, menu) and a report of what was skipped.
Skipped on purpose: drafts, private and password-protected items, and pages
that only make sense on WordPress (shop, checkout, membership/login, forms).
Author e-mail addresses and the like are never copied. Do not commit the raw
export file. Standard library only.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

NS = {
    'wp': 'http://wordpress.org/export/1.2/',
    'content': 'http://purl.org/rss/1.0/modules/content/',
}
# The export has several overlapping, partly retired WordPress menus, so the top menu is set here.
NAV = [('Coaching', '/coaching/'), ('Theory', '/theory/'), ('Blog', '/blog/'), ('About', '/about/'),
       ('Contact', '/about/contact/')]
DEPRECATED = re.compile(
    r'<a\s[^>]*href=["\'](?:https?://(?:www\.)?(?:leadfromself\.wpenginepowered\.com|primarygoals\.org))?'
    r'/(?:bmsu|bmsu-mission|bmsucoach|business-mri|whistle|whistle-beta|schedule|login|discovery)/?(?:[?#][^"\']*)?["\'][^>]*>'
    r'(.*?)</a>', re.S | re.I)
OLD_HOSTS =r'https?://(?:www\.)?(?:leadfromself\.wpenginepowered\.com|primarygoals\.org)'

# Shortcodes that mean the page only works inside WordPress.
DYNAMIC = re.compile(r'\[/?(?:woocommerce_\w+|lifterlms_\w+|memb_\w+|else_memb_\w+|DAP|groups_can|'
                     r'category_login|gravityform|tcb_\w+|html-sitemap)\b')
# Shortcodes that are removed from otherwise normal text.
STRIP = re.compile(r'\[/?(?:urlparam|email|thrive_2step|DAP|groups_can|memb_\w+|else_memb_\w+|'
                   r'amazon_link|tcb_\w+)\b[^\]]*\]')


def text(el, tag):
    return el.findtext(tag, namespaces=NS) or ''


def path_of(it):
    return urlparse(it.findtext('link') or '').path or '/'


def to_table(rows):
    out = ['<table>']
    for i, row in enumerate(rows):
        tag = 'th' if i == 0 else 'td'
        out.append('<tr>%s</tr>' % ''.join('<%s>%s</%s>' % (tag, c, tag) for c in row))
    out.append('</table>')
    return ''.join(out)


def main(xml_path, out_dir):
    raw = open(xml_path, 'rb').read()
    # the export contains a stray control character that is illegal in XML
    raw = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b'', raw)
    ch = ET.fromstring(raw).find('channel')
    items = ch.findall('item')

    # TablePress: [table id=N /] uses its own numbering (stored in an option); the
    # posts are in id order, so number them 1..n by post id.
    tp_posts = sorted((it for it in items if text(it, 'wp:post_type') == 'tablepress_table'),
                      key=lambda it: int(text(it, 'wp:post_id')))
    tp_by_order = [json.loads(text(it, 'content:encoded')) for it in tp_posts
                   if text(it, 'content:encoded').startswith('[')]

    live = [it for it in items if text(it, 'wp:post_type') in ('post', 'page')]
    id_to_path = {text(it, 'wp:post_id'): path_of(it) for it in live if text(it, 'wp:status') == 'publish'}

    def fix_links(body):
        body = re.sub(OLD_HOSTS + r'/\?(?:page_id|p)=(\d+)',
                      lambda m: id_to_path.get(m.group(1), '/'), body)
        body = re.sub(r'(\s(?:href|src)=)(["\'])' + OLD_HOSTS + r'(/[^"\']*)?\2',
                      lambda m: '%s%s%s%s' % (m.group(1), m.group(2), m.group(3) or '/', m.group(2)), body)
        # deprecated destinations: keep the link text, drop the link
        body = DEPRECATED.sub(r'\1', body)
        # an older site layout kept these sections under /leadership/
        return re.sub(r'(\s(?:href|src)=["\'])/leadership/(?=(?:reduce-breakdowns|theory|conflict)/)', r'\1/', body)

    for sub in ('pages', 'posts'):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    kept, skipped = [], []
    for it in live:
        kind = text(it, 'wp:post_type')
        slug = text(it, 'wp:post_name')
        title = it.findtext('title') or slug
        body = text(it, 'content:encoded')
        why = None
        if text(it, 'wp:status') != 'publish':
            why = text(it, 'wp:status')
        elif text(it, 'wp:post_password'):
            why = 'password'
        elif DYNAMIC.search(body):
            why = 'wordpress-only shortcode'
        if why:
            skipped.append((why, kind, path_of(it), title))
            continue
        body = re.sub(r'<!--\s*/?wp:.*?-->', '', body, flags=re.S)
        body = re.sub(r'<!--\[if.*?<!\[endif\]-->', '', body, flags=re.S)
        body = re.sub(r'\[table id=(\d+) */?\]',
                      lambda m: to_table(tp_by_order[int(m.group(1)) - 1])
                      if 0 < int(m.group(1)) <= len(tp_by_order) else '', body)
        body = STRIP.sub('', body)
        body = fix_links(body)
        meta = {
            'id': int(text(it, 'wp:post_id')),
            'title': title,
            'slug': slug,
            'path': path_of(it),
            'date': text(it, 'wp:post_date')[:10],
            'modified': text(it, 'wp:post_modified'),
            'type': kind,
        }
        fname = '%s-%s.html' % (meta['id'], slug or 'untitled') if kind == 'page' else (slug or str(meta['id'])) + '.html'
        with open(os.path.join(out_dir, 'pages' if kind == 'page' else 'posts', fname), 'w', encoding='utf-8') as f:
            f.write('---\n%s\n---\n%s\n' % (json.dumps(meta, ensure_ascii=False), body))
        kept.append(meta['path'])

    nav = [dict(label=l, href=h, children=[]) for l, h in NAV if h in set(kept)]
    site = {
        'title': ch.findtext('title') or '',
        'description': ch.findtext('description') or '',
        'url': (ch.findtext('link') or '').rstrip('/'),
        'nav': nav,
    }
    with open(os.path.join(out_dir, 'site.json'), 'w', encoding='utf-8') as f:
        json.dump(site, f, indent=1, ensure_ascii=False)

    with open(os.path.join(out_dir, 'skipped.txt'), 'w', encoding='utf-8') as f:
        for why, kind, p, title in sorted(skipped):
            f.write('%s\t%s\t%s\t%s\n' % (why, kind, p, title))
    print('kept: %d' % len(kept))
    print('skipped: %d (see %s/skipped.txt)' % (len(skipped), out_dir))
    print('menu items: %d' % len(nav))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
