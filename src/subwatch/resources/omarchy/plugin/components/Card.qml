import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons

// A titled group of rows.
ColumnLayout {
  id: card

  property string title: ""
  property string help: ""
  default property alias content: body.data

  readonly property color fg: Commons.Color.foreground

  spacing: 0

  Caps {
    visible: card.title !== ""
    Layout.fillWidth: true
    Layout.bottomMargin: Style.space(card.help !== "" ? 4 : 8)
    text: card.title
  }
  Label {
    visible: card.help !== ""
    Layout.fillWidth: true
    Layout.bottomMargin: Style.space(10)
    text: card.help
    tone: 0.45
    wrapMode: Text.WordWrap
    elide: Text.ElideNone
    font.pixelSize: Style.font.bodySmall
  }

  Rectangle {
    Layout.fillWidth: true
    implicitHeight: body.implicitHeight
    radius: Style.cornerRadius
    color: Util.alpha(card.fg, 0.025)
    border.width: 1
    border.color: Util.alpha(card.fg, 0.09)

    ColumnLayout {
      id: body
      width: parent.width
      spacing: 0
    }
  }
}
