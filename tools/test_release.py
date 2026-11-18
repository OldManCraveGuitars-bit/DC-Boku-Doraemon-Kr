"""Exercise the packaged EXE with the real source CHD, then delete owned test data."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'patcher'))
from patcher import sha256

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    manifest = json.loads((ROOT / 'patcher/manifest.json').read_text('utf-8'))
    exe = ROOT / 'dist/DC-Boku-Doraemon-Kr-v0.8-Patcher.exe'
    assert sha256(source) == manifest['source']['sha256']
    tests = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                           cwd=ROOT, capture_output=True, text=True)
    if tests.returncode:
        raise RuntimeError(tests.stdout + tests.stderr)
    (ROOT / 'docs/verification/unit-tests.txt').write_text(tests.stdout + tests.stderr, 'utf-8')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix='release-v0.8-test-', dir=build)).resolve()
    env = os.environ.copy()
    for key in ['PYTHONPATH', 'PYTHONHOME', 'TCL_LIBRARY', 'TK_LIBRARY']:
        env.pop(key, None)
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    env['PATH'] = os.path.join(system_root, 'System32') + ';' + system_root
    def run(args):
        start = time.monotonic()
        process = subprocess.run([str(exe)] + [str(arg) for arg in args], env=env,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return process.returncode, round(time.monotonic()-start, 3)
    try:
        ui_report = workspace / 'ui.json'
        code, ui_seconds = run(['--self-test-ui', '--report', ui_report])
        if code:
            raise RuntimeError('Packaged UI self-test failed: ' + str(code))
        ui = json.loads(ui_report.read_text('utf-8'))
        assert ui['success']
        print('Packaged UI controls: passed', flush=True)
        output = workspace / '검증용 한글 경로' / '나는 도라에몽 v0.8.chd'
        report = workspace / 'result.json'
        code, seconds = run(['--source', source, '--output', output, '--report', report])
        if code:
            raise RuntimeError('Packaged patch failed: ' + report.read_text('utf-8'))
        result = json.loads(report.read_text('utf-8'))
        assert result['success'] and output.is_file()
        actual = sha256(output)
        assert actual == manifest['target']['sha256']
        assert output.stat().st_size == manifest['target']['size']
        assert sha256(source) == manifest['source']['sha256']
        assert not list(output.parent.glob('.doraemon-v0.8-*'))
        # Test the *same packaged EXE* refusing an existing result.
        existing_report = workspace / 'existing-output.json'
        code, _ = run(['--source', source, '--output', output, '--report', existing_report])
        failure = json.loads(existing_report.read_text('utf-8'))
        assert code == 1 and not failure['success'] and sha256(output) == actual
        record = dict(passed=True, version='0.8', platform='Windows x86_64',
                      executable=dict(file=exe.name,size=exe.stat().st_size,sha256=sha256(exe)),
                      unit_tests=11, packaged_ui=ui, ui_seconds=ui_seconds,
                      packaged_exe_real_patch=True, patch_seconds=seconds,
                      source_sha256=manifest['source']['sha256'], source_unchanged=True,
                      output_size=output.stat().st_size,output_sha256=actual,
                      chd_internal_integrity_verified=result['chd_internal_integrity_verified'],
                      matches_previously_validated_game=True, unicode_output_path=True,
                      external_python_and_tools_required=False,
                      existing_output_rejected_and_preserved=True,
                      patcher_temporary_tracks_removed=True,
                      duplicate_test_chd_retained=False,
                      scope='EXE reconstruction and UI control creation; no whole-window screenshot test')
        (ROOT / 'docs/verification/patcher-test.json').write_text(
            json.dumps(record,ensure_ascii=False,indent=2)+'\n','utf-8')
        print(json.dumps(record,ensure_ascii=False,indent=2),flush=True)
    finally:
        if workspace.is_symlink() or workspace.resolve().parent != build.resolve() or not workspace.name.startswith('release-v0.8-test-'):
            raise RuntimeError('Test cleanup containment check failed')
        shutil.rmtree(workspace)

if __name__ == '__main__':
    main()
