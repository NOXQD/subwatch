import QtQuick
import qs.Commons
import qs.Commons as Commons

// Monthly spending as columns. The current month is solid, past months are
// quieter and a forecast month is only outlined.
Item {
  id: chart

  property var items: []        // [{label, value, amount, current, forecast}]
  property real chartHeight: Style.space(64)
  property bool showValues: false
  property int hovered: -1

  readonly property real maxValue: {
    var m = 0
    for (var i = 0; i < items.length; i++) m = Math.max(m, items[i].value || 0)
    return m
  }
  readonly property color fg: Commons.Color.foreground

  implicitHeight: chartHeight + labels.implicitHeight + Style.space(6) + (showValues ? valueRow.height : 0)

  Item {
    id: valueRow
    visible: chart.showValues
    width: parent.width
    height: visible ? Style.font.caption + Style.space(4) : 0
  }

  Row {
    id: cols
    y: valueRow.height
    width: parent.width
    height: chart.chartHeight
    spacing: Style.space(6)
    readonly property real colWidth: chart.items.length
      ? (width - spacing * (chart.items.length - 1)) / chart.items.length : 0

    Repeater {
      model: chart.items
      delegate: Item {
        id: col
        required property var modelData
        required property int index
        width: cols.colWidth
        height: cols.height
        readonly property bool hot: chart.hovered === index

        Text {
          visible: chart.showValues && (col.hot || col.modelData.current)
          anchors.horizontalCenter: parent.horizontalCenter
          anchors.bottom: bar.top
          anchors.bottomMargin: Style.space(3)
          textFormat: Text.PlainText
          text: col.modelData.amount
          color: Util.alpha(chart.fg, col.hot ? 1 : 0.7)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.features: ({ "tnum": 1 })
        }

        Rectangle {
          id: bar
          anchors.bottom: parent.bottom
          anchors.horizontalCenter: parent.horizontalCenter
          width: Math.min(parent.width, Math.max(Style.space(10), parent.width * 0.62))
          height: chart.maxValue > 0
            ? Math.max(2, (parent.height - (chart.showValues ? Style.font.caption + Style.space(6) : 0))
                          * (col.modelData.value || 0) / chart.maxValue)
            : 2
          radius: Math.min(Style.cornerRadius, width / 3)
          color: col.modelData.forecast ? "transparent"
            : Util.alpha(chart.fg, col.modelData.current ? 0.95 : (col.hot ? 0.55 : 0.28))
          border.width: col.modelData.forecast ? 1 : 0
          border.color: Util.alpha(chart.fg, 0.45)
          Behavior on height { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
          Behavior on color { ColorAnimation { duration: 120 } }
        }

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          onContainsMouseChanged: chart.hovered = containsMouse ? col.index : (chart.hovered === col.index ? -1 : chart.hovered)
        }
      }
    }
  }

  Row {
    id: labels
    anchors.top: cols.bottom
    anchors.topMargin: Style.space(6)
    width: parent.width
    spacing: cols.spacing
    Repeater {
      model: chart.items
      delegate: Text {
        required property var modelData
        required property int index
        width: cols.colWidth
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: modelData.label
        color: Util.alpha(chart.fg, modelData.current || chart.hovered === index ? 0.9 : 0.42)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        font.capitalization: Font.AllLowercase
        elide: Text.ElideRight
      }
    }
  }
}
