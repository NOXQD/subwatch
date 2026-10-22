import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"

// Findings Subwatch was not sure about. Each answer becomes a rule, so the
// same sender does not have to be judged twice.
PageScroll {
  id: page

  property var app: null
  property string pageId: ""
  property var items: []
  property bool loaded: false

  readonly property color fg: Commons.Color.foreground

  function tr(key) { return app ? app.tr(key) : "" }

  function reload() {
    if (!app) return
    app.request("review", {}, function(ok, data) { if (ok) { page.items = data.items; page.loaded = true } })
  }

  function decide(item, accept) {
    app.request("review_decide", { sub_id: item.id, accept: accept }, function(ok, data) {
      if (ok) { app.toast(data.message, false); page.reload(); app.refreshShell() }
      else app.toast(data, true)
    })
  }

  ColumnLayout {
    width: parent.width
    spacing: Style.space(12)

    ColumnLayout {
      visible: page.loaded && page.items.length === 0
      Layout.topMargin: Style.space(30)
      Layout.alignment: Qt.AlignHCenter
      spacing: Style.space(10)
      Ring { Layout.alignment: Qt.AlignHCenter; size: Style.space(46); value: 1; color: page.fg }
      Label {
        Layout.alignment: Qt.AlignHCenter
        text: page.tr("review_empty")
        font.pixelSize: Style.font.title
      }
      Label {
        Layout.alignment: Qt.AlignHCenter
        text: page.tr("review_empty_hint")
        tone: 0.45
      }
    }

    Repeater {
      model: page.items
      delegate: Rectangle {
        id: card
        required property var modelData
        Layout.fillWidth: true
        implicitHeight: cardCol.implicitHeight + Style.space(32)
        radius: Style.cornerRadius
        color: Util.alpha(page.fg, 0.03)
        border.width: 1
        border.color: Util.alpha(page.fg, 0.11)

        RowLayout {
          id: cardCol
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.margins: Style.space(18)
          spacing: Style.space(20)

          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.space(4)
            RowLayout {
              spacing: Style.space(10)
              Label { text: card.modelData.service; font.pixelSize: Style.font.title; font.weight: Font.Bold }
              Label { text: card.modelData.amount; numeric: true; tone: 0.85 }
              Label { text: card.modelData.period; tone: 0.5; font.pixelSize: Style.font.bodySmall }
            }
            Label {
              Layout.fillWidth: true
              text: [card.modelData.review_reason, card.modelData.source, card.modelData.sender]
                .filter(function(x) { return x }).join("  ·  ")
              tone: 0.5
              font.pixelSize: Style.font.bodySmall
            }
            RowLayout {
              spacing: Style.space(8)
              Layout.topMargin: Style.space(4)
              Item {
                implicitWidth: Style.space(120)
                implicitHeight: Style.space(4)
                Rectangle { anchors.fill: parent; radius: height / 2; color: Util.alpha(page.fg, 0.1) }
                Rectangle {
                  height: parent.height
                  width: parent.width * card.modelData.confidence / 100
                  radius: height / 2
                  color: page.fg
                }
              }
              Label {
                text: page.tr("confidence") + " " + card.modelData.confidence + " %"
                tone: 0.45
                font.pixelSize: Style.font.caption
              }
              Label {
                visible: card.modelData.next_date !== ""
                text: "·  " + page.tr("next_charge") + " " + card.modelData.next_date
                tone: 0.45
                font.pixelSize: Style.font.caption
              }
            }
          }

          PrimaryButton {
            text: page.tr("is_subscription")
            iconText: "\u{F012C}"
            onClicked: page.decide(card.modelData, true)
          }
          Button {
            text: page.tr("not_subscription")
            iconText: "\u{F0156}"
            bordered: true
            onClicked: page.decide(card.modelData, false)
          }
        }
      }
    }
  }
}
