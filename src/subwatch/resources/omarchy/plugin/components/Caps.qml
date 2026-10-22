import QtQuick
import qs.Commons
import qs.Commons as Commons

// Small spaced capitals for section labels.
Text {
  textFormat: Text.PlainText
  color: Util.alpha(Commons.Color.foreground, 0.5)
  font.family: Style.font.family
  font.pixelSize: Style.font.caption
  font.capitalization: Font.AllUppercase
  font.letterSpacing: 1.4
  font.weight: Font.DemiBold
  elide: Text.ElideRight
}
