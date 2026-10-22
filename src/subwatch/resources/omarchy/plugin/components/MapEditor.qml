import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Key → number pairs, e.g. manual exchange rates.
ColumnLayout {
  id: editor

  property var value: ({})
  property bool enabledEdit: true
  property string keyPlaceholder: ""
  property string valuePlaceholder: ""
  signal commit(var value)

  readonly property var keys: Object.keys(value || {}).sort()

  spacing: Style.space(6)

  function setKey(oldKey, newKey, number) {
    var out = {}
    for (var k in value) if (k !== oldKey) out[k] = value[k]
    newKey = String(newKey).trim().toUpperCase()
    var n = Number(String(number).replace(",", ".").replace(/\s/g, ""))
    if (newKey !== "" && isFinite(n) && n > 0) out[newKey] = n
    commit(out)
  }

  Repeater {
    model: editor.keys
    delegate: RowLayout {
      required property string modelData
      Layout.fillWidth: true
      spacing: Style.space(6)
      TextField {
        id: keyField
        Layout.preferredWidth: Style.space(80)
        text: modelData
        enabled: editor.enabledEdit
        font.capitalization: Font.AllUppercase
        onEditingFinished: if (text.trim().toUpperCase() !== modelData) editor.setKey(modelData, text, valueField.text)
      }
      TextField {
        id: valueField
        Layout.fillWidth: true
        text: String(editor.value[modelData])
        enabled: editor.enabledEdit
        onEditingFinished: if (Number(text.replace(",", ".")) !== Number(editor.value[modelData])) editor.setKey(modelData, keyField.text, text)
      }
      Button {
        visible: editor.enabledEdit
        iconText: "×"
        onClicked: editor.setKey(modelData, "", 0)
      }
    }
  }

  RowLayout {
    visible: editor.enabledEdit
    Layout.fillWidth: true
    spacing: Style.space(6)
    TextField {
      id: newKey
      Layout.preferredWidth: Style.space(80)
      placeholderText: editor.keyPlaceholder
      font.capitalization: Font.AllUppercase
    }
    TextField {
      id: newValue
      Layout.fillWidth: true
      placeholderText: editor.valuePlaceholder
      onAccepted: addButton.clicked()
    }
    Button {
      id: addButton
      iconText: "\u{F0415}"
      bordered: true
      onClicked: {
        if (newKey.text.trim() === "") return
        editor.setKey("", newKey.text, newValue.text)
        newKey.text = ""
        newValue.text = ""
      }
    }
  }
}
