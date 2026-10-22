import QtQuick
import Quickshell
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons

// The full Subwatch window, summoned by the shell:
//   omarchy-shell shell summon noxqd.subwatch '{"page": "reminders"}'
// The shell loads this file on summon and unloads it on hide, so neither the
// window nor the `subwatch gui-server` process stays around while closed.
Item {
  id: root

  readonly property string pluginId: "noxqd.subwatch"

  property var shell: null
  property bool opened: false
  property bool closingFromHost: false

  function open(payloadJson) {
    closingFromHost = false
    opened = true
    window.visible = true
    var payload = null
    try {
      payload = payloadJson ? JSON.parse(String(payloadJson)) : null
    } catch (e) {
      payload = null
    }
    view.navigate(payload)
  }

  function close() {
    closingFromHost = true
    opened = false
    window.visible = false
    closingFromHost = false
  }

  function requestClose() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else close()
  }

  // Open on the monitor in focus, sized to it: big enough for two columns,
  // never taller than most of the screen.
  readonly property var targetScreen: {
    var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    for (var i = 0; i < Quickshell.screens.length; i++)
      if (Quickshell.screens[i].name === name) return Quickshell.screens[i]
    return Quickshell.screens.length ? Quickshell.screens[0] : null
  }

  FloatingWindow {
    id: window
    title: "Subwatch"
    color: Commons.Color.background
    screen: root.targetScreen
    implicitWidth: root.targetScreen ? Math.min(1180, Math.round(root.targetScreen.width * 0.86)) : 1100
    implicitHeight: root.targetScreen ? Math.min(800, Math.round(root.targetScreen.height * 0.86)) : 720
    minimumSize: Qt.size(Math.min(860, implicitWidth), Math.min(540, implicitHeight))
    visible: false

    onVisibleChanged: {
      if (!visible && !root.closingFromHost) root.requestClose()
    }

    SettingsView {
      id: view
      anchors.fill: parent
      onCloseRequested: root.requestClose()
    }
  }
}
