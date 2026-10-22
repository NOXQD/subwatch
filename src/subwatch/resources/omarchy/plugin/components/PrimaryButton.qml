import QtQuick
import qs.Commons
import qs.Commons as Commons

// The one solid button on a screen: foreground on background, inverted.
Rectangle {
  id: btn

  property string text: ""
  property string iconText: ""
  property bool busy: false
  signal clicked()

  readonly property color fg: Commons.Color.foreground

  implicitWidth: row.implicitWidth + Style.spacing.controlPaddingX * 2.4
  implicitHeight: Style.spacing.controlHeight
  radius: Style.cornerRadius
  color: fg
  opacity: !enabled ? 0.35 : (mouse.pressed ? 0.75 : (mouse.containsMouse ? 0.88 : 1))
  Behavior on opacity { NumberAnimation { duration: 100 } }

  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.spacing.controlGap
    Text {
      visible: btn.iconText !== ""
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: btn.iconText
      color: Commons.Color.background
      font.family: Style.font.family
      font.pixelSize: Style.font.icon
      RotationAnimation on rotation {
        running: btn.busy
        loops: Animation.Infinite
        from: 0; to: 360; duration: 900
        onRunningChanged: if (!running) parent.rotation = 0
      }
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: btn.text
      color: Commons.Color.background
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      font.weight: Font.DemiBold
    }
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    enabled: btn.enabled && !btn.busy
    onClicked: btn.clicked()
  }
}
