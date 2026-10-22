import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons

Rectangle {
  id: tile

  property string title: ""
  property string value: ""
  property string note: ""
  property real fraction: -1
  property bool alert: false

  readonly property color fg: Commons.Color.foreground

  implicitHeight: col.implicitHeight + Style.space(28)
  radius: Style.cornerRadius
  color: Util.alpha(fg, 0.03)
  border.width: 1
  border.color: alert ? Commons.Color.urgent : Util.alpha(fg, 0.1)

  ColumnLayout {
    id: col
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    anchors.margins: Style.space(16)
    spacing: Style.space(6)

    Caps { text: tile.title }
    Label {
      Layout.fillWidth: true
      text: tile.value
      numeric: true
      font.pixelSize: Style.font.display
      font.weight: Font.Medium
      fontSizeMode: Text.HorizontalFit
      minimumPixelSize: Style.font.title
    }
    Item {
      visible: tile.fraction >= 0
      Layout.fillWidth: true
      implicitHeight: Style.space(4)
      Rectangle { anchors.fill: parent; radius: height / 2; color: Util.alpha(tile.fg, 0.1) }
      Rectangle {
        height: parent.height
        width: parent.width * Math.max(0, Math.min(1, tile.fraction))
        radius: height / 2
        color: tile.alert ? Commons.Color.urgent : tile.fg
        Behavior on width { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
      }
    }
    Label {
      Layout.fillWidth: true
      text: tile.note
      tone: tile.alert ? 0.85 : 0.45
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
      elide: Text.ElideNone
      maximumLineCount: 2
    }
  }
}
