import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A list edited as chips: × removes one, typing and Enter adds one
// (several at once when separated by commas).
ColumnLayout {
  id: editor

  property var values: []
  property bool numeric: false
  property bool enabledEdit: true
  property string placeholder: ""
  signal commit(var values)

  readonly property color fg: Commons.Color.foreground

  spacing: Style.space(6)

  function add(text) {
    var parts = String(text).split(",")
    var out = values ? values.slice() : []
    for (var i = 0; i < parts.length; i++) {
      var raw = parts[i].trim()
      if (raw === "") continue
      var v = numeric ? Number(raw) : raw
      if (numeric && !isFinite(v)) continue
      if (out.indexOf(v) === -1) out.push(v)
    }
    if (numeric) out.sort(function(a, b) { return b - a })
    if (JSON.stringify(out) !== JSON.stringify(values)) commit(out)
  }

  function removeAt(index) {
    var out = values.slice()
    out.splice(index, 1)
    commit(out)
  }

  Flow {
    Layout.fillWidth: true
    spacing: Style.space(6)

    Repeater {
      model: editor.values || []
      delegate: Rectangle {
        required property var modelData
        required property int index
        implicitWidth: chipRow.implicitWidth + Style.space(14)
        implicitHeight: Style.space(26)
        radius: height / 2
        color: Util.alpha(editor.fg, 0.07)
        border.width: 1
        border.color: Util.alpha(editor.fg, 0.14)

        Row {
          id: chipRow
          anchors.centerIn: parent
          spacing: Style.space(6)
          Text {
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: String(modelData)
            color: editor.fg
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            visible: editor.enabledEdit
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "\u00d7"
            color: Util.alpha(editor.fg, removeMouse.containsMouse ? 1 : 0.45)
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            MouseArea {
              id: removeMouse
              anchors.fill: parent
              anchors.margins: -Style.space(4)
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: editor.removeAt(index)
            }
          }
        }
      }
    }

    TextField {
      id: input
      visible: editor.enabledEdit
      width: Style.space(editor.numeric ? 120 : 200)
      height: Style.space(26)
      placeholderText: editor.placeholder
      font.pixelSize: Style.font.bodySmall
      verticalPadding: Style.space(3)
      inputMethodHints: editor.numeric ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
      onAccepted: { editor.add(text); text = "" }
      onEditingFinished: if (text.trim() !== "") { editor.add(text); text = "" }
    }
  }
}
