import QtQuick
import qs.Commons
import qs.Commons as Commons

Rectangle {
  property real strength: 0.1
  implicitHeight: 1
  color: Util.alpha(Commons.Color.foreground, strength)
}
