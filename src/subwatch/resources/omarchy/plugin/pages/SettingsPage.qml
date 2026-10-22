import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"

// Any settings page: groups of fields described by the backend, plus a few
// page-specific extras (exchange rates, the AI key, export).
PageScroll {
  id: page

  property var app: null
  property string pageId: ""
  property var model: null
  property var rates: null
  property bool updatingRates: false

  readonly property color fg: Commons.Color.foreground

  function tr(key) { return app ? app.tr(key) : "" }

  function reload() {
    if (!app) return
    app.request("page", { page: pageId }, function(ok, data) { if (ok) page.model = data })
    if (pageId === "currency")
      app.request("rates", {}, function(ok, data) { if (ok) page.rates = data })
  }

  ColumnLayout {
    width: parent.width
    spacing: Style.space(28)

    Loader {
      Layout.fillWidth: true
      active: page.pageId === "currency" || page.pageId === "ai" || page.pageId === "privacy"
      visible: active
      sourceComponent: page.pageId === "currency" ? ratesCard : page.pageId === "ai" ? aiCard : exportCard
    }

    Repeater {
      model: page.model ? page.model.groups : []
      delegate: Card {
        required property var modelData
        Layout.fillWidth: true
        title: modelData.title
        help: modelData.help

        Repeater {
          model: modelData.fields
          delegate: FieldRow {
            required property var modelData
            required property int index
            Layout.fillWidth: true
            app: page.app
            field: modelData
            first: index === 0
          }
        }
      }
    }
  }

  Component {
    id: ratesCard
    Card {
      title: page.tr("rates_title")
      help: page.rates && page.rates.fetched ? page.tr("rates_from") + " " + page.rates.source + ", " + page.rates.fetched : ""

      Item {
        Layout.fillWidth: true
        implicitHeight: ratesCol.implicitHeight + Style.space(24)
        ColumnLayout {
          id: ratesCol
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(16)
          anchors.rightMargin: Style.space(16)
          spacing: Style.space(12)

          Label {
            visible: !page.rates || page.rates.items.length === 0
            text: page.tr("rates_none")
            tone: 0.45
          }
          Flow {
            Layout.fillWidth: true
            spacing: Style.space(8)
            Repeater {
              model: page.rates ? page.rates.items.filter(function(r) {
                return ["USD", "EUR", "RUB", "GBP", "CNY", "TRY", "UZS", "KGS", "KZT", "AED", "JPY", "CHF"].indexOf(r.code) !== -1
              }) : []
              delegate: Rectangle {
                required property var modelData
                implicitWidth: rateRow.implicitWidth + Style.space(20)
                implicitHeight: rateRow.implicitHeight + Style.space(12)
                radius: Style.cornerRadius
                color: Util.alpha(page.fg, 0.04)
                border.width: 1
                border.color: Util.alpha(page.fg, 0.1)
                Row {
                  id: rateRow
                  anchors.centerIn: parent
                  spacing: Style.space(8)
                  Label { text: modelData.code; font.weight: Font.DemiBold }
                  Label { text: modelData.value; numeric: true; tone: 0.7 }
                }
              }
            }
          }
          Button {
            text: page.updatingRates ? page.tr("checking") : page.tr("rates_update")
            iconText: "\u{F0450}"
            iconSpinning: page.updatingRates
            bordered: true
            onClicked: {
              page.updatingRates = true
              page.app.request("rates_update", {}, function(ok, data) {
                page.updatingRates = false
                if (ok) page.rates = data
              })
            }
          }
        }
      }
    }
  }

  Component {
    id: aiCard
    Card {
      title: page.tr("ai_key_title")
      help: page.tr("ai_key_help")
      Item {
        Layout.fillWidth: true
        implicitHeight: keyRow.implicitHeight + Style.space(24)
        RowLayout {
          id: keyRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(16)
          anchors.rightMargin: Style.space(16)
          spacing: Style.space(8)
          TextField {
            id: keyField
            Layout.fillWidth: true
            password: true
            placeholderText: page.tr("ai_key_placeholder")
          }
          PrimaryButton {
            text: page.tr("save")
            enabled: keyField.text.trim() !== ""
            onClicked: page.app.request("ai_key", { key: keyField.text }, function(ok, data) {
              if (ok) { keyField.text = ""; page.app.toast(data.message, false) }
            })
          }
          Button {
            text: page.tr("remove")
            bordered: true
            onClicked: page.app.request("ai_key", { key: "" }, function(ok, data) {
              if (ok) page.app.toast(data.message, false)
            })
          }
        }
      }
    }
  }

  Component {
    id: exportCard
    Card {
      title: page.tr("export_title")
      help: page.tr("export_help")
      Item {
        Layout.fillWidth: true
        implicitHeight: exportRow.implicitHeight + Style.space(24)
        RowLayout {
          id: exportRow
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(16)
          spacing: Style.space(8)
          Repeater {
            model: [{ f: "csv", icon: "\u{F0219}" }, { f: "json", icon: "\u{F0626}" }, { f: "ics", icon: "\u{F00ED}" }]
            delegate: Button {
              required property var modelData
              text: modelData.f.toUpperCase()
              iconText: modelData.icon
              bordered: true
              onClicked: page.app.request("export", { format: modelData.f }, function(ok, data) {
                if (ok) page.app.toast(data.message, false)
              })
            }
          }
          Button {
            text: page.tr("open_config")
            iconText: "\u{F0219}"
            onClicked: page.app.openConfig()
          }
        }
      }
    }
  }
}
