// Python OCR 백엔드와의 통신을 담당하는 서비스
// Python subprocess를 시작하고 stdout/stderr 스트림을 파싱하여
// OcrEvent 스트림으로 변환한다.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../models/ocr_state.dart';
import 'python_path_resolver.dart';

/// Python OCR 서비스 -- subprocess 통신 전담
class OcrService {
  /// 현재 실행 중인 Python 프로세스
  Process? _process;
  StreamSubscription<String>? _stdoutSubscription;
  StreamSubscription<String>? _stderrSubscription;

  /// 현재 Python 프로세스가 실행 중인지 여부
  bool get isRunning => _process != null;

  /// OCR 처리를 시작하고 이벤트 스트림을 반환한다.
  /// [splitParts]가 2 이상이면 Python에 --split 인자를 전달하여 PDF를 분할한다.
  Stream<OcrEvent> startOcr(String pdfPath, {int splitParts = 1}) async* {
    if (_process != null) {
      yield OcrEvent.fromError('이미 처리 중입니다. 취소 후 다시 시도해주세요.');
      return;
    }

    final projectRoot = PythonPathResolver.findProjectRoot();
    final pythonExecutable = PythonPathResolver.findPythonExecutable(projectRoot);
    final scriptPath = PythonPathResolver.findBackendScript(projectRoot);

    if (pythonExecutable == null) {
      yield OcrEvent.fromError(
        'Python 실행 파일을 찾을 수 없습니다.\n'
        '프로젝트 루트에서 setup.sh를 먼저 실행해주세요.',
      );
      return;
    }

    if (scriptPath == null) {
      yield OcrEvent.fromError(
        'backend/main.py를 찾을 수 없습니다.\n'
        '프로젝트 구조를 확인해주세요.',
      );
      return;
    }

    final controller = StreamController<OcrEvent>();

    try {
      // Python subprocess 시작
      // splitParts가 2 이상이면 --split 인자를 추가하여 분할을 요청한다.
      final args = [scriptPath, '--input', pdfPath];
      if (splitParts >= 2) {
        args.addAll(['--split', splitParts.toString()]);
      }

      _process = await Process.start(
        pythonExecutable,
        args,
        workingDirectory: projectRoot,
        environment: PythonPathResolver.buildEnvironment(projectRoot),
      );

      // stdout 스트림 구독 -- NDJSON 파싱
      _stdoutSubscription = _process!.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(
        (line) {
          final event = _parseLine(line);
          if (event != null) {
            controller.add(event);
            // 스트림 종료 판정:
            // - 분할 없음(splitParts=1): complete 이벤트가 최종 종료 신호
            // - 분할 있음(splitParts>=2): split_complete가 최종 종료 신호
            //   (complete 후에도 split_progress/split_complete가 이어지므로 닫지 않는다)
            final bool isTerminal;
            if (splitParts >= 2) {
              isTerminal = event.type == OcrEventType.splitComplete;
            } else {
              isTerminal = event.type == OcrEventType.complete;
            }
            if (isTerminal && !controller.isClosed) {
              controller.close();
            }
          }
        },
        onError: (e) {
          if (!controller.isClosed) controller.addError(e);
        },
        onDone: () {
          if (!controller.isClosed) controller.close();
        },
      );

      // stderr 스트림 구독 -- 에러 메시지 처리
      _stderrSubscription = _process!.stderr
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(
        (line) {
          final event = _parseErrorLine(line);
          if (event != null && !controller.isClosed) {
            controller.add(event);
          }
        },
        onError: (_) {},
        cancelOnError: false,
      );

      // 프로세스 종료 처리
      _process!.exitCode.then((exitCode) {
        _cleanup();
        if (exitCode != 0 && !controller.isClosed) {
          controller.add(
            OcrEvent.fromError('처리 중 오류가 발생했습니다. (종료 코드: $exitCode)'),
          );
          controller.close();
        }
      });

      yield* controller.stream;
    } catch (e) {
      _cleanup();
      yield OcrEvent.fromError('Python 프로세스를 시작할 수 없습니다: $e');
    }
  }

  /// 현재 실행 중인 OCR 프로세스를 취소한다.
  Future<void> cancel() async {
    if (_process == null) return;
    try {
      // graceful shutdown 요청
      _process!.stdin.writeln('CANCEL');
      await _process!.stdin.flush();
      // 5초 대기 후 강제 종료
      await Future.delayed(const Duration(seconds: 5));
      if (_process != null) _process!.kill();
    } catch (_) {
      _process?.kill();
    } finally {
      _cleanup();
    }
  }

  /// stdout 한 줄을 OcrEvent로 파싱한다.
  OcrEvent? _parseLine(String line) {
    if (line.trim().isEmpty) return null;
    try {
      final json = jsonDecode(line) as Map<String, dynamic>;
      return OcrEvent.fromJson(json);
    } catch (_) {
      return null;
    }
  }

  /// stderr 한 줄을 OcrEvent로 파싱한다.
  /// 약속된 JSON 형식이 아닌 라인(tqdm 진행률 바, 경고 메시지 등)은
  /// 에러로 취급하지 않고 무시하거나 모델 설정 안내로 변환한다.
  OcrEvent? _parseErrorLine(String line) {
    if (line.trim().isEmpty) return null;
    try {
      final json = jsonDecode(line) as Map<String, dynamic>;
      return OcrEvent.fromJson(json);
    } catch (_) {
      // JSON이 아닌 stderr 라인 — 서드파티 라이브러리 출력이므로 무시한다
      // 다운로드/모델 관련 키워드가 감지되면 모델 설정 안내 이벤트를 생성한다
      if (_isModelSetupLine(line)) {
        return OcrEvent.modelSetup(line);
      }
      // 그 외 비-JSON 라인은 조용히 무시한다 (tqdm, 경고 등)
      return null;
    }
  }

  /// stderr 라인이 모델 다운로드/설정 관련 출력인지 판별한다.
  bool _isModelSetupLine(String line) {
    final lower = line.toLowerCase();
    return lower.contains('fetching') ||
        lower.contains('downloading') ||
        lower.contains('model') ||
        lower.contains('tokenizer') ||
        lower.contains('loading') ||
        lower.contains('config.json');
  }

  /// 프로세스 관련 리소스를 정리한다.
  void _cleanup() {
    _stdoutSubscription?.cancel();
    _stderrSubscription?.cancel();
    _stdoutSubscription = null;
    _stderrSubscription = null;
    _process = null;
  }

  /// 서비스 종료 시 리소스를 해제한다.
  void dispose() {
    _process?.kill();
    _cleanup();
  }
}
