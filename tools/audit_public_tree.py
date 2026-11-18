"""Check the staged release tree for ROMs, private data, and broken local links."""
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    files = [name for name in files if name]
    allowed = {'.md', '.txt', '.json', '.py', '.ps1', '.terms', '.png'}
    for name in files:
        path = ROOT / name
        if path.suffix not in allowed and name not in {'.gitignore','.gitattributes','LICENSE'}:
            raise AssertionError('Unapproved public file: ' + name)
        if path.stat().st_size > 2_000_000:
            raise AssertionError('Unexpected large public file: ' + name)
        if path.suffix == '.md' and not name.startswith('licenses/'):
            text = path.read_text('utf-8')
            if 'C:\\CODEX' in text or 'C:\\Users' in text:
                raise AssertionError('Private workspace path in ' + name)
            for link in re.findall(r'\]\(([^)]+)\)', text):
                if not re.match(r'^\w+://', link) and not link.startswith('#'):
                    target = (path.parent / link.split('#')[0]).resolve()
                    if not target.is_relative_to(ROOT) or not target.exists():
                        raise AssertionError('Broken local link: ' + name + ': ' + link)
    first = (ROOT/'README.md').read_text('utf-8').splitlines()[0]
    assert first.startswith('![') and 'docs/screenshots/01-title.png' in first
    manifest = json.loads((ROOT/'patcher/manifest.json').read_text('utf-8'))
    proof = json.loads((ROOT/'docs/verification/patcher-test.json').read_text('utf-8'))
    assert proof['passed'] and proof['output_sha256'] == manifest['target']['sha256']
    assert proof['output_size'] == manifest['target']['size']
    print(f'Public tree: {len(files)} approved files; local links and title-first README passed')

if __name__ == '__main__':
    main()
