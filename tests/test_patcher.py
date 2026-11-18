"""Failure-path tests; the release EXE is additionally tested on the real CHD."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'patcher'))
import patcher


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='doraemon-patcher-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / '일본판 원본.chd'
        self.source.write_bytes(b'original CHD fixture')
        self.output = self.root / '한국어 결과.chd'
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        self.expected_chd = b'verified Korean CHD fixture'
        self.inputs = [b'track one', b'audio two', b'data three', b'audio four', b'I' * 2352]
        self.korean = b'K' * 2352
        self.manifest = dict(game_id=patcher.APP_ID, version=patcher.VERSION, required_free_bytes=100,
                             source=dict(size=self.source.stat().st_size, sha256=patcher.sha256(self.source)),
                             target=dict(file=self.output.name, size=len(self.expected_chd), sha256=digest(self.expected_chd)),
                             data_track=dict(number=5, source_sha256=digest(self.inputs[4]), target_size=2352,
                                             target_sha256=digest(self.korean)),
                             tracks=[dict(number=i+1, layout=[lba, kind, 2352, 0], size=len(data), sha256=digest(data))
                                     for i, (lba, kind, data) in enumerate(zip(
                                         [0, 450, 45000, 180495, 181308], [4, 0, 4, 0, 4], self.inputs))])
        for key, name in [('xdelta', 'xdelta.exe'), ('chdman', 'chdman.exe'), ('delta', 'data.xdelta')]:
            data = key.encode()
            (self.payload / name).write_bytes(data)
            self.manifest[key] = dict(file=name, size=len(data), sha256=digest(data))
        self.write_manifest()

    def write_manifest(self):
        (self.payload / 'manifest.json').write_text(json.dumps(self.manifest), 'utf-8')

    def fake_tool(self, command, **kwargs):
        command = [str(v) for v in command]
        if command[1] == 'extractcd':
            gdi = Path(command[command.index('-o') + 1])
            lines = ['5']
            for i, row in enumerate(self.manifest['tracks']):
                lba, kind, sector, offset = row['layout']
                name = f'source{i+1:02}.bin'
                lines.append(f'{i+1} {lba} {kind} {sector} {name} {offset}')
                (gdi.parent / name).write_bytes(self.inputs[i])
            gdi.write_text('\n'.join(lines) + '\n', 'ascii')
        elif command[1] == '-d':
            Path(command[-1]).write_bytes(self.korean)
        elif command[1] == 'createcd':
            self.assertEqual(command[command.index('-i') + 1], 'korean.gdi')
            self.assertEqual(command[command.index('-o') + 1], 'result.chd')
            root = Path(kwargs['cwd'])
            self.assertNotIn('"', (root / 'korean.gdi').read_text('ascii'))
            tracks = patcher.read_gdi(root / 'korean.gdi')
            self.assertEqual(len(tracks), 5)
            for i in range(4):
                self.assertEqual((root / tracks[i]['file']).read_bytes(), self.inputs[i])
            self.assertEqual((root / tracks[4]['file']).read_bytes(), self.korean)
            (root / command[command.index('-o') + 1]).write_bytes(self.expected_chd)
        return SimpleNamespace(returncode=0, stdout=b'OK', stderr=b'')

    def apply(self):
        return patcher.apply(self.source, self.output, payload=self.payload)

    def assert_preserved(self):
        self.assertEqual(self.source.read_bytes(), b'original CHD fixture')
        self.assertEqual(list(self.root.glob('.doraemon-v0.8-*')), [])

    def test_success_and_unicode_paths(self):
        with patch.object(patcher.subprocess, 'run', side_effect=self.fake_tool):
            result = self.apply()
        self.assertTrue(result['success'])
        self.assertEqual(self.output.read_bytes(), self.expected_chd)
        self.assert_preserved()

    def test_source_overwrite_rejected(self):
        with self.assertRaisesRegex(ValueError, '덮어쓰지'):
            patcher.apply(self.source, self.source, payload=self.payload)
        self.assert_preserved()

    def test_existing_output_preserved(self):
        self.output.write_bytes(b'KEEP')
        with self.assertRaisesRegex(ValueError, '이미'):
            self.apply()
        self.assertEqual(self.output.read_bytes(), b'KEEP')
        self.assert_preserved()

    def test_wrong_size_or_hash_rejected(self):
        for data in [b'wrong size', b'x' * self.source.stat().st_size]:
            self.source.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.apply()
            self.assertFalse(self.output.exists())

    def test_tampered_delta_rejected(self):
        (self.payload / 'data.xdelta').write_bytes(b'bad delta')
        with self.assertRaisesRegex(ValueError, '손상'):
            self.apply()
        self.assert_preserved()

    def test_payload_path_escape_rejected(self):
        self.manifest['xdelta']['file'] = '../outside.exe'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, '경로'):
            self.apply()
        self.assert_preserved()

    def test_insufficient_space_rejected(self):
        with patch.object(patcher.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, '여유 공간'):
                self.apply()
        self.assert_preserved()

    def test_decoder_failure_cleans_only_workspace(self):
        def fail(command, **kwargs):
            if str(command[1]) == '-d':
                return SimpleNamespace(returncode=1, stdout=b'', stderr=b'injected failure')
            return self.fake_tool(command, **kwargs)
        with patch.object(patcher.subprocess, 'run', side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.apply()
        self.assertFalse(self.output.exists())
        self.assert_preserved()

    def test_data_track_hash_failure(self):
        self.manifest['data_track']['target_sha256'] = '0' * 64
        self.write_manifest()
        with patch.object(patcher.subprocess, 'run', side_effect=self.fake_tool):
            with self.assertRaisesRegex(RuntimeError, '데이터 트랙'):
                self.apply()
        self.assertFalse(self.output.exists())
        self.assert_preserved()

    def test_final_chd_hash_failure(self):
        self.manifest['target']['sha256'] = '0' * 64
        self.write_manifest()
        with patch.object(patcher.subprocess, 'run', side_effect=self.fake_tool):
            with self.assertRaisesRegex(RuntimeError, 'CHD의 검증'):
                self.apply()
        self.assertFalse(self.output.exists())
        self.assert_preserved()

    def test_output_created_during_patch_is_preserved(self):
        def concurrent(command, **kwargs):
            result = self.fake_tool(command, **kwargs)
            if str(command[1]) == 'verify':
                self.output.write_bytes(b'CREATED BY ANOTHER PROCESS')
            return result
        with patch.object(patcher.subprocess, 'run', side_effect=concurrent):
            with self.assertRaises(FileExistsError):
                self.apply()
        self.assertEqual(self.output.read_bytes(), b'CREATED BY ANOTHER PROCESS')
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
