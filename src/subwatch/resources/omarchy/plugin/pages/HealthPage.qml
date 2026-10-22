import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"

// `subwatch doctor`, in the window.
PageScroll {
  id: page

  property var app: null
  property string pageId: ""
  property var health: null
  property bool fixing: false

  readonly property color fg: Commons.Color.foreground
  readonly property bool canFix: {
    if (!health) return false
    for (var g = 0; g < health.groups.length; g++)
      for (var i = 0; i < health.groups[g].items.length; i++) {
        var it = health.groups[g].items[i]
        if (it.fixable && (it.status === "warn" || it.status === "fail")) return true
      }
    return false
  }

  function tr(key) { return app ? app.tr(key) : "" }

  function reload() {
    if (!app) return
    app.request("health", {}, function(ok, data) { if (ok) page.health = data })
  }

  ColumnLayout {
    width: parent.width
    spacing: Style.space(24)

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(14)
      Ring {
        size: Style.space(36)
        value: page.health ? (page.health.worst === "ok" ? 1 : page.health.worst === "warn" ? 0.66 : 0.33) : 0
        dot: !!page.health && page.health.worst !== "ok"
        color: page.health && page.health.worst === "fail" ? Commons.Color.urgent : page.fg
      }
      Label {
        Layout.fillWidth: true
        text: !page.health ? "" : page.health.worst === "ok" ? page.tr("health_ok")
          : page.health.worst === "warn" ? page.tr("health_warn") : page.tr("health_fail")
        font.pixelSize: Style.font.title
      }
      Button {
        visible: page.canFix
        text: page.tr("fix")
        iconText: "\u{F05B7}"
        bordered: true
        onClicked: {
          page.fixing = true
          page.app.request("health_fix", {}, function(ok, data) {
            page.fixing = false
            if (ok) { page.app.toast(data.message, false); page.health = data.health }
          })
        }
      }
      Button {
        text: page.tr("logs")
        iconText: "\u{F0219}"
        bordered: true
        onClicked: page.app.request("open", { target: "logs" })
      }
      Button {
        text: page.tr("recheck")
        iconText: "\u{F0450}"
        bordered: true
        onClicked: page.reload()
      }
    }

    Repeater {
      model: page.health ? page.health.groups : []
      delegate: Card {
        required property var modelData
        Layout.fillWidth: true
        title: modelData.title
        Repeater {
          model: modelData.items
          delegate: Item {
            required property var modelData
            required property int index
            Layout.fillWidth: true
            implicitHeight: checkRow.implicitHeight + Style.space(18)
            Hairline { visible: index > 0; width: parent.width; strength: 0.07 }
            RowLayout {
              id: checkRow
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: Style.space(16)
              anchors.rightMargin: Style.space(16)
              spacing: Style.space(12)
              Text {
                Layout.alignment: Qt.AlignTop
                textFormat: Text.PlainText
                text: modelData.status === "ok" ? "✓" : modelData.status === "warn" ? "!" : modelData.status === "fail" ? "✗" : "·"
                color: modelData.status === "fail" ? Commons.Color.urgent : Util.alpha(page.fg, modelData.status === "ok" ? 0.55 : 1)
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                font.weight: Font.Bold
                Layout.preferredWidth: Style.space(14)
              }
              ColumnLayout {
                Layout.fillWidth: true
                spacing: Style.space(2)
                Label {
                  Layout.fillWidth: true
                  text: modelData.text
                  tone: modelData.status === "ok" ? 0.75 : 1
                  wrapMode: Text.WordWrap
                  elide: Text.ElideNone
                }
                Label {
                  visible: modelData.hint !== ""
                  Layout.fillWidth: true
                  text: modelData.hint
                  tone: 0.5
                  font.pixelSize: Style.font.bodySmall
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
}
