import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// One setting: what it is, what it does, and its control. Changes are saved
// straight into config.toml; a rejected value stays on screen with the
// reason underneath.
Item {
  id: row

  property var app: null
  property var field: ({})
  property bool first: false
  property string error: ""
  property bool saving: false

  readonly property color fg: Commons.Color.foreground
  readonly property bool wide: control.wide

  implicitHeight: layout.implicitHeight + Style.space(26)

  function save(value) {
    if (!app) return
    error = ""
    saving = true
    app.request("set", { path: field.path, value: value }, function(ok, data, hint) {
      row.saving = false
      if (!ok) {
        row.error = data || ""
        row.field = JSON.parse(JSON.stringify(row.field))
        return
      }
      row.field = data.field
      var note = app.tr("saved")
      if (data.effects && data.effects.length) note += "\n" + data.effects.join("\n")
      app.toast(note, false)
    })
  }

  function reset() {
    if (!app) return
    app.request("reset", { path: field.path }, function(ok, data) {
      if (!ok) { row.error = data || ""; return }
      row.error = ""
      row.field = data.field
      app.toast(app.tr("reset_done"), false)
    })
  }

  Hairline {
    visible: !row.first
    width: parent.width
    strength: 0.07
  }

  GridLayout {
    id: layout
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    anchors.leftMargin: Style.space(16)
    anchors.rightMargin: Style.space(16)
    columns: row.wide ? 1 : 2
    columnSpacing: Style.space(24)
    rowSpacing: Style.space(10)

    ColumnLayout {
      Layout.fillWidth: true
      Layout.alignment: Qt.AlignVCenter
      spacing: Style.space(3)

      RowLayout {
        spacing: Style.space(8)
        Label {
          text: row.field.label || ""
          font.weight: Font.Medium
        }
        Rectangle {
          visible: !!row.field.changed && !row.field.locked
          implicitWidth: Style.space(6)
          implicitHeight: Style.space(6)
          radius: width / 2
          color: Util.alpha(row.fg, 0.6)
        }
        Text {
          visible: !!row.field.changed && !row.field.locked
          textFormat: Text.PlainText
          text: "↺"
          color: Util.alpha(row.fg, resetMouse.containsMouse ? 1 : 0.4)
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          MouseArea {
            id: resetMouse
            anchors.fill: parent
            anchors.margins: -Style.space(4)
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: row.reset()
          }
          ToolTipText { shown: resetMouse.containsMouse; text: row.app ? row.app.tr("reset_default") : "" }
        }
      }
      Label {
        visible: (row.field.help || "") !== ""
        Layout.fillWidth: true
        text: row.field.help || ""
        tone: 0.45
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
        font.pixelSize: Style.font.bodySmall
        lineHeight: 1.15
      }
      Label {
        visible: !!row.field.locked
        Layout.fillWidth: true
        text: row.field.origin_text || ""
        tone: 0.7
        font.pixelSize: Style.font.caption
        font.italic: true
      }
      Label {
        visible: row.error !== ""
        Layout.fillWidth: true
        text: row.error
        color: Commons.Color.urgent
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
        font.pixelSize: Style.font.bodySmall
      }
    }

    FieldControl {
      id: control
      Layout.alignment: row.wide ? Qt.AlignLeft : (Qt.AlignRight | Qt.AlignVCenter)
      Layout.fillWidth: row.wide
      field: row.field
      strings: row.app ? row.app.strings : ({})
      opacity: row.saving ? 0.6 : 1
      onCommit: function(v) { row.save(v) }
    }
  }

  component ToolTipText: Rectangle {
    property bool shown: false
    property string text: ""
    visible: shown && text !== ""
    y: -height - Style.space(4)
    implicitWidth: tipText.implicitWidth + Style.space(12)
    implicitHeight: tipText.implicitHeight + Style.space(6)
    color: Commons.Color.background
    border.width: 1
    border.color: Util.alpha(Commons.Color.foreground, 0.3)
    radius: Style.cornerRadius / 2
    z: 10
    Text {
      id: tipText
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: parent.text
      color: Commons.Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }
}
