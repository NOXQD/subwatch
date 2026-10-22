import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A list of small tables (reminder rules, category rules, IMAP accounts).
// Edits stay local until "Save", because a half-filled rule may not be
// valid yet.
ColumnLayout {
  id: editor

  property var field: ({})
  property var records: []
  property var strings: ({})
  property bool enabledEdit: true
  property var draft: []
  property bool dirty: false
  signal commit(var records)

  readonly property color fg: Commons.Color.foreground

  function tr(key) { return strings && strings[key] !== undefined ? strings[key] : "" }

  function copy(v) { return JSON.parse(JSON.stringify(v === undefined ? null : v)) }

  function resetDraft() {
    draft = copy(records || [])
    dirty = false
  }

  onRecordsChanged: resetDraft()
  Component.onCompleted: resetDraft()

  function setValue(index, name, value) {
    var next = copy(draft)
    next[index][name] = value
    draft = next
    dirty = true
  }

  function addRecord() {
    var item = {}
    var fields = field.item_fields || []
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i]
      var key = f.path.split(".").pop()
      item[key] = copy(f.default)
    }
    var next = copy(draft)
    next.push(item)
    draft = next
    dirty = true
  }

  function removeRecord(index) {
    var next = copy(draft)
    next.splice(index, 1)
    draft = next
    dirty = true
  }

  function cleaned() {
    var out = []
    for (var i = 0; i < draft.length; i++) {
      var rec = {}
      for (var k in draft[i]) {
        var v = draft[i][k]
        if (v === null || v === undefined) continue
        rec[k] = v
      }
      out.push(rec)
    }
    return out
  }

  spacing: Style.space(10)

  Label {
    visible: editor.draft.length === 0
    text: editor.tr("records_empty")
    tone: 0.45
    font.italic: true
  }

  Repeater {
    model: editor.draft
    delegate: Rectangle {
      id: recordCard
      required property var modelData
      required property int index
      Layout.fillWidth: true
      implicitHeight: recordCol.implicitHeight + Style.space(20)
      radius: Style.cornerRadius
      color: Util.alpha(editor.fg, 0.03)
      border.width: 1
      border.color: Util.alpha(editor.fg, 0.12)

      ColumnLayout {
        id: recordCol
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Style.space(10)
        spacing: Style.space(8)

        RowLayout {
          Layout.fillWidth: true
          Caps {
            Layout.fillWidth: true
            text: "#" + (recordCard.index + 1) + "  " + (recordCard.modelData.name || recordCard.modelData.category
                  || recordCard.modelData.tag || "")
          }
          Button {
            visible: editor.enabledEdit
            iconText: "\u{F0A7A}"
            tooltipText: editor.tr("remove")
            onClicked: editor.removeRecord(recordCard.index)
          }
        }

        GridLayout {
          Layout.fillWidth: true
          columns: 2
          columnSpacing: Style.space(14)
          rowSpacing: Style.space(8)

          Repeater {
            model: editor.field.item_fields || []
            delegate: ColumnLayout {
              id: cell
              required property var modelData
              readonly property string key: modelData.path.split(".").pop()
              Layout.fillWidth: true
              Layout.preferredWidth: 1
              Layout.columnSpan: control.wide ? 2 : 1
              spacing: Style.space(4)
              Label {
                text: cell.modelData.label
                tone: 0.6
                font.pixelSize: Style.font.caption
              }
              FieldControl {
                id: control
                Layout.fillWidth: wide
                field: cell.modelData
                value: recordCard.modelData[cell.key] === undefined ? null : recordCard.modelData[cell.key]
                strings: editor.strings
                locked: !editor.enabledEdit
                onCommit: function(v) { editor.setValue(recordCard.index, cell.key, v) }
              }
            }
          }
        }
      }
    }
  }

  RowLayout {
    visible: editor.enabledEdit
    spacing: Style.space(8)
    Button {
      text: editor.tr("add_record")
      iconText: "\u{F0415}"
      bordered: true
      onClicked: editor.addRecord()
    }
    Item { Layout.fillWidth: true }
    Button {
      visible: editor.dirty
      text: editor.tr("revert")
      onClicked: editor.resetDraft()
    }
    PrimaryButton {
      visible: editor.dirty
      text: editor.tr("save")
      onClicked: editor.commit(editor.cleaned())
    }
  }
}
