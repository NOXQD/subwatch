import QtQuick
import qs.Commons
import qs.Commons as Commons

// One horizontal bar split into category shares.
Item {
  id: bar

  property var items: []          // [{share: 0..1}]
  property var colors: []
  property real thickness: Style.space(8)
  property real gap: Style.space(2)
  property int highlighted: -1

  implicitHeight: thickness

  Row {
    id: row
    anchors.fill: parent
    spacing: bar.gap
    readonly property real usable: Math.max(0, bar.width - bar.gap * Math.max(0, bar.items.length - 1))

    Repeater {
      model: bar.items
      delegate: Rectangle {
        required property var modelData
        required property int index
        height: bar.thickness
        width: Math.max(bar.thickness * 0.5, row.usable * (modelData.share || 0))
        radius: Math.min(height / 2, Style.cornerRadius)
        color: bar.colors[index] || Commons.Color.foreground
        opacity: bar.highlighted < 0 || bar.highlighted === index ? 1 : 0.35
        Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 140 } }
      }
    }
  }
}
