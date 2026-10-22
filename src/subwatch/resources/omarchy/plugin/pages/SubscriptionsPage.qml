import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"

// Every subscription, a filter, and a form on the right to add or change one.
Item {
  id: page

  property var app: null
  property string pageId: ""
  property var model: null
  property string filter: "active"
  property string query: ""
  property var selected: null       // row being edited, or {} for a new one
  property bool adding: false
  property var pendingId: null

  readonly property color fg: Commons.Color.foreground
  readonly property var items: model ? model.items : []
  readonly property var shown: {
    var out = []
    var q = query.trim().toLowerCase()
    for (var i = 0; i < items.length; i++) {
      var it = items[i]
      if (filter === "active" && it.status !== "active") continue
      if (filter === "trial" && !it.trial) continue
      if (filter === "paused" && it.status !== "paused") continue
      if (filter === "cancelled" && it.status !== "cancelled") continue
      if (q !== "" && it.search.indexOf(q) === -1) continue
      out.push(it)
    }
    return out
  }

  function tr(key) { return app ? app.tr(key) : "" }

  function reload() {
    if (!app) return
    app.request("subscriptions", {}, function(ok, data) {
      if (!ok) return
      page.model = data
      if (page.pendingId !== null) {
        page.select(page.pendingId)
        page.pendingId = null
      } else if (page.selected && page.selected.id) {
        page.select(page.selected.id)
      }
    })
  }

  function applyExtra(extra) {
    if (!extra) return
    if (extra.action === "add") startAdding()
    else if (extra.sub_id) {
      if (model) select(extra.sub_id)
      else pendingId = extra.sub_id
    }
  }

  function select(id) {
    for (var i = 0; i < items.length; i++) {
      if (items[i].id === id) {
        adding = false
        selected = items[i]
        if (filter !== "all" && shown.indexOf(items[i]) === -1) filter = "all"
        return
      }
    }
    selected = null
  }

  function startAdding() {
    selected = ({})
    adding = true
  }

  function closeEditor() {
    selected = null
    adding = false
  }

  RowLayout {
    anchors.fill: parent
    anchors.topMargin: Style.space(18)
    spacing: Style.space(24)

    // ----------------------------------------------------------------- list
    ColumnLayout {
      Layout.fillWidth: true
      Layout.fillHeight: true
      spacing: Style.space(12)

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(8)

        Flow {
          Layout.fillWidth: true
          Layout.preferredWidth: Style.space(40)
          spacing: Style.space(6)
          Repeater {
            model: ["active", "trial", "paused", "cancelled", "all"]
            delegate: Button {
              required property string modelData
              readonly property int count: page.model && page.model.counts ? (page.model.counts[modelData] || 0) : 0
              text: page.tr("filter_" + modelData) + (count ? "  " + count : "")
              selected: page.filter === modelData
              bordered: true
              fontSize: Style.font.bodySmall
              onClicked: page.filter = modelData
            }
          }
        }
        TextField {
          Layout.preferredWidth: Style.space(170)
          Layout.minimumWidth: Style.space(110)
          Layout.alignment: Qt.AlignTop
          placeholderText: page.tr("filter_search")
          onTextChanged: page.query = text
        }
        PrimaryButton {
          Layout.alignment: Qt.AlignTop
          text: page.tr("add")
          iconText: "\u{F0415}"
          onClicked: page.startAdding()
        }
      }

      Label {
        visible: page.shown.length === 0 && !!page.model
        Layout.topMargin: Style.space(20)
        text: page.tr("list_empty")
        tone: 0.45
        font.italic: true
      }

      ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: Style.space(2)
        model: page.shown
        boundsBehavior: Flickable.StopAtBounds

        delegate: Rectangle {
          id: row
          required property var modelData
          required property int index
          readonly property bool current: page.selected && page.selected.id === modelData.id
          width: list.width
          implicitHeight: rowLayout.implicitHeight + Style.space(16)
          radius: Style.cornerRadius
          color: current ? Util.alpha(page.fg, 0.09) : (rowMouse.containsMouse ? Util.alpha(page.fg, 0.045) : "transparent")
          opacity: modelData.status === "cancelled" ? 0.55 : 1
          Behavior on color { ColorAnimation { duration: 100 } }

          RowLayout {
            id: rowLayout
            anchors.fill: parent
            anchors.leftMargin: Style.space(12)
            anchors.rightMargin: Style.space(14)
            spacing: Style.space(14)

            Rectangle {
              implicitWidth: Style.space(34)
              implicitHeight: Style.space(34)
              radius: width / 2
              color: Util.alpha(page.fg, 0.06)
              border.width: 1
              border.color: Util.alpha(page.fg, 0.1)
              Text {
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: row.modelData.category.icon || row.modelData.service.charAt(0)
                color: Util.alpha(page.fg, 0.8)
                font.family: Style.font.family
                font.pixelSize: Style.font.icon
              }
            }

            ColumnLayout {
              Layout.fillWidth: true
              spacing: Style.space(2)
              RowLayout {
                spacing: Style.space(6)
                Label { text: row.modelData.service; font.weight: Font.DemiBold }
                Pill { visible: row.modelData.trial; text: page.tr("trial") }
                Pill { visible: row.modelData.status === "paused" || row.modelData.status === "cancelled"; text: row.modelData.status_text }
              }
              Label {
                Layout.fillWidth: true
                text: [row.modelData.period, row.modelData.category.name].concat(row.modelData.tags).join("  ·  ")
                tone: 0.45
                font.pixelSize: Style.font.caption
              }
            }

            ColumnLayout {
              Layout.preferredWidth: Style.space(150)
              spacing: Style.space(2)
              Label {
                Layout.alignment: Qt.AlignRight
                text: row.modelData.next_date || "—"
                tone: 0.8
                font.pixelSize: Style.font.bodySmall
              }
              Label {
                Layout.alignment: Qt.AlignRight
                text: row.modelData.relative
                tone: row.modelData.days >= 0 && row.modelData.days <= 1 ? 0.9 : 0.42
                font.pixelSize: Style.font.caption
              }
            }

            ColumnLayout {
              Layout.preferredWidth: Style.space(120)
              spacing: Style.space(2)
              Label { Layout.alignment: Qt.AlignRight; text: row.modelData.amount; numeric: true; font.weight: Font.Medium }
              Label {
                Layout.alignment: Qt.AlignRight
                visible: row.modelData.converted
                text: "≈ " + row.modelData.monthly + " " + page.tr("per_month")
                numeric: true
                tone: 0.4
                font.pixelSize: Style.font.caption
              }
            }
          }

          MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: { page.adding = false; page.selected = row.modelData }
          }
        }
      }
    }

    // --------------------------------------------------------------- editor
    Rectangle {
      visible: page.selected !== null
      Layout.preferredWidth: Style.space(400)
      Layout.fillHeight: true
      Layout.bottomMargin: Style.space(20)
      radius: Style.cornerRadius
      color: Util.alpha(page.fg, 0.025)
      border.width: 1
      border.color: Util.alpha(page.fg, 0.1)

      SubscriptionEditor {
        anchors.fill: parent
        anchors.margins: Style.space(18)
        app: page.app
        item: page.selected
        adding: page.adding
        form: page.model ? page.model.form : null
        onClosed: page.closeEditor()
        onSaved: function(id) { page.pendingId = id; page.adding = false; page.reload() }
        onRemoved: { page.closeEditor(); page.reload() }
      }
    }
  }
}
