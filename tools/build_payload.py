"""Build the v0.8 raw track-5 delta from already extracted, verified discs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'patcher'))
from patcher import APP_ID, VERSION, read_gdi, sha256

SOURCE_SHA = '9ef09d65231aa437fa3d47b421c426d1cfde446d7e1d2edcdae6975d41b2a019'
TARGET_SHA = '8544f155b0cbc4c11d97102ce73baed059589fbcb3e29b8e736d002d48e8011d'
CHDMAN_SHA = '58d5f13b14a07d0d65f05fbaa5d78f62e85a0e98c6f4c89e423e44998b3ddff8'
XDELTA_SHA = '2081fb24a7b8a89d068b58e7d9353647d5fc1512a68bb6a37f71fc60ca84d943'

def describe(path, name=None):
    return dict(file=name or path.name, size=path.stat().st_size, sha256=sha256(path))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ['source-chd', 'target-chd', 'source-gdi', 'target-gdi', 'chdman', 'xdelta']:
        parser.add_argument('--' + arg, type=Path, required=True)
    args = parser.parse_args()
    payload = ROOT / 'payload'
    payload.mkdir(exist_ok=True)
    for path, expected in [(args.source_chd, SOURCE_SHA), (args.target_chd, TARGET_SHA),
                           (args.chdman, CHDMAN_SHA), (args.xdelta, XDELTA_SHA)]:
        if sha256(path) != expected:
            raise ValueError('Unexpected input hash: ' + str(path))
    source_tracks, target_tracks = read_gdi(args.source_gdi), read_gdi(args.target_gdi)
    tracks, data_track = [], None
    for original, target in zip(source_tracks, target_tracks):
        keys = ['number', 'lba', 'type', 'sector', 'offset']
        if any(original[k] != target[k] for k in keys):
            raise ValueError('Disc geometry changed')
        source = args.source_gdi.parent / original['file']
        patched = args.target_gdi.parent / target['file']
        row = describe(source)
        target_row = describe(patched)
        if row['size'] != target_row['size']:
            raise ValueError('Track size changed')
        if original['number'] < 5 and row['sha256'] != target_row['sha256']:
            raise ValueError('Unexpected edit to track 1-4')
        row.pop('file')
        row.update(number=original['number'], layout=[original[k] for k in keys[1:]])
        tracks.append(row)
        if original['number'] == 5:
            data_track = dict(number=5, source_sha256=row['sha256'],
                              target_sha256=target_row['sha256'], target_size=target_row['size'])
            delta = payload / 'track05-v0.8.xdelta'
            if delta.exists():
                raise FileExistsError(delta)
            # No application header (avoids embedding private source filenames).
            subprocess.run([str(args.xdelta), '-e', '-9', '-A', '-B', '67108864',
                            '-s', str(source), str(patched), str(delta)], check=True)
    shutil.copyfile(args.chdman, payload / 'chdman.exe')
    shutil.copyfile(args.xdelta, payload / 'xdelta3.exe')
    manifest = dict(game_id=APP_ID, version=VERSION, required_free_bytes=3_000_000_000,
                    source=describe(args.source_chd),
                    target=describe(args.target_chd, 'Boku Doraemon Korean-v0.8.chd'),
                    tracks=tracks, data_track=data_track,
                    delta=describe(delta), chdman=describe(payload / 'chdman.exe'),
                    xdelta=describe(payload / 'xdelta3.exe'))
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    (payload / 'manifest.json').write_text(text, 'utf-8')
    (ROOT / 'patcher' / 'manifest.json').write_text(text, 'utf-8')
    print(text)

if __name__ == '__main__':
    main()
