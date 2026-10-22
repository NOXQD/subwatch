import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../components"
import "../Palette.js" as Palette

// Categories with their monthly limits, plus the overall budget.
PageScroll {
  id: page

  property var app: null
  property string pageId: ""
  property var cats: null
  property var budgetPage: null
  property string newName: ""
  property string newIcon: ""
  property string newBudget: ""

  readonly property color fg: Commons.Color.foreground
  readonly property var items: cats ? cats.items : []
  readonly property var colors: Palette.series(app ? app.palette : ({}), Math.max(1, items.length), fg)

  function tr(key) { return app ? app.tr(key) : "" }

  function reload() {
    if (!app) return
    app.request("categories", {}, function(ok, data) { if (ok) page.cats = data })
    app.request("page", { page: "budget" }, function(ok, data) { if (ok) page.budgetPage = data })
  }

  function saveCategory(key, name, icon, budget) {
    app.request("category_save", { key: key, name: name, icon: icon, budget: budget }, function(ok, data) {
      if (ok) { app.toast(data.message, false); page.reload() }
      else app.toast(data, true)
    })
  }

  function removeCategory(key) {
    app.request("category_remove", { key: key }, function(ok, data) {
      if (ok) { app.toast(data.message, false); page.reload() }
      else app.toast(data, true)
    })
  }

  ColumnLayout {
    width: parent.width
    spacing: Style.space(28)

    Repeater {
      model: page.budgetPage ? page.budgetPage.groups : []
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

    Card {
      Layout.fillWidth: true
      title: page.tr("categories")
      help: page.tr("categories_help")

      Repeater {
        model: page.items
        delegate: Item {
          id: catRow
          required property var modelData
          required property int index
          property bool confirm: false
          Layout.fillWidth: true
          implicitHeight: catLayout.implicitHeight + Style.space(22)

          Hairline { visible: catRow.index > 0; width: parent.width; strength: 0.07 }

          RowLayout {
            id: catLayout
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(16)
            anchors.rightMargin: Style.space(12)
            spacing: Style.space(10)

            Rectangle {
              implicitWidth: Style.space(10); implicitHeight: Style.space(10); radius: width / 2
              color: page.colors[catRow.index] || page.fg
            }
            TextField {
              id: iconField
              Layout.preferredWidth: Style.space(52)
              horizontalAlignment: TextInput.AlignHCenter
              text: catRow.modelData.icon
              font.pixelSize: Style.font.icon
              onEditingFinished: if (text !== catRow.modelData.icon)
                page.saveCategory(catRow.modelData.key, nameField.text, text, budgetField.text)
            }
            TextField {
              id: nameField
              Layout.preferredWidth: Style.space(180)
              text: catRow.modelData.name
              onEditingFinished: if (text !== catRow.modelData.name && text.trim() !== "")
                page.saveCategory(catRow.modelData.key, text, iconField.text, budgetField.text)
            }
            ColumnLayout {
              Layout.fillWidth: true
              spacing: Style.space(4)
              RowLayout {
                Layout.fillWidth: true
                Label { text: catRow.modelData.spent; numeric: true; font.pixelSize: Style.font.bodySmall }
                Label { text: "·  " + catRow.modelData.count_text; tone: 0.45; font.pixelSize: Style.font.caption }
                Item { Layout.fillWidth: true }
              }
              Item {
                Layout.fillWidth: true
                implicitHeight: Style.space(4)
                visible: catRow.modelData.budget !== ""
                Rectangle { anchors.fill: parent; radius: height / 2; color: Util.alpha(page.fg, 0.1) }
                Rectangle {
                  height: parent.height
                  width: parent.width * catRow.modelData.fraction
                  radius: height / 2
                  color: catRow.modelData.over ? Commons.Color.urgent : (page.colors[catRow.index] || page.fg)
                }
              }
            }
            Label { text: page.tr("limit"); tone: 0.45; font.pixelSize: Style.font.caption }
            TextField {
              id: budgetField
              Layout.preferredWidth: Style.space(110)
              horizontalAlignment: TextInput.AlignRight
              placeholderText: "—"
              text: catRow.modelData.budget
              font.features: ({ "tnum": 1 })
              onEditingFinished: if (text !== catRow.modelData.budget)
                page.saveCategory(catRow.modelData.key, nameField.text, iconField.text, text)
            }
            Item {
              visible: !catRow.modelData.removable
              implicitWidth: Style.space(30)
            }
            Button {
              visible: catRow.modelData.removable
              iconText: "\u{F0A7A}"
              selected: catRow.confirm
              text: catRow.confirm ? page.tr("delete_confirm") : ""
              tooltipText: page.tr("delete")
              onClicked: {
                if (catRow.confirm) page.removeCategory(catRow.modelData.key)
                else { catRow.confirm = true; confirmReset.restart() }
              }
              Timer { id: confirmReset; interval: 4000; onTriggered: catRow.confirm = false }
            }
          }
        }
      }

      // new category
      Item {
        Layout.fillWidth: true
        implicitHeight: addLayout.implicitHeight + Style.space(22)
        Hairline { width: parent.width; strength: 0.07 }
        RowLayout {
          id: addLayout
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(16)
          anchors.rightMargin: Style.space(12)
          spacing: Style.space(10)
          Item { implicitWidth: Style.space(10) }
          TextField {
            id: addIcon
            Layout.preferredWidth: Style.space(52)
            horizontalAlignment: TextInput.AlignHCenter
            placeholderText: "\u{F0285}"
            font.pixelSize: Style.font.icon
          }
          TextField {
            id: addName
            Layout.preferredWidth: Style.space(180)
            placeholderText: page.tr("new_category")
            onAccepted: addButton.clicked()
          }
          Item { Layout.fillWidth: true }
          Label { text: page.tr("limit"); tone: 0.45; font.pixelSize: Style.font.caption }
          TextField {
            id: addBudget
            Layout.preferredWidth: Style.space(110)
            horizontalAlignment: TextInput.AlignRight
            placeholderText: "—"
          }
          Button {
            id: addButton
            iconText: "\u{F0415}"
            text: page.tr("add")
            bordered: true
            onClicked: {
              if (addName.text.trim() === "") return
              page.saveCategory("", addName.text, addIcon.text, addBudget.text)
              addName.text = ""; addIcon.text = ""; addBudget.text = ""
            }
          }
        }
      }
    }
  }
}
