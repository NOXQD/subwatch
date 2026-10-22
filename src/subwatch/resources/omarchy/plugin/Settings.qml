import QtQuick
import Quickshell
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

  FloatingWindow {
    id: window
    title: "Subwatch"
    color: Commons.Color.background
    implicitWidth: 1180
    implicitHeight: 780
    minimumSize: Qt.size(920, 580)
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
