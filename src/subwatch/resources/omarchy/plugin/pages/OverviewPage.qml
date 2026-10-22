import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"
import "../Palette.js" as Palette

// The big picture: totals, the budget, a year of spending, categories and
// what is about to be charged.
PageScroll {
  id: page

  property var app: null
  property string pageId: ""
  property var d: null

  readonly property color fg: Commons.Color.foreground
  readonly property var cats: d && d.categories ? d.categories : []
  readonly property var catColors: Palette.series(app ? app.palette : ({}), Math.max(1, cats.length), fg)

  function reload() {
    if (!app) return
    app.request("overview", {}, function(ok, data) { if (ok) page.d = data })
  }

  ColumnLayout {
    width: parent.width
    spacing: Style.space(26)

    // ---- empty -----------------------------------------------------------
    ColumnLayout {
      visible: !!page.d && page.d.totals.count === 0
      Layout.fillWidth: true
      spacing: Style.space(10)
      Label { text: page.app ? page.app.tr("empty_title") : ""; font.pixelSize: Style.font.heading; font.weight: Font.DemiBold }
      Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Style.space(560)
        text: page.app ? page.app.tr("empty_text") : ""
        tone: 0.6
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
      }
      RowLayout {
        spacing: Style.space(8)
        PrimaryButton {
          text: page.app ? page.app.tr("connect_mail") : ""
          iconText: "\u{F01EE}"
          onClicked: page.app.navigate({ page: "sources" })
        }
        Button {
          text: page.app ? page.app.tr("add") : ""
          iconText: "\u{F0415}"
          bordered: true
          onClicked: page.app.navigate({ page: "subscriptions", action: "add" })
        }
      }
    }

    // ---- tiles -----------------------------------------------------------
    GridLayout {
      visible: !!page.d && page.d.totals.count > 0
      Layout.fillWidth: true
      columns: page.width > Style.space(760) ? 4 : 2
      columnSpacing: Style.space(12)
      rowSpacing: Style.space(12)

      StatTile {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.fillHeight: true
        title: page.app ? page.app.tr("per_month") : ""
        value: page.d ? page.d.totals.monthly : ""
        note: page.d ? "≈ " + page.d.totals.daily + " " + page.app.tr("per_day") : ""
      }
      StatTile {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.fillHeight: true
        title: page.app ? page.app.tr("per_year") : ""
        value: page.d ? page.d.totals.yearly : ""
        note: page.d ? page.d.year_note : ""
      }
      StatTile {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.fillHeight: true
        title: page.app ? page.app.tr("subscriptions_count") : ""
        value: page.d ? String(page.d.totals.count) : ""
        note: page.d && page.d.review.count > 0 ? page.d.review.text : (page.d ? page.d.totals.count_text : "")
      }
      StatTile {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.fillHeight: true
        title: page.app ? page.app.tr("budget") : ""
        value: page.d && page.d.budget ? page.d.budget.pct : "—"
        note: page.d && page.d.budget ? page.d.budget.note : (page.app ? page.app.tr("budget_not_set") : "")
        fraction: page.d && page.d.budget ? page.d.budget.fraction : -1
        alert: !!(page.d && page.d.budget && page.d.budget.level === "over")
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: page.app.navigate({ page: "categories" })
        }
      }
    }

    // ---- two columns -----------------------------------------------------
    GridLayout {
      visible: !!page.d && page.d.totals.count > 0
      Layout.fillWidth: true
      columns: page.width > Style.space(820) ? 2 : 1
      columnSpacing: Style.space(30)
      rowSpacing: Style.space(26)

      ColumnLayout {
        Layout.fillWidth: true
        Layout.preferredWidth: 3
        Layout.alignment: Qt.AlignTop
        spacing: Style.space(26)

        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(12)
          Caps { text: page.app ? page.app.tr("by_month") : "" }
          Columns {
            Layout.fillWidth: true
            items: page.d && page.d.history_long ? page.d.history_long : []
            chartHeight: Style.space(150)
            showValues: true
          }
        }

        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(12)
          Caps { text: page.app ? page.app.tr("categories") : "" }
          StackBar {
            id: stack
            Layout.fillWidth: true
            items: page.cats
            colors: page.catColors
            thickness: Style.space(10)
          }
          Repeater {
            model: page.cats
            delegate: RowLayout {
              required property var modelData
              required property int index
              Layout.fillWidth: true
              spacing: Style.space(12)
              Rectangle {
                implicitWidth: Style.space(10); implicitHeight: Style.space(10); radius: width / 2
                color: page.catColors[index] || page.fg
              }
              Label { text: (modelData.icon ? modelData.icon + "  " : "") + modelData.name; Layout.preferredWidth: Style.space(170) }
              Item {
                Layout.fillWidth: true
                implicitHeight: Style.space(6)
                Rectangle { anchors.fill: parent; radius: height / 2; color: Util.alpha(page.fg, 0.07) }
                Rectangle {
                  height: parent.height
                  width: parent.width * modelData.share
                  radius: height / 2
                  color: page.catColors[index] || page.fg
                  Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                  visible: !!modelData.budget
                  x: modelData.budget ? Math.min(parent.width - 2, parent.width * modelData.share / Math.max(0.0001, modelData.budget.fraction)) : 0
                  y: -Style.space(3)
                  width: 2
                  height: parent.height + Style.space(6)
                  color: modelData.budget && modelData.budget.level === "over" ? Commons.Color.urgent : page.fg
                }
              }
              Label { text: modelData.amount; numeric: true; Layout.preferredWidth: Style.space(96); horizontalAlignment: Text.AlignRight }
              Label { text: modelData.pct; numeric: true; tone: 0.45; Layout.preferredWidth: Style.space(44); horizontalAlignment: Text.AlignRight }
              HoverHandler { onHoveredChanged: stack.highlighted = hovered ? index : -1 }
            }
          }
        }
      }

      ColumnLayout {
        Layout.fillWidth: true
        Layout.preferredWidth: 2
        Layout.alignment: Qt.AlignTop
        spacing: Style.space(10)

        RowLayout {
          Layout.fillWidth: true
          Caps { text: page.app ? page.app.tr("soon") : "" }
          Item { Layout.fillWidth: true }
          Label {
            text: page.d && page.d.upcoming.length ? page.d.upcoming_title + "  ·  " + page.d.upcoming_sum : ""
            tone: 0.42
            numeric: true
            font.pixelSize: Style.font.caption
          }
        }
        Label {
          visible: !!page.d && page.d.upcoming.length === 0
          text: page.app ? page.app.tr("nothing_soon") : ""
          tone: 0.45
          font.italic: true
        }
        Repeater {
          model: page.d ? page.d.upcoming : []
          delegate: UpcomingRow {
            required property var modelData
            Layout.fillWidth: true
            item: modelData
            trialText: page.app ? page.app.tr("trial") : ""
            onClicked: page.app.navigate({ page: "subscriptions", sub_id: modelData.id })
          }
        }

        ColumnLayout {
          visible: !!page.d && page.d.insights.length > 0
          Layout.fillWidth: true
          Layout.topMargin: Style.space(16)
          spacing: Style.space(8)
          Caps { text: page.app ? page.app.tr("insights") : "" }
          Repeater {
            model: page.d ? page.d.insights : []
            delegate: RowLayout {
              required property var modelData
              Layout.fillWidth: true
              spacing: Style.space(10)
              Label {
                Layout.alignment: Qt.AlignTop
                text: modelData.kind === "price" ? "\u{F0535}" : modelData.kind === "duplicate" ? "\u{F0191}"
                  : modelData.kind === "zombie" ? "\u{F04B2}" : "\u{F051F}"
                tone: 0.7
                font.pixelSize: Style.font.icon
              }
              Label {
                Layout.fillWidth: true
                text: modelData.text
                tone: 0.8
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
              }
            }
          }
        }
      }
    }
  }
}
