// Native window for the printer app: runs server.py and shows its page.
import Cocoa
import WebKit

let appURL = URL(string: "http://localhost:8765/")!

class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    let server = Process()
    var attempts = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        webView.uiDelegate = self
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1040, height: 780),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Thermal Printer"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = .black
        webView.setValue(false, forKey: "drawsBackground")
        window.minSize = NSSize(width: 420, height: 480)
        window.contentView = webView
        window.setFrameAutosaveName("Main")
        window.center()
        window.makeKeyAndOrderFront(nil)
        startServer()
        waitForServer()
    }

    func startServer() {
        let script = Bundle.main.resourceURL!.appendingPathComponent("app/server.py")
        server.executableURL = Bundle.main.resourceURL!.appendingPathComponent("python/bin/python3")
        server.arguments = [script.path, "--no-browser"]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        server.environment = environment
        do {
            try server.run()
        } catch {
            fail("The printer service couldn't start. Try reinstalling the app.")
        }
    }

    func waitForServer() {
        URLSession.shared.dataTask(with: appURL.appendingPathComponent("jobs")) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.webView.load(URLRequest(url: appURL))
                } else if self.attempts < 150 {
                    self.attempts += 1
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.waitForServer() }
                } else {
                    self.fail("The printer service didn't respond. Quit and open the app again.")
                }
            }
        }.resume()
    }

    func fail(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Thermal Printer"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }

    func buildMenu() {
        let main = NSMenu()
        let app = NSMenu()
        app.addItem(withTitle: "Quit Thermal Printer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        main.addItem(withTitle: "", action: nil, keyEquivalent: "").submenu = app
        // Without an Edit menu, copy and paste shortcuts don't reach the page.
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        main.addItem(withTitle: "Edit", action: nil, keyEquivalent: "").submenu = edit
        let view = NSMenu(title: "Window")
        view.addItem(withTitle: "Minimize", action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        view.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        main.addItem(withTitle: "Window", action: nil, keyEquivalent: "").submenu = view
        NSApp.mainMenu = main
    }

    // The page's file picker.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.begin { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    // Links that open a new tab go to the default browser.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        if server.isRunning { server.terminate() }
    }
}

let delegate = AppDelegate()
NSApplication.shared.delegate = delegate
NSApp.setActivationPolicy(.regular)
NSApp.activate(ignoringOtherApps: true)
NSApp.run()
