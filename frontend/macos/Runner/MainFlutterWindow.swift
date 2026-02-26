import Cocoa
import FlutterMacOS

// 메인 Flutter 윈도우 -- 최소 크기 및 초기 크기를 설정한다.
class MainFlutterWindow: NSWindow {
  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()

    // 윈도우 초기 크기 설정 (700x600)
    let windowFrame = NSRect(x: 0, y: 0, width: 700, height: 600)
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)

    // 화면 중앙에 배치
    self.center()

    // 윈도우 최소 크기 설정 (600x500)
    self.minSize = NSSize(width: 600, height: 500)

    // 타이틀 바 스타일 설정 -- 더 모던한 느낌
    self.titlebarAppearsTransparent = false
    self.titleVisibility = .visible

    RegisterGeneratedPlugins(registry: flutterViewController)

    super.awakeFromNib()
  }
}
