import QtQuick
import qs.Commons
import qs.Commons as Commons

// A tear-off calendar leaf: the day large, the month small. Charges due
// today or tomorrow are drawn inverted, which reads at a glance even in
// monochrome themes.
Rectangle {
  id: tile

  property int day: 1
  property string month: ""
  property bool urgent: false
  property bool soon: false

  readonly property color fg: Commons.Color.foreground
  readonly property color ink: urgent ? Commons.Color.background : fg

  implicitWidth: Style.space(40)
  implicitHeight: Style.space(40)
  radius: Math.max(2, Style.cornerRadius * 0.75)
  color: urgent ? fg : Util.alpha(fg, soon ? 0.1 : 0.05)
  border.width: urgent ? 0 : 1
  border.color: Util.alpha(fg, soon ? 0.32 : 0.12)

  Column {
    anchors.centerIn: parent
    spacing: -Style.space(1)
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: tile.day
      color: tile.ink
      font.family: Style.font.family
      font.pixelSize: Style.font.title
      font.weight: Font.Bold
      font.features: ({ "tnum": 1 })
    }
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: tile.month
      color: Util.alpha(tile.ink, tile.urgent ? 0.75 : 0.5)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption - 1
      font.capitalization: Font.AllUppercase
      font.letterSpacing: 0.8
    }
  }
}
