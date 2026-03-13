// 앱의 메인 화면 -- 상태 머신 기반의 단일 화면
// 상태 변수 관리와 OCR 이벤트 처리를 담당하며,
// 실제 UI 빌드는 HomeScreenBuilder에 위임한다.

import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../models/ocr_state.dart';
import '../services/ocr_service.dart';
import '../services/file_service.dart';
import 'home_screen_builder.dart';
import 'home_state_handler.dart';

/// 메인 홈 화면 위젯
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final OcrService _ocrService = OcrService();
  final FileService _fileService = FileService();

  OcrAppState _appState = OcrAppState.idle;
  String? _selectedFilePath;
  DownloadProgress? _downloadProgress;
  ProcessingProgress? _processingProgress;
  SplitProgress? _splitProgress;
  OcrResult? _ocrResult;
  String? _errorMessage;
  String? _errorCode;
  bool _isRecoverable = false;

  /// 현재 요청된 분할 권 수 (재시도 시 유지)
  int _currentSplitCount = 1;

  /// Phase 1(OCR)에서 수신한 원래 총 페이지 수
  /// Phase 2 후처리 시 모델별 진행률 계산에 사용한다.
  int _originalTotalPages = 0;

  /// 모델 초기 설정 중 메시지 (서드파티 stderr 출력 감지 시 표시)
  String? _modelSetupMessage;

  /// complete 이벤트 수신 후 임시 저장되는 OCR 결과
  /// (split_complete 수신 전까지 split 정보가 없으므로 보관한다)
  OcrResult? _pendingOcrResult;

  /// 로그 메시지 목록 (최근 50개까지 보관)
  final List<LogEntry> _logEntries = [];

  /// 메모리 경고 표시 여부
  bool _showMemoryWarning = false;

  /// 최근 메모리 경고 메시지
  String? _memoryWarningMessage;

  /// 현재 활성 모델 이름 (Phase 2 후처리 중)
  String? _activeModelName;

  StreamSubscription<OcrEvent>? _ocrSubscription;

  @override
  void dispose() {
    _ocrSubscription?.cancel();
    _ocrService.dispose();
    super.dispose();
  }

  // 파일이 선택되면 FILE_SELECTED 상태로 전환한다.
  void _onFileSelected(String path) {
    if (!_fileService.isValidPdfPath(path)) return;
    setState(() {
      _selectedFilePath = path;
      _appState = OcrAppState.fileSelected;
    });
  }

  // 파일 선택 취소 -- IDLE 상태로 복귀한다.
  void _onClearFile() {
    setState(() {
      _selectedFilePath = null;
      _appState = OcrAppState.idle;
    });
  }

  // 변환 시작 -- splitCount를 인자로 받아 OCR 처리를 시작한다.
  Future<void> _onStartOcr(int splitCount) async {
    if (_selectedFilePath == null) return;
    await _ocrSubscription?.cancel();

    // 분할 권 수를 저장해 재시도 시 재사용한다.
    _currentSplitCount = splitCount;

    setState(() {
      _appState = OcrAppState.processing;
      _processingProgress = null;
      _splitProgress = null;
      _downloadProgress = null;
      _ocrResult = null;
      _pendingOcrResult = null;
      _errorMessage = null;
      _modelSetupMessage = null;
    });

    _ocrSubscription = _ocrService
        .startOcr(_selectedFilePath!, splitParts: splitCount)
        .listen(
          _handleOcrEvent,
          onError: _handleStreamError,
          onDone: _handleStreamDone,
        );
  }

  /// macOS 시스템 알림을 전송한다. (앱이 비활성 상태일 때 유용하다)
  void _sendCompletionNotification(OcrResult result) {
    try {
      final pageInfo = result.totalPages > 0 ? '${result.totalPages}페이지' : '';
      final timeInfo = result.formattedElapsedTime;
      final subtitle = '$pageInfo 변환 완료 ($timeInfo)';
      Process.run('osascript', [
        '-e',
        'display notification "$subtitle" with title "OCR Module" sound name "Glass"',
      ]);
    } catch (_) {
      // 알림 실패는 무시한다 — 핵심 기능이 아니다
    }
  }

  // OCR 이벤트를 처리하여 상태를 업데이트한다.
  void _handleOcrEvent(OcrEvent event) {
    if (!mounted) return;
    switch (event.type) {
      case OcrEventType.download:
        setState(() {
          _appState = OcrAppState.downloadingModel;
          _downloadProgress = DownloadProgress(
            downloadedMb: event.downloadedMb ?? 0,
            totalMb: event.totalMb ?? 0,
            percent: event.percent ?? 0,
            statusText: HomeStateHandler.translateDownloadStatus(event.status),
          );
        });

      case OcrEventType.init:
        setState(() {
          _appState = OcrAppState.processing;
          // 원래 총 페이지 수를 저장 — Phase 2 후처리 진행률 계산에 사용
          _originalTotalPages = event.totalPages ?? 0;
          _processingProgress = ProcessingProgress(
            currentPage: 0,
            totalPages: event.totalPages ?? 0,
            percent: 0,
            statusText: '처리 준비 중...',
            memoryMb: 0,
            startTime: DateTime.now(),
            skippedPages: 0,
          );
        });

      case OcrEventType.progress:
        _handleProgressEvent(event);

      case OcrEventType.complete:
        // 분할이 있을 경우 split_complete를 기다린다.
        // 분할이 없으면 즉시 완료 상태로 전환한다.
        final result = OcrResult(
          outputPath: event.outputPath ?? '',
          totalPages: event.totalPages ?? 0,
          skippedPages: _processingProgress?.skippedPages ?? 0,
          elapsedSeconds: event.elapsedSeconds ?? 0,
        );
        if (_currentSplitCount >= 2) {
          // split_complete 이벤트를 대기하며 결과를 임시 보관
          setState(() {
            _pendingOcrResult = result;
          });
        } else {
          // 분할 없음 -- 즉시 완료 처리
          setState(() {
            _appState = OcrAppState.complete;
            _ocrResult = result;
          });
          _sendCompletionNotification(result);
        }

      case OcrEventType.splitProgress:
        // 분할 진행 중 상태를 업데이트한다.
        setState(() {
          _splitProgress = SplitProgress(
            currentPart: event.currentPart ?? 1,
            totalParts: event.totalParts ?? _currentSplitCount,
            startPage: event.startPage ?? 0,
            endPage: event.endPage ?? 0,
          );
        });

      case OcrEventType.splitComplete:
        // 분할 완료 -- 최종 결과를 구성하고 완료 상태로 전환한다.
        final parts = event.splitPartPaths ?? [];
        final base = _pendingOcrResult;
        setState(() {
          _appState = OcrAppState.complete;
          _splitProgress = null;
          _ocrResult = OcrResult(
            outputPath: base?.outputPath ?? (parts.isNotEmpty ? parts.first : ''),
            totalPages: base?.totalPages ?? 0,
            skippedPages: base?.skippedPages ?? 0,
            elapsedSeconds: base?.elapsedSeconds ?? 0,
            splitParts: parts,
            totalParts: event.totalParts ?? parts.length,
          );
          _pendingOcrResult = null;
        });
        _sendCompletionNotification(_ocrResult!);

      case OcrEventType.error:
        _handleErrorEvent(event);

      case OcrEventType.log:
        final level = event.logLevel ?? 'info';
        final msg = event.logMessage ?? '';
        // 메모리 경고 감지
        if (level == 'warn' && msg.contains('메모리')) {
          setState(() {
            _showMemoryWarning = true;
            _memoryWarningMessage = msg;
          });
        }
        setState(() {
          _logEntries.add(LogEntry(
            level: level,
            message: msg,
            timestamp: DateTime.now(),
          ));
          // 최대 50개까지만 보관한다
          if (_logEntries.length > 50) _logEntries.removeAt(0);
        });
        break;

      case OcrEventType.modelSetup:
        // 서드파티 라이브러리의 모델 다운로드/로드 관련 stderr 출력 감지
        // UI에 "초기 모델 설정 중" 메시지를 표시한다
        setState(() {
          _modelSetupMessage = event.logMessage;
        });
    }
  }

  // progress 이벤트 -- ProcessingProgress를 갱신한다.
  // 워커별 진행 정보도 함께 파싱하여 반영한다.
  void _handleProgressEvent(OcrEvent event) {
    // 워커별 진행 정보를 WorkerProgress 목록으로 변환한다
    final workerList = (event.workerProgressData ?? [])
        .map((wp) => WorkerProgress(
              workerId: wp['worker_id'] as int? ?? 0,
              completed: wp['completed'] as int? ?? 0,
              total: wp['total'] as int? ?? 0,
            ))
        .toList();

    // Phase 변경 감지 — 후처리/PDF 생성 전환 시 ocrStartTime을 리셋한다
    final currentStatus = _processingProgress?.statusText ?? '';
    final newStatus = HomeStateHandler.translateProgressStatus(event.status);
    final phaseChanged = currentStatus.isNotEmpty &&
        currentStatus != newStatus &&
        (newStatus.contains('후처리') || newStatus.contains('PDF 생성'));

    setState(() {
      _appState = OcrAppState.processing;
      if (_processingProgress != null) {
        _processingProgress = _processingProgress!.copyWith(
          currentPage: event.currentPage,
          totalPages: event.totalPages,
          percent: event.percent,
          statusText: newStatus,
          memoryMb: event.memoryMb,
          numWorkers: event.numWorkers,
          // 워커 정보가 있을 때만 갱신하고, 없으면 기존 값을 유지한다
          workerProgress: workerList.isNotEmpty ? workerList : null,
          // Phase 변경 시 ocrStartTime 리셋 — 이전 Phase 소요시간 제외
          ocrStartTime: phaseChanged
              ? DateTime.now()
              : (_processingProgress!.ocrStartTime ?? DateTime.now()),
        );
      } else {
        _processingProgress = ProcessingProgress(
          currentPage: event.currentPage ?? 0,
          totalPages: event.totalPages ?? 0,
          percent: event.percent ?? 0,
          statusText: HomeStateHandler.translateProgressStatus(event.status),
          memoryMb: event.memoryMb ?? 0,
          startTime: DateTime.now(),
          skippedPages: 0,
          numWorkers: event.numWorkers ?? 0,
          workerProgress: workerList,
        );
      }
      // Phase 2에서 활성 모델 이름을 추적한다
      if (event.modelName != null) {
        _activeModelName = event.modelName;
      }
    });
  }

  // error 이벤트 -- 복구 가능 여부에 따라 상태를 전환한다.
  void _handleErrorEvent(OcrEvent event) {
    if (!(event.recoverable ?? false)) {
      setState(() {
        _appState = OcrAppState.error;
        _errorMessage = event.errorMessage ?? '알 수 없는 오류가 발생했습니다.';
        _errorCode = event.errorCode;
        _isRecoverable = false;
      });
    } else if (_processingProgress != null) {
      // 복구 가능한 에러 (페이지 스킵) -- 카운터 증가 + 페이지 번호 기록
      final failedPage = event.currentPage;
      final updatedFailed = List<int>.from(_processingProgress!.failedPages);
      if (failedPage != null) updatedFailed.add(failedPage);
      setState(() {
        _processingProgress = _processingProgress!.copyWith(
          skippedPages: (_processingProgress?.skippedPages ?? 0) + 1,
          failedPages: updatedFailed,
        );
      });
    }
  }

  // 스트림 에러를 처리한다.
  void _handleStreamError(Object error) {
    if (!mounted) return;
    setState(() {
      _appState = OcrAppState.error;
      _errorMessage = '처리 중 예기치 않은 오류: $error';
      _isRecoverable = false;
    });
  }

  // 스트림 종료를 처리한다.
  // 분할 대기 중이면 마스터 PDF를 최종 결과로 사용하고,
  // 처리 중이면 비정상 종료로 에러 처리한다.
  void _handleStreamDone() {
    if (!mounted) return;

    // 분할 대기 중 스트림이 종료된 경우 — 분할은 실패했지만 OCR 결과는 유효하다
    // 마스터 PDF 결과를 최종 결과로 사용하여 사용자에게 보여준다
    if (_pendingOcrResult != null) {
      setState(() {
        _appState = OcrAppState.complete;
        _ocrResult = _pendingOcrResult;
        _pendingOcrResult = null;
      });
      return;
    }

    // 분할 없이 처리 중 상태에서 스트림이 끊기면 에러 처리
    if (_appState == OcrAppState.processing) {
      setState(() {
        _appState = OcrAppState.error;
        _errorMessage = 'OCR 처리가 비정상적으로 종료되었습니다.';
        _isRecoverable = false;
      });
    }
  }

  // 취소 -- IDLE로 복귀한다.
  Future<void> _onCancel() async {
    await _ocrService.cancel();
    await _ocrSubscription?.cancel();
    _ocrSubscription = null;
    if (mounted) {
      setState(() {
        _appState = OcrAppState.idle;
        _selectedFilePath = null;
        _processingProgress = null;
        _splitProgress = null;
        _downloadProgress = null;
        _pendingOcrResult = null;
        _modelSetupMessage = null;
        _logEntries.clear();
        _showMemoryWarning = false;
        _memoryWarningMessage = null;
        _activeModelName = null;
      });
    }
  }

  // 재시도 -- 저장된 분할 권 수로 다시 시작한다.
  Future<void> _onRetry() async {
    if (_selectedFilePath == null) {
      _resetToIdle();
      return;
    }
    await _onStartOcr(_currentSplitCount);
  }

  // IDLE 상태로 완전 초기화한다.
  void _resetToIdle() {
    setState(() {
      _appState = OcrAppState.idle;
      _selectedFilePath = null;
      _downloadProgress = null;
      _processingProgress = null;
      _splitProgress = null;
      _ocrResult = null;
      _pendingOcrResult = null;
      _errorMessage = null;
      _errorCode = null;
      _currentSplitCount = 1;
      _originalTotalPages = 0;
      _modelSetupMessage = null;
      _logEntries.clear();
      _showMemoryWarning = false;
      _memoryWarningMessage = null;
      _activeModelName = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              HomeScreenBuilder.buildHeader(context, _appState),
              const SizedBox(height: AppSpacing.xl),
              Expanded(
                child: AnimatedSwitcher(
                  duration: AppDuration.normal,
                  child: HomeScreenBuilder.buildStateView(
                    context: context,
                    appState: _appState,
                    selectedFilePath: _selectedFilePath,
                    downloadProgress: _downloadProgress,
                    processingProgress: _processingProgress,
                    splitProgress: _splitProgress,
                    ocrResult: _ocrResult,
                    errorMessage: _errorMessage,
                    errorCode: _errorCode,
                    isRecoverable: _isRecoverable,
                    modelSetupMessage: _modelSetupMessage,
                    originalTotalPages: _originalTotalPages,
                    logEntries: _logEntries,
                    showMemoryWarning: _showMemoryWarning,
                    memoryWarningMessage: _memoryWarningMessage,
                    activeModelName: _activeModelName,
                    onFileSelected: _onFileSelected,
                    onClearFile: _onClearFile,
                    onStartOcr: _onStartOcr,
                    onCancel: _onCancel,
                    onRetry: _onRetry,
                    onReset: _resetToIdle,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
