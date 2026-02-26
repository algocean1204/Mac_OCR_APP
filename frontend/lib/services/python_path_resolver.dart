// Python 실행 파일 경로 결정 서비스
// 프로젝트 .venv 또는 시스템 Python3를 탐색하여 경로를 반환한다.

import 'dart:io';

/// Python 경로 해석기 -- Python 실행 파일 및 스크립트 경로를 찾는다.
class PythonPathResolver {
  /// Python 실행 파일 경로를 찾는다.
  /// 우선순위: backend/.venv > 프로젝트루트/.venv > /usr/bin > /opt/homebrew > /usr/local
  static String? findPythonExecutable(String projectRoot) {
    // 1순위: backend 디렉토리의 .venv (install.sh가 여기에 생성한다)
    final backendVenvPython = '$projectRoot/backend/.venv/bin/python3';
    if (File(backendVenvPython).existsSync()) return backendVenvPython;

    // 2순위: 프로젝트 루트의 .venv (사용자가 수동 생성한 경우)
    final rootVenvPython = '$projectRoot/.venv/bin/python3';
    if (File(rootVenvPython).existsSync()) return rootVenvPython;

    // 3순위: macOS 시스템 기본
    if (File('/usr/bin/python3').existsSync()) return '/usr/bin/python3';

    // 4순위: Homebrew (Apple Silicon)
    if (File('/opt/homebrew/bin/python3').existsSync()) {
      return '/opt/homebrew/bin/python3';
    }

    // 5순위: Homebrew (Intel)
    if (File('/usr/local/bin/python3').existsSync()) {
      return '/usr/local/bin/python3';
    }

    return null;
  }

  /// backend/main.py 스크립트 경로를 찾는다.
  static String? findBackendScript(String projectRoot) {
    final scriptPath = '$projectRoot/backend/main.py';
    if (File(scriptPath).existsSync()) return scriptPath;
    return null;
  }

  /// 프로젝트 루트 디렉토리를 탐색하여 반환한다.
  /// 앱 번들 위치 또는 현재 디렉토리 기준으로 상위 탐색한다.
  static String findProjectRoot() {
    final executablePath = Platform.resolvedExecutable;

    // .app 번들 안에서 실행 중인 경우:
    // 번들 위치에서 상위로 올라가며 backend/main.py를 탐색한다.
    // 빌드 경로가 깊으므로 (frontend/build/macos/Build/Products/Debug/app.app)
    // 충분한 깊이까지 탐색해야 한다.
    if (executablePath.contains('.app/Contents/MacOS/')) {
      final dotAppIndex = executablePath.indexOf('.app/');
      final appBundlePath = executablePath.substring(0, dotAppIndex + 4);
      var dir = Directory(appBundlePath).parent.path;
      for (int i = 0; i < 10; i++) {
        if (File('$dir/backend/main.py').existsSync()) return dir;
        final parent = Directory(dir).parent.path;
        if (parent == dir) break;
        dir = parent;
      }
    }

    // 개발 환경: 현재 디렉토리 기준 상위 탐색
    var dir = Directory.current.path;
    for (int i = 0; i < 10; i++) {
      if (File('$dir/backend/main.py').existsSync()) return dir;
      final parent = Directory(dir).parent.path;
      if (parent == dir) break;
      dir = parent;
    }

    return Directory.current.path;
  }

  /// Python 프로세스에 전달할 환경변수를 구성한다.
  /// 프로젝트 루트를 PYTHONPATH에 추가하여 backend.xxx 모듈 경로를 해석할 수 있게 한다.
  static Map<String, String> buildEnvironment(String projectRoot) {
    final env = Map<String, String>.from(Platform.environment);

    // 프로젝트 루트를 PYTHONPATH에 추가하여 'backend.xxx' import가 작동하게 한다
    if (env.containsKey('PYTHONPATH')) {
      env['PYTHONPATH'] = '$projectRoot:${env['PYTHONPATH']}';
    } else {
      env['PYTHONPATH'] = projectRoot;
    }

    return env;
  }
}
