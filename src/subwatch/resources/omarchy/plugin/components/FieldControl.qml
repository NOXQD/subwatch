import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// The input for one setting, chosen by its kind. Emits `commit(value)` with
// a typed value; saving is the caller's business.
Loader {
  id: control

  property var field: ({})
  property var value: field ? field.value : null
  property var strings: ({})
  property bool locked: !!(field && field.locked)
  signal commit(var value)

  readonly property string kind: field && field.kind ? field.kind : "raw"
  readonly property bool wide: ["tags", "numbers", "multichoice", "map_number", "records", "raw"].indexOf(kind) !== -1
  readonly property color fg: Commons.Color.foreground

  function tr(key) { return strings && strings[key] !== undefined ? strings[key] : "" }

  function parseNumber(text) {
    var s = String(text).trim().replace(/\s/g, "").replace(",", ".")
    if (s === "") return field && field.nullable ? null : NaN
    return Number(s)
  }

  sourceComponent: {
    switch (kind) {
    case "bool": return boolControl
    case "choice": return choiceControl
    case "int":
    case "number": return numberControl
    case "text": return textControl
    case "tags": return tagsControl
    case "numbers": return numbersControl
    case "multichoice": return multiControl
    case "map_number": return mapControl
    case "records": return recordsControl
    default: return rawControl
    }
  }

  Component {
    id: boolControl
    ToggleSwitch {
      checked: control.value === true
      interactive: !control.locked
      onToggled: control.commit(!control.value)
    }
  }

  Component {
    id: choiceControl
    Dropdown {
      implicitWidth: Style.space(240)
      options: control.field.options || []
      value: String(control.value)
      showLabel: false
      enabled: !control.locked
      onChanged: function(v) { if (v !== String(control.value)) control.commit(v) }
    }
  }

  Component {
    id: numberControl
    TextField {
      implicitWidth: Style.space(160)
      horizontalAlignment: TextInput.AlignRight
      text: control.value === null || control.value === undefined ? "" : String(control.value)
      enabled: !control.locked
      inputMethodHints: Qt.ImhFormattedNumbersOnly
      font.features: ({ "tnum": 1 })
      onEditingFinished: {
        var n = control.parseNumber(text)
        if (n === null && control.value === null) return
        if (n !== null && (!isFinite(n) || n === Number(control.value))) {
          if (!isFinite(n)) text = control.value === null ? "" : String(control.value)
          return
        }
        control.commit(control.kind === "int" && n !== null ? Math.round(n) : n)
      }
    }
  }

  Component {
    id: textControl
    RowLayout {
      spacing: Style.space(8)
      Rectangle {
        visible: control.field.format === "color" && /^#[0-9a-fA-F]{6}$/.test(String(control.value))
        implicitWidth: Style.space(20)
        implicitHeight: Style.space(20)
        radius: Style.cornerRadius / 2
        color: visible ? String(control.value) : "transparent"
        border.width: 1
        border.color: Util.alpha(control.fg, 0.3)
      }
      Text {
        visible: control.field.format === "glyph" && String(control.value) !== ""
        textFormat: Text.PlainText
        text: String(control.value)
        color: control.fg
        font.family: Style.font.family
        font.pixelSize: Style.font.iconLarge
      }
      TextField {
        Layout.preferredWidth: control.field.format === "time" ? Style.space(100)
          : (control.field.format === "duration" ? Style.space(100) : Style.space(260))
        text: control.value === null || control.value === undefined ? "" : String(control.value)
        enabled: !control.locked
        placeholderText: control.field.format === "time" ? "09:00"
          : control.field.format === "duration" ? "4h"
          : control.field.format === "color" ? "#rrggbb" : ""
        onEditingFinished: {
          if (text === String(control.value === null || control.value === undefined ? "" : control.value)) return
          control.commit(text === "" && control.field.nullable ? null : text)
        }
      }
    }
  }

  Component {
    id: tagsControl
    ChipsEditor {
      values: control.value || []
      enabledEdit: !control.locked
      placeholder: control.tr("type_and_enter")
      onCommit: function(v) { control.commit(v) }
    }
  }

  Component {
    id: numbersControl
    ChipsEditor {
      values: control.value || []
      numeric: true
      enabledEdit: !control.locked
      placeholder: control.tr("type_number_enter")
      onCommit: function(v) { control.commit(v) }
    }
  }

  Component {
    id: multiControl
    Flow {
      spacing: Style.space(6)
      Repeater {
        model: control.field.options || []
        delegate: Button {
          required property var modelData
          readonly property bool on: (control.value || []).indexOf(modelData.value) !== -1
          text: modelData.label
          bordered: true
          selected: on
          enabled: !control.locked
          onClicked: {
            var out = (control.value || []).slice()
            var i = out.indexOf(modelData.value)
            if (i >= 0) out.splice(i, 1); else out.push(modelData.value)
            control.commit(out)
          }
        }
      }
    }
  }

  Component {
    id: mapControl
    MapEditor {
      value: control.value || ({})
      enabledEdit: !control.locked
      keyPlaceholder: "USD"
      valuePlaceholder: control.tr("rate_placeholder")
      onCommit: function(v) { control.commit(v) }
    }
  }

  // Loaded by URL: RecordsEditor itself uses FieldControl for its cells.
  Component {
    id: recordsControl
    Loader {
      id: records
      source: Qt.resolvedUrl("RecordsEditor.qml")
      Binding { target: records.item; property: "field"; value: control.field; when: records.item !== null }
      Binding { target: records.item; property: "records"; value: control.value || []; when: records.item !== null }
      Binding { target: records.item; property: "strings"; value: control.strings; when: records.item !== null }
      Binding { target: records.item; property: "enabledEdit"; value: !control.locked; when: records.item !== null }
      Connections {
        target: records.item
        ignoreUnknownSignals: true
        function onCommit(v) { control.commit(v) }
      }
    }
  }

  Component {
    id: rawControl
    Label {
      text: JSON.stringify(control.value)
      tone: 0.6
      wrapMode: Text.WrapAnywhere
      elide: Text.ElideNone
      font.pixelSize: Style.font.bodySmall
    }
  }
}
