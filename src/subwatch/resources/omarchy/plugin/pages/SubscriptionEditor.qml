import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"

// The add/edit form. Amounts and dates are typed the way people write them
// ("3 990 ₸", "25.10", "+1m", "9.99 USD"); the backend understands all of that.
Flickable {
  id: editor

  property var app: null
  property var item: null
  property bool adding: false
  property var form: null
  property var values: ({})
  property string error: ""
  property bool confirmDelete: false

  signal closed()
  signal saved(int id)
  signal removed()

  readonly property color fg: Commons.Color.foreground
  readonly property bool isNew: adding || !item || !item.id

  function tr(key) { return app ? app.tr(key) : "" }

  function load() {
    error = ""
    confirmDelete = false
    var it = item || {}
    values = {
      service: it.service || "",
      amount: it.amount_raw || "",
      currency: it.currency || (form ? form.base : ""),
      period: it.period_code || "1m",
      next: it.next_raw || "",
      category: it.category ? it.category.key : "",
      tags: it.tags || [],
      trial_until: it.trial_until || "",
      cancel_url: it.cancel_url || "",
      notes: it.notes || "",
      status: it.status || "active",
      track_usage: !!it.track_usage
    }
  }

  onItemChanged: load()
  onAddingChanged: load()

  function set(key, value) {
    var next = {}
    for (var k in values) next[k] = values[k]
    next[key] = value
    values = next
  }

  function periodOptions() {
    var base = form ? form.periods.slice() : []
    var known = false
    for (var i = 0; i < base.length; i++) if (base[i].value === values.period) known = true
    if (!known && item && item.period_code === values.period) base.push({ value: item.period_code, label: item.period })
    return base
  }

  function save() {
    error = ""
    var args = { values: values }
    if (!isNew) args.sub_id = item.id
    app.request("subscription_save", args, function(ok, data, hint) {
      if (!ok) { editor.error = data + (hint ? "\n" + hint : ""); return }
      app.toast(data.message, false)
      editor.saved(data.item.id)
    })
  }

  function action(name) {
    app.request("subscription_action", { sub_id: item.id, action: name }, function(ok, data) {
      if (!ok) { editor.error = data; return }
      app.toast(data.message, false)
      if (name === "remove") editor.removed()
      else editor.saved(item.id)
    })
  }

  clip: true
  contentHeight: col.implicitHeight + Style.space(10)
  boundsBehavior: Flickable.StopAtBounds

  ColumnLayout {
    id: col
    width: editor.width
    spacing: Style.space(12)

    RowLayout {
      Layout.fillWidth: true
      Label {
        Layout.fillWidth: true
        text: editor.isNew ? editor.tr("new_subscription") : (editor.item ? editor.item.service : "")
        font.pixelSize: Style.font.heading
        font.weight: Font.Bold
      }
      PanelActionButton {
        iconText: "\u{F0156}"
        foreground: editor.fg
        onClicked: editor.closed()
      }
    }

    // Facts we know but the form does not edit.
    Label {
      visible: !editor.isNew && !!editor.item
      Layout.fillWidth: true
      text: editor.item && editor.item.id
        ? [editor.item.source, editor.tr("confidence") + " " + editor.item.confidence + " %",
           editor.item.last ? editor.tr("last_charge") + " " + editor.item.last : ""].filter(function(x) { return x }).join("  ·  ")
        : ""
      tone: 0.45
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
      elide: Text.ElideNone
    }
    Label {
      visible: !!editor.item && !!editor.item.price_change
      Layout.fillWidth: true
      text: editor.item && editor.item.price_change ? "\u{F0535}  " + editor.item.price_change : ""
      tone: 0.75
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
      elide: Text.ElideNone
    }

    FormLabel { text: editor.tr("f_service") }
    TextField {
      Layout.fillWidth: true
      text: editor.values.service || ""
      placeholderText: "Netflix"
      onTextEdited: editor.set("service", text)
    }

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(10)
      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)
        FormLabel { text: editor.tr("f_amount") }
        TextField {
          Layout.fillWidth: true
          text: editor.values.amount || ""
          placeholderText: "3990"
          font.features: ({ "tnum": 1 })
          onTextEdited: editor.set("amount", text)
        }
      }
      ColumnLayout {
        spacing: Style.space(6)
        FormLabel { text: editor.tr("f_currency") }
        Dropdown {
          implicitWidth: Style.space(120)
          showLabel: false
          options: editor.form ? editor.form.currencies : []
          value: editor.values.currency || ""
          onChanged: function(v) { editor.set("currency", v) }
        }
      }
    }
    Label {
      Layout.fillWidth: true
      text: editor.form ? editor.form.amount_hint : ""
      tone: 0.35
      font.pixelSize: Style.font.caption
    }

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(10)
      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)
        FormLabel { text: editor.tr("f_period") }
        Dropdown {
          Layout.fillWidth: true
          showLabel: false
          options: editor.periodOptions()
          value: editor.values.period || "1m"
          onChanged: function(v) { editor.set("period", v) }
        }
      }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)
        FormLabel { text: editor.tr("f_category") }
        Dropdown {
          Layout.fillWidth: true
          showLabel: false
          options: editor.form ? editor.form.categories : []
          value: editor.values.category || ""
          onChanged: function(v) { editor.set("category", v) }
        }
      }
    }

    FormLabel { text: editor.tr("f_next") }
    TextField {
      Layout.fillWidth: true
      text: editor.values.next || ""
      placeholderText: editor.form ? editor.form.date_hint : ""
      onTextEdited: editor.set("next", text)
    }

    FormLabel { text: editor.tr("f_tags") }
    ChipsEditor {
      Layout.fillWidth: true
      values: editor.values.tags || []
      placeholder: editor.tr("type_and_enter")
      onCommit: function(v) { editor.set("tags", v) }
    }

    FormLabel { text: editor.tr("f_trial_until") }
    TextField {
      Layout.fillWidth: true
      text: editor.values.trial_until || ""
      placeholderText: editor.tr("optional")
      onTextEdited: editor.set("trial_until", text)
    }

    FormLabel { text: editor.tr("f_cancel_url") }
    TextField {
      Layout.fillWidth: true
      text: editor.values.cancel_url || ""
      placeholderText: "https://"
      onTextEdited: editor.set("cancel_url", text)
    }

    FormLabel { text: editor.tr("f_notes") }
    TextField {
      Layout.fillWidth: true
      text: editor.values.notes || ""
      onTextEdited: editor.set("notes", text)
    }

    RowLayout {
      Layout.fillWidth: true
      Layout.topMargin: Style.space(4)
      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(2)
        Label { text: editor.tr("f_track_usage") }
        Label {
          Layout.fillWidth: true
          text: editor.item && editor.item.last_used ? editor.tr("last_used") + " " + editor.item.last_used : editor.tr("track_usage_help")
          tone: 0.4
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          elide: Text.ElideNone
        }
      }
      ToggleSwitch {
        checked: !!editor.values.track_usage
        onToggled: editor.set("track_usage", !editor.values.track_usage)
      }
    }

    RowLayout {
      visible: !editor.isNew
      Layout.fillWidth: true
      spacing: Style.space(6)
      Repeater {
        model: editor.form ? editor.form.statuses : []
        delegate: Button {
          required property var modelData
          Layout.fillWidth: true
          text: modelData.label
          bordered: true
          selected: editor.values.status === modelData.value
          fontSize: Style.font.bodySmall
          onClicked: editor.set("status", modelData.value)
        }
      }
    }

    Label {
      visible: editor.error !== ""
      Layout.fillWidth: true
      text: editor.error
      color: Commons.Color.urgent
      wrapMode: Text.WordWrap
      elide: Text.ElideNone
    }

    RowLayout {
      Layout.fillWidth: true
      Layout.topMargin: Style.space(6)
      spacing: Style.space(8)
      PrimaryButton {
        Layout.fillWidth: true
        text: editor.isNew ? editor.tr("add") : editor.tr("save")
        enabled: (editor.values.service || "").trim() !== ""
        onClicked: editor.save()
      }
      Button {
        text: editor.tr("close")
        bordered: true
        onClicked: editor.closed()
      }
    }

    Hairline { visible: !editor.isNew; Layout.fillWidth: true; Layout.topMargin: Style.space(6) }

    Flow {
      visible: !editor.isNew
      Layout.fillWidth: true
      spacing: Style.space(6)
      Button {
        visible: !!editor.item && editor.item.status !== "cancelled"
        text: editor.item && editor.item.cancel_url ? editor.tr("cancel_and_open") : editor.tr("mark_cancelled")
        iconText: "\u{F0156}"
        bordered: true
        fontSize: Style.font.bodySmall
        onClicked: editor.action("cancel")
      }
      Button {
        visible: !!editor.item && editor.item.status === "active"
        text: editor.tr("pause")
        iconText: "\u{F03E4}"
        bordered: true
        fontSize: Style.font.bodySmall
        onClicked: editor.action("pause")
      }
      Button {
        visible: !!editor.item && editor.item.status !== "active"
        text: editor.tr("resume")
        iconText: "\u{F040A}"
        bordered: true
        fontSize: Style.font.bodySmall
        onClicked: editor.action("resume")
      }
      Button {
        visible: !!editor.item && editor.item.status === "active"
        text: editor.tr("used_today")
        iconText: "\u{F012C}"
        bordered: true
        fontSize: Style.font.bodySmall
        onClicked: editor.action("used")
      }
      Button {
        visible: !!editor.item && !!editor.item.cancel_url && editor.item.status === "cancelled"
        text: editor.tr("open_cancel_page")
        iconText: "\u{F03CC}"
        bordered: true
        fontSize: Style.font.bodySmall
        onClicked: editor.action("open_cancel_page")
      }
      Button {
        text: editor.confirmDelete ? editor.tr("delete_confirm") : editor.tr("delete")
        iconText: "\u{F0A7A}"
        bordered: true
        selected: editor.confirmDelete
        fontSize: Style.font.bodySmall
        onClicked: {
          if (editor.confirmDelete) editor.action("remove")
          else { editor.confirmDelete = true; deleteReset.restart() }
        }
      }
    }
  }

  Timer {
    id: deleteReset
    interval: 4000
    onTriggered: editor.confirmDelete = false
  }

  component FormLabel: Caps {
    Layout.topMargin: Style.space(4)
    font.pixelSize: Style.font.caption
  }
}
