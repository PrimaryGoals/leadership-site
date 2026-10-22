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
import html
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
# It follows the live site: Team Development has three groups of links under it.
NAV = [
    ('Team Development', '/', [
        ('Books & Articles', '/teams/books/', [
            ('Book Reviews', '/teams/books/'),
            ('Article Reviews & Links', '/teams/articles/'),
            ('Appreciative Inquiry', '/teams/appreciative-inquiry/'),
            ('Cross Functional Teams', '/teams/articles/cross-functional-teams/'),
            ('Sustainability', '/teams/articles/sustainability/'),
            ('Group Dynamics', '/teams/group/')]),
        ('Models & Instruments', '/teams/models/', [
            ('Models', '/teams/models/'),
            ('Instruments', '/teams/instruments/'),
            ('Diagrams', '/teams/diagrams/')]),
        ('Other', '/teams/general/', [
            ('General Topics', '/teams/general/'),
            ('Interactive Activities', '/teams/activities/'),
            ('External Links', '/teams/links/'),
            ('Leadership Quotes', '/teams/general/leadership-quotes/'),
            ('Anti-Leadership Quotes', '/teams/links/anti-leadership/')])]),
    # the live /leadership/ address redirects to this page
    ('Leadership Coaching', '/teams/diagrams/leadership-culture-structure-process/', []),
    ('Blog', '/blog/', []),
    ('Privacy', '/legal/privacy-policy/', []),
    ('About', '/about/', []),
    ('Contact', '/about/contact/', []),
]
# Videos that the export does not contain (they were added with Thrive Architect): read from the live pages.
# path -> [(heading the video follows, YouTube id, title)]
VIDEOS = {
    '/offers/brandscripts-made-simple/client-instructions/': [
        ('Using the StorySheet BrandScript Generator', '3EAmyCI_JHc', 'Client Instructions'),
        ('Sheet #1. Client Instructions', 'p0XuaZJKRWc', 'Troubleshooting Add-On Installation'),
        ('Troubleshooting', 'igRXcCyHe_0', 'Licensing Whistle for your BrandScript'),
        ('Sheet #2. Getting Your License', 'A26FklGl0Dw', 'Transformation'),
        ('Sheet #7. Success', '7JYQDRrKYtA', 'Whistle Narrative')],
    '/offers/brandscripts-made-simple/guide-instructions/': [
        ('Instructions for StoryBrand Guides', 'fmvwGn5pzzA', 'Guide Instructions'),
        ('Download: Beta Test Version 1.5.5', 'p0XuaZJKRWc', 'Troubleshooting Add-On Installation'),
        ('Troubleshooting', 'QmzOi6_hKwE', 'Adding Custom Reference info to StorySheet'),
        ('Adding Private Reference Material', 'cawmUull9Aw', 'Livestream Dashboard')],
}
# Sections that were removed from the site on purpose (pages and every link to them).
REMOVED_PREFIXES = ('/marketing/',)
DEPRECATED = re.compile(
    r'<a\s[^>]*href=["\'](?:https?://(?:www\.)?(?:leadfromself\.wpenginepowered\.com|primarygoals\.org))?'
    r'/(?:(?:bmsu|bmsu-mission|bmsucoach|business-mri|whistle|whistle-beta|schedule|login|discovery)/?'
    r'|marketing(?:/[^"\'?#]*)?)(?:[?#][^"\']*)?["\'][^>]*>'
    r'(.*?)</a>', re.S | re.I)
# Parts of the contact page that were removed on purpose: the calendar embed and the Facebook link.
IFRAME = re.compile(r'\[iframe\b[^\]]*\]')
FACEBOOK_ITEM = re.compile(r'\s*<li>\s*<a\s[^>]*facebook\.com[^>]*>.*?</a>\s*</li>', re.S | re.I)
# Membership login/logout block: only meaningful inside WordPress.
MEMBER_BLOCK = re.compile(r'\[memb_is_logged_in\].*?\[/memb_is_logged_in\]', re.S)
OLD_HOSTS =r'https?://(?:www\.)?(?:leadfromself\.wpenginepowered\.com|primarygoals\.org)'

# Shortcodes that mean the page only works inside WordPress.
DYNAMIC = re.compile(r'\[/?(?:woocommerce_\w+|lifterlms_\w+|memb_\w+|else_memb_\w+|DAP|groups_can|'
                     r'category_login|gravityform|tcb_\w+|html-sitemap)\b')
# Shortcodes that are removed from otherwise normal text.
STRIP = re.compile(r'\[/?(?:urlparam|email|thrive_2step|DAP|groups_can|memb_\w+|else_memb_\w+|'
                   r'amazon_link|tcb_\w+)\b[^\]]*\]')


def text(el, tag):
    return el.findtext(tag, namespaces=NS) or ''


def postmeta(it):
    return {text(m, 'wp:meta_key'): text(m, 'wp:meta_value') for m in it.findall('wp:postmeta', NS)}


def add_videos(body, specs):
    """Put each video right after the heading it followed on the live page (at the end if that heading is gone)."""
    for heading, vid, title in specs:
        player = ('\n<div class="video"><iframe src="https://www.youtube.com/embed/%s" title="%s" loading="lazy" '
                  'allowfullscreen></iframe></div>\n' % (vid, html.escape(title)))
        for m in re.finditer(r'<h[1-4]\b[^>]*>(.*?)</h[1-4]>', body, flags=re.S):
            if html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).replace('\xa0', ' ').strip().startswith(heading):
                body = body[:m.end()] + player + body[m.end():]
                break
        else:
            body += player
    return body


def seo_title(pm, title, sitename):
    """The <title> the live site (Rank Math) used: a custom one, or "<title> - <site name>"."""
    t = (pm.get('rank_math_title') or '').strip() or '%title% %sep% %sitename%'
    return html.unescape(t.replace('%title%', title).replace('%sep%', '-').replace('%sitename%', sitename))


def seo_description(pm, body):
    """A custom description if one was written, else the first ~160 characters of the text (as Rank Math does)."""
    d = (pm.get('rank_math_description') or '').strip()
    if d:
        return html.unescape(d)
    s = re.sub(r'<(script|style)\b.*?</\1>|<!--.*?-->', '', body, flags=re.S)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s)).replace('\xa0', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s if len(s) <= 160 else s[:160].rsplit(' ', 1)[0].rstrip(' ,;:')


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

    sitename = ch.findtext('title') or ''
    attachments = {text(it, 'wp:post_id'): re.sub(OLD_HOSTS, '', text(it, 'wp:attachment_url'))
                   for it in items if text(it, 'wp:post_type') == 'attachment'}
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
        folder = os.path.join(out_dir, sub)
        os.makedirs(folder, exist_ok=True)
        # start clean so pages that are now skipped don't linger from an earlier run
        for old in os.listdir(folder):
            if old.endswith('.html'):
                os.remove(os.path.join(folder, old))
    kept, skipped = [], []
    for it in live:
        kind = text(it, 'wp:post_type')
        slug = text(it, 'wp:post_name')
        title = it.findtext('title') or slug
        body = MEMBER_BLOCK.sub('', text(it, 'content:encoded'))
        why = None
        if text(it, 'wp:status') != 'publish':
            why = text(it, 'wp:status')
        elif text(it, 'wp:post_password'):
            why = 'password'
        elif path_of(it).startswith(REMOVED_PREFIXES):
            why = 'removed'
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
        body = IFRAME.sub('', body)
        body = FACEBOOK_ITEM.sub('', body)
        # trailing spaces / stray <br /> inside an address make the link unusable
        body = re.sub(r'(href=["\'][^"\']*?)(?:\s|<br\s*/?>)+(["\'])', r'\1\2', body)
        body = fix_links(body)
        body = add_videos(body, VIDEOS.get(path_of(it), []))
        pm = postmeta(it)
        title = html.unescape(title)
        # social-sharing image: the featured image, else the one Rank Math stored for the first image in the text
        stored = re.search(r'https?://[^"\']+?\.(?:jpe?g|png|gif|webp)', pm.get('rank_math_og_content_image', ''), re.I)
        first_img = re.search(r'<img\b[^>]*\bsrc=["\'](/[^"\']+)', body)
        image = (attachments.get(pm.get('_thumbnail_id', '')) or (re.sub(OLD_HOSTS, '', stored.group(0)) if stored else '')
                 or (first_img.group(1) if first_img else ''))
        meta = {
            'id': int(text(it, 'wp:post_id')),
            'title': title,
            'seo_title': seo_title(pm, title, sitename),
            'description': seo_description(pm, body),
            'image': image,
            'slug': slug,
            'path': path_of(it),
            'date': text(it, 'wp:post_date')[:10],
            'modified': text(it, 'wp:post_modified'),
            'published_gmt': text(it, 'wp:post_date_gmt').replace(' ', 'T') + '+00:00',
            'modified_gmt': text(it, 'wp:post_modified_gmt').replace(' ', 'T') + '+00:00',
            'type': kind,
        }
        fname = '%s-%s.html' % (meta['id'], slug or 'untitled') if kind == 'page' else (slug or str(meta['id'])) + '.html'
        with open(os.path.join(out_dir, 'pages' if kind == 'page' else 'posts', fname), 'w', encoding='utf-8') as f:
            f.write('---\n%s\n---\n%s\n' % (json.dumps(meta, ensure_ascii=False), body))
        kept.append(meta['path'])

    have = set(kept)

    def build_nav(entries):
        out = []
        for label, href, *rest in entries:
            kids = build_nav(rest[0]) if rest and rest[0] and isinstance(rest[0][0], tuple) and len(rest[0][0]) == 3 else \
                [dict(label=l, href=h, children=[]) for l, h in (rest[0] if rest else []) if h in have]
            if href in have or kids:
                out.append(dict(label=label, href=href, children=kids))
        return out

    nav = build_nav(NAV)
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
