import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons

// Settings that match the search box, from every page at once.
PageScroll {
  id: results

  property var app: null
  property string query: ""
  property var items: []

  onQueryChanged: {
    if (!app || query.trim() === "") { items = []; return }
    app.request("search", { query: query }, function(ok, data) { if (ok) results.items = data })
  }

  ColumnLayout {
    width: parent.width
    spacing: Style.space(12)

    Label {
      visible: results.items.length === 0 && results.query.trim() !== ""
      text: results.app ? results.app.tr("search_nothing") : ""
      tone: 0.45
      font.italic: true
    }

    Card {
      Layout.fillWidth: true
      visible: results.items.length > 0
      Repeater {
        model: results.items
        delegate: ColumnLayout {
          required property var modelData
          required property int index
          Layout.fillWidth: true
          spacing: 0
          Caps {
            Layout.topMargin: Style.space(12)
            Layout.leftMargin: Style.space(16)
            text: modelData.page_title + "  ›  " + modelData.path
            font.letterSpacing: 0.6
            font.capitalization: Font.MixedCase
          }
          FieldRow {
            Layout.fillWidth: true
            app: results.app
            field: modelData
            first: true
          }
        }
      }
    }
  }
}
