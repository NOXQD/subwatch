import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "components"
import "Env.js" as Env
import "Palette.js" as Palette

// Subwatch on the Omarchy bar: the dial and the nearest charge (or the
// monthly total). Left click opens the popup, right click the full window,
// middle click scans the mail.
BarWidget {
  id: root
  moduleName: "noxqd.subwatch"

  property var info: null
  property var palette: ({})
  property bool scanning: false

  readonly property var widget: info && info.widget ? info.widget : null
  readonly property string label: widget ? widget.label : ""
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  // ---------------------------------------------------------------- data

  function refresh() {
    if (!fetch.running) fetch.running = true
  }

  Process {
    id: fetch
    command: [Env.exe, "bar", "--format", "panel"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          root.info = JSON.parse(text)
        } catch (e) {
          console.warn("subwatch: unreadable widget data")
        }
      }
    }
  }

  Timer {
    interval: Math.max(20, root.widget ? root.widget.interval : 300) * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  // Every change to subscriptions or settings touches this file.
  FileView {
    path: Env.cacheDir + "/changed"
    watchChanges: true
    printErrors: false
    onFileChanged: { reload(); root.refresh() }
  }

  FileView {
    path: Commons.Color.currentThemePath + "/colors.toml"
    watchChanges: true
    printErrors: false
    onLoaded: root.palette = Palette.parse(text())
    onFileChanged: reload()
  }

  // ------------------------------------------------------------- actions

  function openSettings(page, extra) {
    var payload = { page: page || "overview" }
    if (extra) for (var k in extra) payload[k] = extra[k]
    close()
    Quickshell.execDetached(["omarchy-shell", "shell", "summon", "noxqd.subwatch", JSON.stringify(payload)])
  }

  function scan() {
    if (scanning) return
    scanning = true
    Quickshell.execDetached(["sh", "-c",
      "systemctl --user start --no-block subwatch-scan.service 2>/dev/null || exec \"$0\" scan", Env.exe])
    scanWatch.start()
  }

  function openTui() {
    close()
    Quickshell.execDetached([Env.exe, "open"])
  }

  Timer {
    id: scanWatch
    interval: 2000
    repeat: true
    property int ticks: 0
    onRunningChanged: if (running) ticks = 0
    onTriggered: {
      ticks++
      if (!scanState.running) scanState.running = true
      if (ticks > 300) { stop(); root.scanning = false }
    }
  }

  Process {
    id: scanState
    command: ["systemctl", "--user", "is-active", "subwatch-scan.service"]
    stdout: StdioCollector {
      onStreamFinished: {
        var state = text.trim()
        if (scanWatch.ticks > 1 && state !== "active" && state !== "activating") {
          scanWatch.stop()
          root.scanning = false
          root.refresh()
        }
      }
    }
  }

  // --------------------------------------------------------------- popup

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  function open() {
    refresh()
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Popup.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "subwatch"
    function toggle(): void { root.refresh(); root.togglePanel() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function refresh(): void { root.refresh() }
  }

  // ----------------------------------------------------------------- bar

  visible: !(widget && widget.hide)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    labelVisible: false
    hasVisualContent: true
    active: !!(root.widget && root.widget.level === "over")
    fixedWidth: root.vertical ? -1 : content.implicitWidth + button.scaledHorizontalMargin * 2
    tooltipText: root.opened ? "" : (root.widget ? root.widget.tooltip : "Subwatch")

    onPressed: function(b) {
      if (b === Qt.RightButton) root.openSettings("overview", null)
      else if (b === Qt.MiddleButton) root.scan()
      else { root.refresh(); root.togglePanel() }
    }

    Row {
      id: content
      anchors.centerIn: parent
      spacing: Style.space(6)
      readonly property color ink: button.active && button.useActiveColor ? button.activeColor : button.foreground

      Ring {
        anchors.verticalCenter: parent.verticalCenter
        size: Math.round(button.fontSize * 1.15)
        value: root.widget ? root.widget.ring : 0
        dot: root.widget ? root.widget.alert : false
        color: content.ink
        thickness: Math.max(1.5, size * 0.14)
        RotationAnimation on rotation {
          running: root.scanning
          loops: Animation.Infinite
          from: 0; to: 360; duration: 1400
          onRunningChanged: if (!running) parent.rotation = 0
        }
      }

      Text {
        anchors.verticalCenter: parent.verticalCenter
        visible: !root.vertical && root.label !== ""
        textFormat: Text.PlainText
        text: root.label
        color: content.ink
        font.family: button.fontFamily
        font.pixelSize: button.fontSize
        font.features: ({ "tnum": 1 })
        renderType: Text.NativeRendering
      }
    }
  }
}
