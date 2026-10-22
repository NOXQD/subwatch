import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons

// A row in the window's sidebar.
Rectangle {
  id: item

  property string icon: ""
  property string text: ""
  property string badge: ""
  property bool badgeStrong: false
  property bool selected: false
  signal clicked()

  readonly property color fg: Commons.Color.foreground

  implicitHeight: Style.space(32)
  radius: Style.cornerRadius
  color: selected ? Util.alpha(fg, 0.1) : (mouse.containsMouse ? Util.alpha(fg, 0.05) : "transparent")
  Behavior on color { ColorAnimation { duration: 110 } }

  Rectangle {
    visible: item.selected
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    width: 2
    height: parent.height * 0.5
    radius: 1
    color: item.fg
  }

  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: Style.space(12)
    anchors.rightMargin: Style.space(8)
    spacing: Style.space(10)

    Text {
      textFormat: Text.PlainText
      text: item.icon
      color: Util.alpha(item.fg, item.selected ? 1 : 0.55)
      font.family: Style.font.family
      font.pixelSize: Style.font.icon
      Layout.preferredWidth: Style.space(18)
      horizontalAlignment: Text.AlignHCenter
    }
    Text {
      Layout.fillWidth: true
      textFormat: Text.PlainText
      text: item.text
      color: Util.alpha(item.fg, item.selected ? 1 : 0.75)
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      font.weight: item.selected ? Font.DemiBold : Font.Normal
      elide: Text.ElideRight
    }
    Pill {
      visible: item.badge !== ""
      text: item.badge
      strong: item.badgeStrong
      tone: 0.06
    }
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: item.clicked()
  }
}
