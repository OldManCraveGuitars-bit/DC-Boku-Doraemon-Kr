# 패처 빌드

이 저장소는 원본 게임이나 한글화 완료 CHD를 포함하지 않습니다. 공개 소스는 **차분 적용 패처**의 소스이며, 원작 게임 데이터를 포함한 전체 한글화 편집 프로젝트는 아닙니다.

## 환경

- Windows 64비트
- Python 3.13 (배포 빌드: 3.13.15)
- PyInstaller 6.22.3
- MAME 0.264의 `chdman.exe`
- xdelta3 3.2.1의 Windows 실행 파일

외부 도구는 [고지](../THIRD_PARTY_NOTICES.md)와 `patcher/manifest.json`의 해시를 확인합니다. 수정한 바이너리는 사용하지 않았습니다.

## 공개 차분으로 다시 패키징

1. 릴리스의 `track05-v0.8.xdelta`와 `manifest.json`을 저장소의 `payload` 폴더에 둡니다.
2. 일치하는 `chdman.exe`, `xdelta3.exe`를 같은 폴더에 둡니다. 모든 파일의 해시는 매니페스트에 있습니다.
3. `python -m pip install PyInstaller==6.22.3`으로 빌드 도구를 설치합니다.
4. 저장소 루트에서 아래 명령을 실행합니다.

```powershell
python -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_release.ps1
```

결과는 `dist/DC-Boku-Doraemon-Kr-v0.8-Patcher.exe`입니다. PyInstaller와 Windows PE 빌드 시간 등에 따라 EXE 해시는 달라질 수 있습니다. 패처가 만드는 CHD는 매니페스트의 고정 해시와 일치해야 합니다.

## 차분 생성

원본·대상 CHD와 각각을 추출한 5트랙 GDI를 가진 제작자는 `tools/build_payload.py`를 사용할 수 있습니다. 이 도구는 두 CHD와 도구의 해시, 트랙 배치·크기를 확인하고 트랙 1~4의 바이트 일치를 검사합니다. 트랙 5만 xdelta3로 차분화합니다. 기존 `payload/track05-v0.8.xdelta`가 있으면 덮어쓰지 않습니다.

```powershell
python tools/build_payload.py --source-chd ORIGINAL.chd --target-chd KOREAN.chd --source-gdi ORIGINAL.gdi --target-gdi KOREAN.gdi --chdman CHDMAN.exe --xdelta XDELTA3.exe
```

## 명령행 적용과 검사

```powershell
$patch = Start-Process -FilePath '.\dist\DC-Boku-Doraemon-Kr-v0.8-Patcher.exe' -ArgumentList '--source "C:\Games\Boku Doraemon (Japan).chd" --output "C:\Games\Boku Doraemon Korean-v0.8.chd" --report "C:\Games\patch-result.json"' -Wait -PassThru -WindowStyle Hidden
$patch.ExitCode
```

결과 보고서는 새 파일이어야 합니다. 성공 시 종료 코드는 0, 적용 중 검사 실패 시 1입니다. `--self-test-ui --report NEW-REPORT.json`은 GUI 컨트롤 생성 검사이며 화면 캡처 검증을 대신하지 않습니다. `--payload`는 개발용 데이터 경로 재정의 옵션입니다.

패처는 출력 폴더 아래에 자신이 만든 임시 폴더만 사용합니다. 실패 시 새 결과 파일을 내보내지 않고, 끝나면 임시 트랙을 정리합니다. GUI를 닫는 동작은 진행 중인 작업이 끝난 뒤 허용합니다.
