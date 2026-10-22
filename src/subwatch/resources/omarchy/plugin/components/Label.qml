import QtQuick
import qs.Commons
import qs.Commons as Commons

// Body text in the shell font. `tone`: 1 primary, 0.6 secondary, 0.4 quiet.
Text {
  property real tone: 1
  property bool numeric: false
  textFormat: Text.PlainText
  color: Util.alpha(Commons.Color.foreground, tone)
  font.family: Style.font.family
  font.pixelSize: Style.font.body
  font.features: numeric ? ({ "tnum": 1 }) : ({})
  elide: Text.ElideRight
}
