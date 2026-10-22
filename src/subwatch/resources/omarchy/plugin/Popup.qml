import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// The popup under the bar widget. Layout lives in PopupContent.qml; this
// file only hooks it into the bar's popout machinery and the keyboard.
Panel {
  id: root
  moduleName: "noxqd.subwatch"
  ipcTarget: "noxqd.subwatch"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property int cursor: -1

  readonly property var barIdentity: hostWidget || root
  readonly property var info: hostWidget ? hostWidget.info : null
  readonly property int rows: info && info.upcoming
    ? Math.min(info.upcoming.length, info.upcoming_rows || 5) : 0

  property real reveal: 1
  NumberAnimation { id: revealAnim; target: root; property: "reveal"; from: 0; to: 1; duration: 260; easing.type: Easing.OutCubic }
  onOpenedChanged: if (opened) { cursor = -1; revealAnim.restart() }

  function open() {
    setCenterHoverRevealSuppressed(false)
    root.controller.show()
  }

  function openFromHotkey() {
    root.controller.show()
    Qt.callLater(function() {
      if (root.opened) setCenterHoverRevealSuppressed(true)
    })
  }

  function close() {
    setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.openFromHotkey()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && typeof root.bar.setCenterHoverRevealSuppressed === "function")
      root.bar.setCenterHoverRevealSuppressed(value)
  }

  function move(delta) {
    if (rows === 0) return
    cursor = cursor < 0 ? (delta > 0 ? 0 : rows - 1) : Math.max(0, Math.min(rows - 1, cursor + delta))
  }

  function activate() {
    if (!hostWidget) return
    if (cursor >= 0 && info && info.upcoming[cursor])
      hostWidget.openSettings("subscriptions", { sub_id: info.upcoming[cursor].id })
    else
      hostWidget.openSettings("overview", null)
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(430))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) { root.move(dy !== 0 ? dy : dx) }
      onActivateRequested: root.activate()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        var key = String(text || "")
        if (!root.hostWidget) return
        if (key === "a") root.hostWidget.openSettings("subscriptions", { action: "add" })
        else if (key === "s" || key === ",") root.hostWidget.openSettings("overview", null)
        else if (key === "r") root.hostWidget.scan()
        else if (key === "t") root.hostWidget.openTui()
        else if (key === "j") root.move(1)
        else if (key === "k") root.move(-1)
      }

      // Scrolls when the card is taller than the screen allows.
      Flickable {
        id: scroller
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        interactive: contentHeight > height + 1
        boundsBehavior: Flickable.StopAtBounds

        PopupContent {
          id: content
          width: scroller.width
          info: root.info
          palette: root.hostWidget ? root.hostWidget.palette : ({})
          scanning: root.hostWidget ? root.hostWidget.scanning : false
          cursor: root.cursor
          opacity: root.reveal
          transform: Translate { y: (1 - root.reveal) * Style.space(6) }
          onOpenSettings: function(page, extra) { if (root.hostWidget) root.hostWidget.openSettings(page, extra) }
          onScanRequested: if (root.hostWidget) root.hostWidget.scan()
          onTuiRequested: if (root.hostWidget) root.hostWidget.openTui()
        }
      }
    }
  }
}
