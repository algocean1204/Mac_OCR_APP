#!/bin/bash
# macOS PDF OCR 변환기 — 설치 스크립트

set -e

echo "=== AI PDF OCR 변환기 설치 ==="
echo ""

# 1. Python 가상환경 생성 + 의존성 설치
echo "[1/3] Python 환경 설정 중..."
cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"

if [ ! -d "backend/.venv" ]; then
    python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
echo "✓ Python 환경 준비 완료"

# 2. Flutter 의존성 설치
echo ""
echo "[2/3] Flutter 의존성 설치 중..."
cd frontend
flutter pub get
echo "✓ Flutter 의존성 준비 완료"

# 3. macOS 빌드
echo ""
echo "[3/3] macOS 앱 빌드 중..."
flutter build macos --release
echo "✓ 빌드 완료"

echo ""
echo "=== 설치 완료! ==="
echo "실행 방법: cd frontend && flutter run -d macos"
echo "또는: open frontend/build/macos/Build/Products/Release/frontend.app"
