"""Standalone Windows installer for Boku Doraemon Korean v0.8."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading

APP_ID = 'DC-Boku-Doraemon-Kr'
VERSION = '0.8'
RESOURCES = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_manifest(payload):
    data = json.loads((Path(payload) / 'manifest.json').read_text('utf-8'))
    if data['game_id'] != APP_ID or data['version'] != VERSION:
        raise ValueError('이 패처와 맞지 않는 패치 데이터입니다.')
    return data


def member(payload, name):
    base = Path(payload).resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError('잘못된 패치 데이터 경로입니다.')
    return path


def read_gdi(path):
    lines = path.read_text('utf-8-sig').splitlines()
    rows = []
    for line in lines[1:]:
        values = shlex.split(line)
        if not values:
            continue
        if len(values) != 6:
            raise ValueError('추출한 GDI의 항목 수가 다릅니다.')
        rows.append(dict(number=int(values[0]), lba=int(values[1]), type=int(values[2]),
                         sector=int(values[3]), file=values[4], offset=int(values[5])))
    if int(lines[0]) != 5 or [r['number'] for r in rows] != [1, 2, 3, 4, 5]:
        raise ValueError('추출한 디스크의 트랙 구성이 다릅니다.')
    return rows


def apply(source, output, *, payload=None, log=lambda value: None):
    payload = Path(payload or RESOURCES / 'payload').resolve()
    manifest = read_manifest(payload)
    if Path(output).is_symlink():
        raise ValueError('출력 파일이 링크입니다. 다른 새 파일 이름을 지정하세요.')
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError('원본과 다른 출력 파일을 지정하세요. 원본은 덮어쓰지 않습니다.')
    if output.exists() or output.is_symlink():
        raise ValueError('출력 파일이 이미 있습니다. 다른 새 파일 이름을 지정하세요.')
    if not source.is_file():
        raise ValueError('원본 일본판 CHD 파일을 선택하세요.')
    expected = manifest['source']
    log('원본 일본판 CHD 확인 중…')
    if source.stat().st_size != expected['size'] or sha256(source) != expected['sha256']:
        raise ValueError('대상 원본의 크기 또는 SHA-256이 다릅니다. 배포 페이지의 원본 해시를 확인하세요.')
    for key in ['xdelta', 'chdman', 'delta']:
        row = manifest[key]
        path = member(payload, row['file'])
        if not path.is_file() or path.stat().st_size != row['size'] or sha256(path) != row['sha256']:
            raise ValueError('패치 데이터가 손상되었습니다. EXE를 다시 받아 주세요.')
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < manifest['required_free_bytes']:
        raise ValueError('출력 드라이브의 여유 공간이 부족합니다. 3GB 이상을 확보하세요.')
    workspace = Path(tempfile.mkdtemp(prefix='.doraemon-v0.8-', dir=output.parent)).resolve()
    temporary = workspace / 'result.chd'

    def run(command):
        process = subprocess.run([str(v) for v in command], capture_output=True,
                                 cwd=workspace,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if process.returncode:
            detail = (process.stdout + process.stderr).decode('utf-8', 'replace')[-1400:]
            raise RuntimeError('패치 도구 실행에 실패했습니다. ' + detail)
        return (process.stdout + process.stderr).decode('utf-8', 'replace')

    try:
        log('원본 CHD의 트랙 추출 중…')
        gdi = workspace / 'source.gdi'
        chdman = member(payload, manifest['chdman']['file'])
        run([chdman, 'extractcd', '-i', source, '-o', gdi])
        tracks = read_gdi(gdi)
        if len(manifest['tracks']) != 5:
            raise ValueError('패치 데이터의 트랙 수가 올바르지 않습니다.')
        if len({row['file'] for row in tracks}) != 5:
            raise ValueError('추출된 트랙 파일 이름이 중복되었습니다.')
        for track, expected_track in zip(tracks, manifest['tracks']):
            path = member(workspace, track['file'])
            if track['number'] != expected_track['number'] or (track['lba'], track['type'], track['sector'], track['offset']) != tuple(expected_track['layout']):
                raise ValueError('추출된 트랙의 배치가 대상 원본과 다릅니다.')
            if path.stat().st_size != expected_track['size'] or sha256(path) != expected_track['sha256']:
                raise ValueError('추출된 원본 트랙의 해시가 다릅니다.')
        log('v0.8 한국어 패치 적용 중…')
        raw_data = member(workspace, tracks[4]['file'])
        patched = workspace / 'patched05.bin'
        run([member(payload, manifest['xdelta']['file']), '-d', '-s', raw_data,
             member(payload, manifest['delta']['file']), patched])
        expected_data = manifest['data_track']
        if patched.stat().st_size != expected_data['target_size'] or sha256(patched) != expected_data['target_sha256']:
            raise RuntimeError('패치한 데이터 트랙의 검증에 실패했습니다.')
        # Tracks 1-4 remain byte-for-byte original; only track 5 is replaced.
        raw_data.unlink()
        lines = ['5']
        for track in tracks:
            name = patched.name if track['number'] == 5 else track['file']
            if not name.isascii() or any(c.isspace() or c == '"' for c in name) or Path(name).name != name:
                raise ValueError('추출된 트랙 파일 이름이 올바르지 않습니다.')
            # MAME 0.264 parse_gdi incorrectly consumes the next token after a
            # quoted single-token filename. Use its generated ASCII basenames.
            lines.append(f"{track['number']} {track['lba']} {track['type']} {track['sector']} {name} {track['offset']}")
        patched_gdi = workspace / 'korean.gdi'
        patched_gdi.write_text('\n'.join(lines) + '\n', 'ascii')
        log('한국어 CHD 생성 중… 잠시 기다려 주세요.')
        # MAME 0.264's GDI parser uses narrow fopen(). Relative ASCII names
        # work even when the actual Windows working directory contains Hangul.
        run([chdman, 'createcd', '-i', patched_gdi.name, '-o', temporary.name, '-np', '8'])
        log('CHD 내부 무결성 확인 중…')
        run([chdman, 'verify', '-i', temporary])
        log('완성된 CHD의 SHA-256 확인 중…')
        target = manifest['target']
        actual = sha256(temporary)
        if temporary.stat().st_size != target['size'] or actual != target['sha256']:
            raise RuntimeError('결과 CHD의 검증에 실패했습니다. 완성 파일은 만들지 않았습니다.')
        # Windows rename refuses to replace an existing destination, including
        # one created while the worker was running. Both files are on one volume.
        if os.name == 'nt':
            os.rename(temporary, output)
        else:
            os.link(temporary, output)
            temporary.unlink()
        result = dict(success=True, version=VERSION, source_sha256=expected['sha256'],
                      output=str(output), output_size=output.stat().st_size,
                      output_sha256=actual, original_modified=False,
                      data_track_sha256=manifest['data_track']['target_sha256'],
                      chd_internal_integrity_verified=True)
        log('완료: ' + str(output))
        return result
    finally:
        # Verify the absolute, exclusively created workspace before recursive
        # cleanup. The user's source and any existing output are outside it.
        if workspace.is_symlink() or workspace.resolve().parent != output.parent.resolve() or not workspace.name.startswith('.doraemon-v0.8-'):
            raise RuntimeError('임시 작업 폴더 경로가 달라 정리를 중단했습니다.')
        if workspace.exists():
            shutil.rmtree(workspace)


def create_gui(payload=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    payload = Path(payload or RESOURCES / 'payload')
    manifest = read_manifest(payload)
    root = tk.Tk()
    root.title('나는 도라에몽 한국어 패치 v0.8')
    root.geometry('780x530')
    root.minsize(740, 530)
    frame = ttk.Frame(root, padding=22)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='나는 도라에몽', font=('맑은 고딕', 20, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Dreamcast 일본판 → 한국어 v0.8',
              font=('맑은 고딕', 11)).pack(anchor='w', pady=(3, 16))
    source = tk.StringVar()
    output = tk.StringVar()
    status = tk.StringVar(value='원본 일본판 CHD를 선택하세요. 출력 드라이브 여유 공간 3GB 이상이 필요합니다.')
    source_entry = output_entry = None

    def select_source():
        chosen = filedialog.askopenfilename(parent=root, title='원본 일본판 CHD 선택',
                                            filetypes=[('CHD 이미지', '*.chd'), ('모든 파일', '*.*')])
        if chosen:
            source.set(chosen)
            if not output.get():
                output.set(str(Path(chosen).parent / manifest['target']['file']))

    def select_output():
        chosen = filedialog.asksaveasfilename(parent=root, title='새 한국어 CHD 저장 위치',
                                            initialfile=manifest['target']['file'], defaultextension='.chd',
                                            filetypes=[('CHD 이미지', '*.chd')])
        if chosen:
            output.set(chosen)

    controls = []
    for label, variable, command in [('원본 CHD', source, select_source), ('출력 CHD', output, select_output)]:
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=7)
        ttk.Label(row, text=label, width=10).pack(side='left')
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side='left', fill='x', expand=True)
        button = ttk.Button(row, text='선택', command=command)
        button.pack(side='left', padx=(8, 0))
        controls.extend([entry, button])
        if variable is source:
            source_entry = entry
        else:
            output_entry = entry
    ttk.Label(frame, text='원본과 패치 데이터를 검사한 뒤 새 CHD를 만듭니다.\n완성된 CHD의 해시까지 일치해야 패치가 완료됩니다.',
              wraplength=690).pack(anchor='w', pady=(14, 9))
    ttk.Label(frame, textvariable=status, wraplength=690).pack(anchor='w', pady=5)
    progress = ttk.Progressbar(frame, mode='indeterminate')
    progress.pack(fill='x', pady=(6, 8))
    log_box = tk.Text(frame, height=4, wrap='word', state='disabled', font=('맑은 고딕', 9))
    log_box.pack(fill='both', expand=True, pady=(2, 8))
    events = queue.Queue()
    busy = False

    def start():
        nonlocal busy
        if not source.get() or not output.get():
            messagebox.showerror('파일 선택', '원본 CHD와 새 출력 CHD를 선택하세요.', parent=root)
            return
        chosen_source, chosen_output = source.get(), output.get()
        busy = True
        for widget in controls:
            widget.configure(state='disabled')
        apply_button.configure(state='disabled')
        progress.start()

        def worker():
            try:
                result = apply(chosen_source, chosen_output, payload=payload,
                               log=lambda value: events.put(('log', value)))
                events.put(('done', result))
            except Exception as error:
                events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    apply_button = ttk.Button(frame, text='한국어 패치 적용', command=start)
    apply_button.pack(anchor='e')

    def pump():
        nonlocal busy
        try:
            while True:
                kind, value = events.get_nowait()
                line = value if kind != 'done' else '결과 SHA-256: ' + value['output_sha256']
                status.set(line)
                log_box.configure(state='normal')
                log_box.insert('end', line + '\n')
                log_box.see('end')
                log_box.configure(state='disabled')
                if kind in ['done', 'error']:
                    busy = False
                    progress.stop()
                    for widget in controls:
                        widget.configure(state='normal')
                    apply_button.configure(state='normal')
                    if kind == 'done':
                        messagebox.showinfo('패치 완료', 'CHD 생성과 해시 검증을 완료했습니다.\n' + value['output'], parent=root)
                    else:
                        messagebox.showerror('패치 중단', value, parent=root)
        except queue.Empty:
            pass
        root.after(100, pump)

    def close():
        if busy:
            messagebox.showinfo('패치 적용 중', '파일 생성이 끝난 뒤 닫아 주세요.', parent=root)
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, pump)
    return root, dict(source=source, output=output, source_entry=source_entry,
                      output_entry=output_entry, apply_button=apply_button)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--payload', type=Path, help='개발·검증용 데이터 경로')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--self-test-ui', action='store_true')
    parser.add_argument('--version', action='version', version='V' + VERSION)
    args = parser.parse_args()
    if args.report:
        if args.report.exists() or args.report.is_symlink():
            parser.error('검증 보고서 파일이 이미 있습니다. 새 보고서 경로를 지정하세요.')
        if args.output and args.report.resolve() == args.output.resolve():
            parser.error('출력 CHD와 보고서는 서로 다른 파일이어야 합니다.')
    result = None
    code = 0
    if args.self_test_ui:
        root, widgets = create_gui(args.payload)
        root.withdraw()
        root.update_idletasks()
        assert widgets['source_entry'].winfo_exists() and widgets['output_entry'].winfo_exists()
        assert widgets['apply_button'].cget('text') == '한국어 패치 적용'
        assert root.title().endswith('v0.8')
        result = dict(success=True, version=VERSION, source_and_output_controls=True,
                      patch_button=True, korean_title=True, visual_screenshot_verified=False)
        root.destroy()
    elif args.source or args.output:
        if not (args.source and args.output):
            parser.error('--source와 --output을 함께 지정하세요.')
        try:
            result = apply(args.source, args.output, payload=args.payload)
        except Exception as error:
            result = dict(success=False, version=VERSION, error=str(error))
            code = 1
    else:
        root, _ = create_gui(args.payload)
        root.mainloop()
    if result is not None:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        if sys.stdout:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
