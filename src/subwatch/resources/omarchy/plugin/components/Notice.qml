import QtQuick
import qs.Commons
import qs.Commons as Commons

// Short messages at the bottom of the window. Errors stay longer and wear
// the theme's urgent colour.
Rectangle {
  id: notice

  property bool error: false

  function show(text, isError) {
    label.text = text
    error = isError
    hideTimer.interval = isError ? 7000 : 3200
    hideTimer.restart()
    shown = true
  }

  property bool shown: false

  readonly property color fg: Commons.Color.foreground

  implicitWidth: Math.min(label.implicitWidth + Style.space(36), Style.space(640))
  implicitHeight: label.implicitHeight + Style.space(20)
  width: implicitWidth
  height: implicitHeight
  radius: Style.cornerRadius
  color: Commons.Color.background
  border.width: 1
  border.color: error ? Commons.Color.urgent : Util.alpha(fg, 0.35)
  opacity: shown ? 1 : 0
  visible: opacity > 0
  scale: shown ? 1 : 0.97
  Behavior on opacity { NumberAnimation { duration: 180 } }
  Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

  Text {
    id: label
    anchors.centerIn: parent
    width: Math.min(implicitWidth, Style.space(600))
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    horizontalAlignment: Text.AlignHCenter
    color: notice.error ? Commons.Color.urgent : notice.fg
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Timer {
    id: hideTimer
    onTriggered: notice.shown = false
  }

  MouseArea {
    anchors.fill: parent
    onClicked: notice.shown = false
  }
}
