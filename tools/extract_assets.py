#!/usr/bin/env python3
"""One-time extraction of the uploads the static site actually uses from the WordPress archive.

    python3 tools/extract_assets.py /path/to/site-archive.zip content/ static/

Scans every file in content/ for /wp-content/uploads/..., /Diagrams/..., /Readings/...
(and /Papers, /Presentations) references and copies
just those files from the archive, keeping the original WordPress paths so
existing links keep working. Nothing else from the archive (PHP, plugins,
config files, unreferenced files) is copied. Standard library only.
"""
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote

REF = re.compile(r'/((?:wp-content/uploads|wp-content/gallery|Diagrams|Readings|Papers|Presentations)/'
                 r'[^"\'\s<>)?#]+)')


def main(zip_path, content_dir, out_dir):
    # build.py's default social-sharing image, which no page links to directly
    wanted = {'wp-content/uploads/2024/09/social-share.jpg', 'wp-content/uploads/2024/09/logo-square.jpg'}
    for f in Path(content_dir).rglob('*'):
        if f.suffix not in ('.html', '.json'):
            continue
        wanted.update(unquote(m) for m in REF.findall(f.read_text(encoding='utf-8')))
    found = set()
    with zipfile.ZipFile(zip_path) as z:
        names = {i.filename: i for i in z.infolist() if not i.is_dir()}
        for name in sorted(wanted):
            info = names.get(name)
            if info is None or '..' in name.split('/'):
                continue
            target = Path(out_dir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, 'wb') as dst:
                dst.write(src.read())
            found.add(name)
    print('referenced: %d, copied: %d' % (len(wanted), len(found)))
    for name in sorted(wanted - found):
        print('missing from archive: /' + name)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
