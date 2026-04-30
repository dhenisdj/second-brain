import Cocoa
@preconcurrency import WebKit
import UniformTypeIdentifiers
import Darwin

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    private var port = 8765
    private var backendProcess: Process?
    private var window: NSWindow?
    private var webView: WKWebView?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)

        do {
            try startBackend()
            waitForBackend()
        } catch {
            showFatalError("Second Brain 启动失败", error.localizedDescription)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        backendProcess?.terminate()
        backendProcess = nil
    }

    private func startBackend() throws {
        guard let resourcesURL = Bundle.main.resourceURL else {
            throw AppError("无法定位 App 资源目录")
        }

        let backendURL = resourcesURL.appendingPathComponent("backend", isDirectory: true)
        let frontendURL = resourcesURL.appendingPathComponent("frontend", isDirectory: true)
        let pythonURL = backendURL.appendingPathComponent("venv/bin/python")

        guard FileManager.default.fileExists(atPath: pythonURL.path) else {
            throw AppError("未找到后端 Python 环境：\(pythonURL.path)")
        }
        guard FileManager.default.fileExists(atPath: frontendURL.appendingPathComponent("index.html").path) else {
            throw AppError("未找到前端构建产物：\(frontendURL.path)")
        }

        let appSupportURL = try appSupportDirectory()
        let credentialsURL = appSupportURL.appendingPathComponent("credentials", isDirectory: true)
        try FileManager.default.createDirectory(at: credentialsURL, withIntermediateDirectories: true)
        port = try chooseAvailablePort(preferred: 8765)

        let process = Process()
        process.executableURL = pythonURL
        process.currentDirectoryURL = backendURL
        process.arguments = [
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            String(port),
        ]

        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["SECOND_BRAIN_SERVE_FRONTEND"] = "1"
        environment["SECOND_BRAIN_FRONTEND_DIR"] = frontendURL.path
        environment["SECOND_BRAIN_CREDENTIALS_DIR"] = credentialsURL.path
        environment["DATABASE_URL"] = databaseURL(resourcesURL: resourcesURL, appSupportURL: appSupportURL)
        environment["PATH"] = "\(backendURL.appendingPathComponent("venv/bin").path):\(environment["PATH"] ?? "/usr/bin:/bin")"
        process.environment = environment

        let logURL = appSupportURL.appendingPathComponent("backend.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let logHandle = try FileHandle(forWritingTo: logURL)
        logHandle.seekToEndOfFile()
        process.standardOutput = logHandle
        process.standardError = logHandle

        try process.run()
        backendProcess = process
    }

    private func waitForBackend() {
        DispatchQueue.global(qos: .userInitiated).async {
            let healthURL = URL(string: "http://127.0.0.1:\(self.port)/api/settings")!
            for _ in 0..<80 {
                if self.requestSucceeds(healthURL) {
                    DispatchQueue.main.async {
                        self.openMainWindow()
                    }
                    return
                }
                Thread.sleep(forTimeInterval: 0.15)
            }

            DispatchQueue.main.async {
                self.showFatalError(
                    "Second Brain 启动超时",
                    "后端服务没有按预期启动。日志位置：~/Library/Application Support/Second Brain/backend.log"
                )
            }
        }
    }

    private func requestSucceeds(_ url: URL) -> Bool {
        var request = URLRequest(url: url)
        request.timeoutInterval = 0.5

        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: request) { _, response, _ in
            if let httpResponse = response as? HTTPURLResponse {
                ok = (200..<500).contains(httpResponse.statusCode)
            }
            semaphore.signal()
        }.resume()

        _ = semaphore.wait(timeout: .now() + 0.7)
        return ok
    }

    private func chooseAvailablePort(preferred: Int) throws -> Int {
        for candidate in preferred...(preferred + 100) {
            if canBindLocalPort(candidate) {
                return candidate
            }
        }
        throw AppError("无法找到可用本地端口，请退出旧的 Second Brain 进程后重试")
    }

    private func canBindLocalPort(_ candidate: Int) -> Bool {
        let socketFD = socket(AF_INET, SOCK_STREAM, 0)
        if socketFD < 0 {
            return false
        }
        defer { close(socketFD) }

        var reuse: Int32 = 1
        setsockopt(socketFD, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(candidate).bigEndian
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        return withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { socketAddress in
                Darwin.bind(socketFD, socketAddress, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }

    private func openMainWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.userContentController.add(self, name: "secondBrainNative")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        let cacheBuster = Int(Date().timeIntervalSince1970)
        let appURL = URL(string: "http://127.0.0.1:\(port)/?appBuild=\(cacheBuster)")!
        let request = URLRequest(url: appURL, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: 30)
        webView.load(request)
        self.webView = webView

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Second Brain"
        window.center()
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        self.window = window
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.allowedContentTypes = [.json]
        panel.prompt = "上传"
        panel.message = "选择 Google OAuth JSON 凭据文件"

        if let window {
            panel.beginSheetModal(for: window) { response in
                completionHandler(response == .OK ? panel.urls : nil)
            }
            return
        }

        completionHandler(panel.runModal() == .OK ? panel.urls : nil)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.allow)
            return
        }

        let host = url.host ?? ""
        if url.scheme?.hasPrefix("http") == true && host != "127.0.0.1" && host != "localhost" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }

        decisionHandler(.allow)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "secondBrainNative",
              let payload = message.body as? [String: Any],
              let type = payload["type"] as? String,
              type == "openExternal",
              let urlString = payload["url"] as? String,
              let url = URL(string: urlString) else {
            return
        }

        NSWorkspace.shared.open(url)
    }

    private func appSupportDirectory() throws -> URL {
        let baseURL = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let appURL = baseURL.appendingPathComponent("Second Brain", isDirectory: true)
        try FileManager.default.createDirectory(at: appURL, withIntermediateDirectories: true)
        return appURL
    }

    private func databaseURL(resourcesURL: URL, appSupportURL: URL) -> String {
        if let projectURL = projectRootURL(from: resourcesURL) {
            let candidates = [
                projectURL.appendingPathComponent(".local/private/database/second_brain.db"),
                projectURL.appendingPathComponent("backend/second_brain.db"),
            ]

            for candidate in candidates where FileManager.default.fileExists(atPath: candidate.path) {
                return "sqlite+aiosqlite:///\(candidate.path)"
            }
        }

        return "sqlite+aiosqlite:///\(appSupportURL.appendingPathComponent("second_brain.db").path)"
    }

    private func projectRootURL(from resourcesURL: URL) -> URL? {
        var url = resourcesURL
        for _ in 0..<5 {
            url.deleteLastPathComponent()
        }

        let frontendPackage = url.appendingPathComponent("frontend/package.json")
        let backendApp = url.appendingPathComponent("backend/app/main.py")
        guard FileManager.default.fileExists(atPath: frontendPackage.path),
              FileManager.default.fileExists(atPath: backendApp.path) else {
            return nil
        }
        return url
    }

    private func showFatalError(_ title: String, _ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = title
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }
}

struct AppError: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var errorDescription: String? {
        return message
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
