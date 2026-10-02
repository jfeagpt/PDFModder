"""Prepare only allowlisted project files for the GitHub connector, locally."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_licenses import source_files


def main():
    entries = []
    for path, relative in source_files():
        data = path.read_bytes()
        try:
            content = data.decode('utf-8')
            if '\0' in content:
                raise ValueError('binary')
            encoding = 'utf-8'
        except (UnicodeDecodeError, ValueError):
            content = base64.b64encode(data).decode('ascii')
            encoding = 'base64'
        entries.append({'path': relative.as_posix(), 'encoding': encoding,
                        'content': content, 'bytes': len(data)})
    target = ROOT / 'output/github-source-payload.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(entries, ensure_ascii=True), encoding='utf-8')
    print(json.dumps({'files': len(entries), 'binary': sum(e['encoding'] == 'base64' for e in entries),
                      'bytes': sum(e['bytes'] for e in entries)}))


if __name__ == '__main__':
    main()
