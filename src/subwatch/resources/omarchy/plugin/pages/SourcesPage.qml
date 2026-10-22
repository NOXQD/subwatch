import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"

// Where subscriptions come from: Gmail, IMAP boxes, bank statements, and
// when the mail is scanned.
PageScroll {
  id: page

  property var app: null
  property string pageId: ""
  property var src: null
  property var settingsPage: null
  property bool showImapForm: false
  property bool connecting: false
  property string imapError: ""

  readonly property color fg: Commons.Color.foreground
  readonly property var presets: [
    { value: "", label: "—" },
    { value: "imap.yandex.ru", label: "Yandex" },
    { value: "imap.mail.ru", label: "Mail.ru" },
    { value: "imap.gmail.com", label: "Gmail (IMAP)" },
    { value: "outlook.office365.com", label: "Outlook" },
    { value: "imap.fastmail.com", label: "Fastmail" },
    { value: "imap.zoho.com", label: "Zoho" }
  ]

  function tr(key) { return app ? app.tr(key) : "" }

  function reload() {
    if (!app) return
    app.request("sources", {}, function(ok, data) { if (ok) page.src = data })
    app.request("page", { page: "sources" }, function(ok, data) { if (ok) page.settingsPage = data })
  }

  function call(cmd, args) {
    app.request(cmd, args || {}, function(ok, data, hint) {
      if (ok) { if (data.message) app.toast(data.message, false); page.reload() }
      else app.toast(data + (hint ? "\n" + hint : ""), true)
    })
  }

  function connectImap() {
    imapError = ""
    connecting = true
    app.request("imap_connect", {
      name: imapName.text.trim() || (imapHost.text.split(".").slice(-2, -1)[0] || "mail"),
      host: imapHost.text.trim(), username: imapUser.text.trim(), password: imapPass.text,
      folders: imapFolders.text.trim() || "INBOX"
    }, function(ok, data, hint) {
      page.connecting = false
      if (!ok) { page.imapError = data + (hint ? "\n" + hint : ""); return }
      imapPass.text = ""
      page.showImapForm = false
      app.toast(data.message, false)
      page.reload()
    })
  }

  ColumnLayout {
    width: parent.width
    spacing: Style.space(28)

    // ---- mail -----------------------------------------------------------
    Card {
      Layout.fillWidth: true
      title: page.tr("mail")
      help: page.tr("mail_help")

      SourceRow {
        icon: "\u{F02AB}"
        title: "Gmail"
        detail: page.src && page.src.gmail.connected ? page.tr("gmail_on") : page.tr("gmail_off")
        ok: !!(page.src && page.src.gmail.connected && page.src.gmail.enabled)
        Button {
          text: page.src && page.src.gmail.connected ? page.tr("reconnect") : page.tr("connect")
          bordered: true
          onClicked: page.call("gmail_connect")
        }
        Button {
          visible: !!(page.src && page.src.gmail.connected)
          text: page.tr("disconnect")
          onClicked: page.call("gmail_disconnect")
        }
      }

      Repeater {
        model: page.src ? page.src.imap : []
        delegate: SourceRow {
          required property var modelData
          icon: "\u{F01EE}"
          title: modelData.name
          detail: modelData.username + "  ·  " + modelData.host + "  ·  " + modelData.folders
            + (modelData.connected ? "" : "  ·  " + page.tr("no_password"))
          ok: modelData.connected && modelData.enabled
          Button {
            text: page.tr("remove")
            onClicked: page.call("imap_remove", { name: modelData.name })
          }
        }
      }

      Item {
        Layout.fillWidth: true
        implicitHeight: imapBox.implicitHeight + Style.space(24)
        Hairline { width: parent.width; strength: 0.07 }

        ColumnLayout {
          id: imapBox
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(16)
          anchors.rightMargin: Style.space(16)
          spacing: Style.space(10)

          Button {
            visible: !page.showImapForm
            text: page.tr("add_imap")
            iconText: "\u{F0415}"
            bordered: true
            onClicked: page.showImapForm = true
          }

          ColumnLayout {
            visible: page.showImapForm
            Layout.fillWidth: true
            spacing: Style.space(8)
            Label {
              Layout.fillWidth: true
              text: page.tr("imap_help")
              tone: 0.5
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
              elide: Text.ElideNone
            }
            GridLayout {
              Layout.fillWidth: true
              columns: 2
              columnSpacing: Style.space(10)
              rowSpacing: Style.space(8)
              Dropdown {
                Layout.fillWidth: true
                showLabel: false
                options: page.presets
                value: ""
                onChanged: function(v) { if (v) imapHost.text = v }
              }
              TextField { id: imapHost; Layout.fillWidth: true; placeholderText: "imap.example.com" }
              TextField { id: imapUser; Layout.fillWidth: true; placeholderText: page.tr("imap_user") }
              TextField { id: imapPass; Layout.fillWidth: true; password: true; placeholderText: page.tr("imap_password") }
              TextField { id: imapName; Layout.fillWidth: true; placeholderText: page.tr("imap_name") }
              TextField { id: imapFolders; Layout.fillWidth: true; placeholderText: "INBOX" }
            }
            Label {
              visible: page.imapError !== ""
              Layout.fillWidth: true
              text: page.imapError
              color: Commons.Color.urgent
              wrapMode: Text.WordWrap
              elide: Text.ElideNone
            }
            RowLayout {
              spacing: Style.space(8)
              PrimaryButton {
                text: page.connecting ? page.tr("checking") : page.tr("connect")
                busy: page.connecting
                iconText: page.connecting ? "\u{F0450}" : ""
                enabled: imapHost.text.trim() !== "" && imapUser.text.trim() !== "" && imapPass.text !== ""
                onClicked: page.connectImap()
              }
              Button { text: page.tr("close"); onClicked: page.showImapForm = false }
            }
          }
        }
      }
    }

    // ---- scanning -------------------------------------------------------
    Card {
      Layout.fillWidth: true
      title: page.tr("scanning_title")

      SourceRow {
        icon: "\u{F0450}"
        title: page.src ? page.src.last_scan.text : ""
        detail: page.src && page.src.timer.enabled
          ? page.tr("timer_on") + (page.src.timer.next ? " " + page.src.timer.next : "")
          : page.tr("timer_off")
        ok: !!(page.src && page.src.timer.enabled && !page.src.last_scan.errors)
        PrimaryButton {
          text: page.app && page.app.scanning ? page.tr("scanning") : page.tr("scan_now")
          iconText: "\u{F0450}"
          busy: !!(page.app && page.app.scanning)
          onClicked: page.app.scan()
        }
      }

      SourceRow {
        icon: "\u{F0219}"
        title: page.tr("statement")
        detail: page.tr("statement_help")
        ok: true
        TextField {
          id: statementPath
          Layout.preferredWidth: Style.space(240)
          placeholderText: "~/Downloads/kaspi.pdf"
          onAccepted: importButton.clicked()
        }
        Button {
          id: importButton
          text: page.tr("import")
          bordered: true
          onClicked: if (statementPath.text.trim() !== "") page.call("open", { target: "import", path: statementPath.text.trim() })
        }
      }
    }

    // ---- the rest from config.toml ------------------------------------------
    Repeater {
      model: page.settingsPage ? page.settingsPage.groups : []
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

  component SourceRow: Item {
    id: srow
    property string icon: ""
    property string title: ""
    property string detail: ""
    property bool ok: false
    default property alias actions: actionsRow.data
    Layout.fillWidth: true
    implicitHeight: srowLayout.implicitHeight + Style.space(24)

    Hairline { width: parent.width; strength: 0.07; visible: srow.y > 0 }

    RowLayout {
      id: srowLayout
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(16)
      anchors.rightMargin: Style.space(16)
      spacing: Style.space(14)

      Rectangle {
        implicitWidth: Style.space(34)
        implicitHeight: Style.space(34)
        radius: width / 2
        color: srow.ok ? page.fg : Util.alpha(page.fg, 0.06)
        border.width: srow.ok ? 0 : 1
        border.color: Util.alpha(page.fg, 0.15)
        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: srow.icon
          color: srow.ok ? Commons.Color.background : Util.alpha(page.fg, 0.7)
          font.family: Style.font.family
          font.pixelSize: Style.font.icon
        }
      }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(2)
        Label { Layout.fillWidth: true; text: srow.title; font.weight: Font.DemiBold }
        Label {
          Layout.fillWidth: true
          text: srow.detail
          tone: 0.5
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          elide: Text.ElideNone
        }
      }
      RowLayout {
        id: actionsRow
        spacing: Style.space(6)
      }
    }
  }
}
