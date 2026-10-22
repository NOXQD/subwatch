import QtQuick
import qs.Commons
import qs.Commons as Commons

// A small rounded label. `strong` inverts it for things that need eyes.
Rectangle {
  id: pill

  property string text: ""
  property bool strong: false
  property real tone: 0.08

  readonly property color fg: Commons.Color.foreground

  implicitWidth: label.implicitWidth + Style.space(12)
  implicitHeight: label.implicitHeight + Style.space(4)
  radius: height / 2
  color: strong ? fg : Util.alpha(fg, tone)
  border.width: strong ? 0 : 1
  border.color: Util.alpha(fg, 0.12)

  Text {
    id: label
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: pill.text
    color: pill.strong ? Commons.Color.background : Util.alpha(pill.fg, 0.85)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.weight: Font.DemiBold
    font.features: ({ "tnum": 1 })
  }
}
