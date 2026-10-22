import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons

// A charge in a list: calendar leaf, service, when, amount.
Rectangle {
  id: row

  property var item: ({})
  property string trialText: ""
  signal clicked()

  readonly property color fg: Commons.Color.foreground

  implicitHeight: layout.implicitHeight + Style.space(12)
  radius: Style.cornerRadius
  color: mouse.containsMouse ? Util.alpha(fg, 0.05) : "transparent"
  Behavior on color { ColorAnimation { duration: 100 } }

  RowLayout {
    id: layout
    anchors.fill: parent
    anchors.leftMargin: Style.space(6)
    anchors.rightMargin: Style.space(10)
    spacing: Style.space(12)

    DateTile {
      day: row.item.day || 1
      month: row.item.month || ""
      urgent: row.item.days <= 1
      soon: row.item.days <= 3
    }
    ColumnLayout {
      Layout.fillWidth: true
      spacing: Style.space(1)
      RowLayout {
        spacing: Style.space(6)
        Label { text: row.item.service || ""; font.weight: Font.DemiBold }
        Pill { visible: !!row.item.trial; text: row.trialText }
      }
      Label {
        Layout.fillWidth: true
        text: (row.item.relative || "") + "  ·  " + (row.item.category ? row.item.category.name : "")
        tone: row.item.days <= 1 ? 0.8 : 0.45
        font.pixelSize: Style.font.caption
      }
    }
    ColumnLayout {
      spacing: Style.space(1)
      Label { Layout.alignment: Qt.AlignRight; text: row.item.amount || ""; numeric: true; font.weight: Font.Medium }
      Label {
        Layout.alignment: Qt.AlignRight
        visible: !!row.item.converted
        text: "≈ " + (row.item.converted || "")
        numeric: true
        tone: 0.4
        font.pixelSize: Style.font.caption
      }
    }
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: row.clicked()
  }
}
