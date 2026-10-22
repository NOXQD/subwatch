import QtQuick
import QtQuick.Layouts
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "components"
import "Palette.js" as Palette

// Contents of the Subwatch window: navigation on the left, the page on the
// right, notices at the bottom. Pages live in pages/ and talk to the backend
// through `app.request`.
Item {
  id: app

  signal closeRequested()

  property var strings: ({})
  property var overview: null
  property var palette: ({})
  property string page: "overview"
  property var pageExtra: null
  property bool ready: false
  property bool scanning: false
  property string version: ""
  property string configPath: ""

  readonly property color fg: Commons.Color.foreground
  readonly property int reviewCount: overview && overview.review ? overview.review.count : 0

  readonly property var navGroups: [
    { title: "nav_main", items: [
      { id: "overview", icon: "\u{F0570}" },
      { id: "subscriptions", icon: "\u{F0279}" },
      { id: "review", icon: "\u{F0E1E}" },
      { id: "categories", icon: "\u{F0285}" }
    ] },
    { title: "nav_settings", items: [
      { id: "reminders", icon: "\u{F009A}" },
      { id: "notifications", icon: "\u{F0A08}" },
      { id: "sources", icon: "\u{F01EE}" },
      { id: "currency", icon: "\u{F01C1}" },
      { id: "detection", icon: "\u{F0349}" },
      { id: "appearance", icon: "\u{F03D8}" },
      { id: "keys", icon: "\u{F030C}" },
      { id: "ai", icon: "\u{F0674}" },
      { id: "privacy", icon: "\u{F0341}" },
      { id: "hooks", icon: "\u{F06D3}" }
    ] },
    { title: "nav_system", items: [
      { id: "health", icon: "\u{F04D5}" }
    ] }
  ]

  function tr(key) { return strings[key] !== undefined ? strings[key] : "" }
  function pageTitle(id) { return tr("page_" + id) }

  function request(cmd, args, callback) {
    return backend.request(cmd, args || {}, function(ok, data, hint) {
      if (!ok && data && !callback) app.toast(data + (hint ? "\n" + hint : ""), true)
      if (callback) callback(ok, data, hint)
    })
  }

  function toast(text, isError) {
    if (!text) return
    notice.show(String(text), !!isError)
  }

  function navigate(payload) {
    var target = payload && payload.page ? String(payload.page) : (page || "overview")
    if (target === "budget") target = "categories"
    pageExtra = payload || null
    if (target === page && pageLoader.item && pageLoader.item.applyExtra) pageLoader.item.applyExtra(pageExtra)
    page = target
  }

  function refreshShell() {
    request("overview", {}, function(ok, data) { if (ok) app.overview = data })
  }

  function scan() {
    request("scan", {}, function(ok, data) {
      if (ok) { app.scanning = true; app.toast(data.message, false) }
      else app.toast(data, true)
    })
  }

  function openConfig() { request("open", { target: "config" }) }

  Backend {
    id: backend
    onEvent: function(message) {
      if (message.event === "ready") {
        app.version = message.version || ""
      } else if (message.event === "changed") {
        app.refreshShell()
        if (pageLoader.item && pageLoader.item.reload) pageLoader.item.reload()
      } else if (message.event === "scan") {
        app.scanning = message.state === "running"
        if (message.state === "done") app.toast(message.text, message.error)
      }
    }
  }

  Component.onCompleted: {
    request("hello", {}, function(ok, data) {
      if (!ok) return
      app.strings = data.strings
      app.version = data.version
      app.configPath = data.config_path
      app.ready = true
    })
    refreshShell()
  }

  FileView {
    path: Commons.Color.currentThemePath + "/colors.toml"
    watchChanges: true
    printErrors: false
    onLoaded: app.palette = Palette.parse(text())
    onFileChanged: reload()
  }

  // Ctrl+F jumps to the settings search, Ctrl+W/Escape close the window.
  Shortcut { sequences: ["Ctrl+F"]; onActivated: search.forceActiveFocus() }
  Shortcut { sequences: ["Ctrl+W", "Ctrl+Q"]; onActivated: app.closeRequested() }
  Shortcut { sequences: ["Ctrl+R"]; onActivated: app.scan() }
  Shortcut { sequences: ["Ctrl+N"]; onActivated: app.navigate({ page: "subscriptions", action: "add" }) }

  RowLayout {
    anchors.fill: parent
    spacing: 0

    // ------------------------------------------------------------ sidebar
    Rectangle {
      Layout.fillHeight: true
      Layout.preferredWidth: Style.space(232)
      color: Util.alpha(app.fg, 0.025)

      Rectangle {
        anchors.right: parent.right
        width: 1
        height: parent.height
        color: Util.alpha(app.fg, 0.08)
      }

      ColumnLayout {
        anchors.fill: parent
        anchors.margins: Style.space(18)
        anchors.rightMargin: Style.space(14)
        spacing: 0

        // brand
        RowLayout {
          spacing: Style.space(12)
          Ring {
            size: Style.space(30)
            value: app.overview && app.overview.widget ? app.overview.widget.ring : 0.7
            dot: app.overview && app.overview.widget ? app.overview.widget.alert : false
            color: app.fg
          }
          ColumnLayout {
            spacing: 0
            Label {
              text: "Subwatch"
              font.pixelSize: Style.font.heading
              font.weight: Font.Bold
              font.letterSpacing: 0.4
            }
            Label {
              text: app.overview && app.overview.totals
                ? app.overview.totals.monthly + " " + app.tr("per_month") : ""
              tone: 0.5
              numeric: true
              font.pixelSize: Style.font.caption
            }
          }
        }

        Item { Layout.preferredHeight: Style.space(22) }

        Flickable {
          Layout.fillWidth: true
          Layout.fillHeight: true
          contentHeight: navColumn.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          ColumnLayout {
            id: navColumn
            width: parent.width
            spacing: 0

            Repeater {
              model: app.navGroups
              delegate: ColumnLayout {
                required property var modelData
                required property int index
                Layout.fillWidth: true
                spacing: Style.space(2)

                Caps {
                  Layout.topMargin: index === 0 ? 0 : Style.space(16)
                  Layout.bottomMargin: Style.space(4)
                  Layout.leftMargin: Style.space(10)
                  text: app.tr(modelData.title)
                  font.pixelSize: Style.font.caption - 1
                }

                Repeater {
                  model: modelData.items
                  delegate: NavItem {
                    required property var modelData
                    Layout.fillWidth: true
                    icon: modelData.icon
                    text: app.pageTitle(modelData.id)
                    selected: app.page === modelData.id
                    badge: modelData.id === "review" && app.reviewCount > 0 ? String(app.reviewCount)
                      : (modelData.id === "subscriptions" && app.overview && app.overview.totals
                         ? String(app.overview.totals.count) : "")
                    badgeStrong: modelData.id === "review"
                    onClicked: app.navigate({ page: modelData.id })
                  }
                }
              }
            }
          }
        }

        Hairline { Layout.fillWidth: true; Layout.topMargin: Style.space(10) }

        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: Style.space(10)
          spacing: Style.space(6)
          Button {
            Layout.fillWidth: true
            leftAlign: true
            iconText: app.scanning ? "\u{F0450}" : "\u{F01EE}"
            iconSpinning: app.scanning
            text: app.scanning ? app.tr("scanning") : app.tr("scan_now")
            fontSize: Style.font.bodySmall
            onClicked: app.scan()
          }
        }
        Button {
          Layout.fillWidth: true
          leftAlign: true
          iconText: "\u{F0219}"
          text: app.tr("open_config")
          tooltipText: app.configPath
          fontSize: Style.font.bodySmall
          onClicked: app.openConfig()
        }
        Label {
          Layout.topMargin: Style.space(8)
          Layout.leftMargin: Style.space(10)
          text: app.version ? "v" + app.version : ""
          tone: 0.3
          font.pixelSize: Style.font.caption
        }
      }
    }

    // --------------------------------------------------------------- page
    Item {
      Layout.fillWidth: true
      Layout.fillHeight: true

      ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(34)
        anchors.rightMargin: Style.space(34)
        anchors.topMargin: Style.space(26)
        spacing: 0

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(16)
          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.space(4)
            Label {
              text: app.pageTitle(app.page)
              font.pixelSize: Style.font.display
              font.weight: Font.Bold
              font.letterSpacing: -0.3
            }
            Label {
              Layout.fillWidth: true
              text: app.tr("sub_" + app.page)
              tone: 0.5
              wrapMode: Text.WordWrap
              elide: Text.ElideNone
            }
          }
          TextField {
            id: search
            Layout.preferredWidth: Style.space(260)
            Layout.alignment: Qt.AlignTop
            placeholderText: app.tr("search_settings")
            onTextChanged: searchDebounce.restart()
            Keys.onEscapePressed: { text = ""; focus = false }
          }
        }

        Hairline { Layout.fillWidth: true; Layout.topMargin: Style.space(18) }

        Loader {
          id: pageLoader
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: search.text.trim() === ""
          // The page id in the query makes generic pages load afresh.
          source: app.ready ? Qt.resolvedUrl("pages/" + app.pageFile(app.page)) + "?" + app.page : ""
          onLoaded: {
            item.app = app
            item.pageId = app.page
            if (item.applyExtra) item.applyExtra(app.pageExtra)
            if (item.reload) item.reload()
          }
        }

        SearchResults {
          id: results
          Layout.fillWidth: true
          Layout.fillHeight: true
          visible: search.text.trim() !== ""
          app: app
          query: ""
        }
      }

      Timer {
        id: searchDebounce
        interval: 180
        onTriggered: results.query = search.text
      }
    }
  }

  function pageFile(id) {
    var special = { overview: "OverviewPage.qml", subscriptions: "SubscriptionsPage.qml",
                    review: "ReviewPage.qml", categories: "CategoriesPage.qml",
                    sources: "SourcesPage.qml", health: "HealthPage.qml" }
    return special[id] || "SettingsPage.qml"
  }

  Notice {
    id: notice
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Style.space(24)
  }
}
