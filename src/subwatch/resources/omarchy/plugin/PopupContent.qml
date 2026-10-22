import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "components"
import "Palette.js" as Palette

// What the bar popup shows: the monthly figure, the budget, the next
// charges, where the money goes and how the last half-year looked.
// Everything arrives formatted from `subwatch bar --format panel`.
ColumnLayout {
  id: root

  property var info: null
  property var palette: ({})
  property int cursor: -1
  property bool scanning: false

  signal openSettings(string page, var extra)
  signal scanRequested()
  signal tuiRequested()

  readonly property var s: info && info.strings ? info.strings : ({})
  readonly property var totals: info && info.totals ? info.totals : null
  readonly property var widget: info && info.widget ? info.widget : null
  readonly property var upcoming: info && info.upcoming ? info.upcoming : []
  readonly property var categories: info && info.categories ? info.categories : []
  readonly property var shownCategories: categories.slice(0, 5)
  readonly property var catColors: Palette.series(palette, Math.max(1, categories.length), Commons.Color.foreground)
  readonly property bool empty: !!totals && totals.count === 0
  readonly property int visibleUpcoming: Math.min(upcoming.length, info && info.upcoming_rows ? info.upcoming_rows : 5)
  readonly property color fg: Commons.Color.foreground

  function tr(key) { return s[key] !== undefined ? s[key] : "" }

  spacing: 0

  // ---- header -----------------------------------------------------------
  RowLayout {
    Layout.fillWidth: true
    spacing: Style.space(10)

    Ring {
      size: Style.space(22)
      value: root.widget ? root.widget.ring : 0
      dot: root.widget ? root.widget.alert : false
      color: root.fg
    }

    ColumnLayout {
      Layout.fillWidth: true
      spacing: 0
      Caps { text: "Subwatch"; color: root.fg; font.letterSpacing: 2.2 }
      Label {
        Layout.fillWidth: true
        text: root.info ? root.info.today : ""
        tone: 0.45
        font.pixelSize: Style.font.caption
      }
    }

    PanelActionButton {
      iconText: "\u{F0450}"
      tooltipText: root.tr("scan")
      foreground: root.fg
      fontSize: Style.font.icon
      onClicked: root.scanRequested()
      RotationAnimation on rotation {
        running: root.scanning
        loops: Animation.Infinite
        from: 0; to: 360; duration: 1100
        onRunningChanged: if (!running) parent.rotation = 0
      }
    }
    PanelActionButton {
      iconText: "\u{F0493}"
      tooltipText: root.tr("settings")
      foreground: root.fg
      fontSize: Style.font.icon
      onClicked: root.openSettings("overview", null)
    }
  }

  // ---- error / loading --------------------------------------------------
  Label {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(16)
    visible: !!(root.info && root.info.error)
    text: root.info && root.info.error ? root.info.error : ""
    wrapMode: Text.WordWrap
    color: Commons.Color.urgent
  }

  // ---- empty state ------------------------------------------------------
  ColumnLayout {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(22)
    visible: root.empty
    spacing: Style.space(8)
    Label {
      text: root.tr("empty_title")
      font.pixelSize: Style.font.heading
      font.weight: Font.DemiBold
    }
    Label {
      Layout.fillWidth: true
      text: root.tr("empty_text")
      tone: 0.6
      wrapMode: Text.WordWrap
      elide: Text.ElideNone
    }
    RowLayout {
      Layout.topMargin: Style.space(8)
      spacing: Style.space(8)
      PrimaryButton {
        text: root.tr("connect_mail")
        iconText: "\u{F01EE}"
        onClicked: root.openSettings("sources", null)
      }
      Button {
        text: root.tr("add")
        iconText: "\u{F0415}"
        bordered: true
        onClicked: root.openSettings("subscriptions", { action: "add" })
      }
    }
  }

  // ---- hero -------------------------------------------------------------
  ColumnLayout {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(18)
    visible: !!root.totals && !root.empty
    spacing: Style.space(2)

    RowLayout {
      spacing: Style.space(8)
      Label {
        text: root.totals ? root.totals.monthly : ""
        numeric: true
        font.pixelSize: Style.font.displayLarge + Style.space(4)
        font.weight: Font.Medium
        font.letterSpacing: -0.5
      }
      Label {
        Layout.alignment: Qt.AlignBottom
        Layout.bottomMargin: Style.space(5)
        text: root.tr("per_month")
        tone: 0.5
      }
    }
    Label {
      Layout.fillWidth: true
      tone: 0.5
      numeric: true
      font.pixelSize: Style.font.bodySmall
      text: root.totals
        ? root.totals.yearly + " " + root.tr("per_year") + "   ·   " + root.totals.count_text
          + "   ·   ≈ " + root.totals.daily + " " + root.tr("per_day")
        : ""
    }
  }

  // ---- budget -----------------------------------------------------------
  ColumnLayout {
    id: budgetBox
    readonly property var b: root.info ? root.info.budget : null
    Layout.fillWidth: true
    Layout.topMargin: Style.space(14)
    visible: !!b && !root.empty
    spacing: Style.space(6)

    Item {
      Layout.fillWidth: true
      implicitHeight: Style.space(5)
      Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Util.alpha(root.fg, 0.1)
      }
      Rectangle {
        height: parent.height
        width: parent.width * (budgetBox.b ? budgetBox.b.fraction : 0)
        radius: height / 2
        color: budgetBox.b && budgetBox.b.level === "over" ? Commons.Color.urgent
          : Util.alpha(root.fg, budgetBox.b && budgetBox.b.level === "warn" ? 1 : 0.8)
        Behavior on width { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
      }
    }
    RowLayout {
      Layout.fillWidth: true
      Label {
        text: budgetBox.b ? budgetBox.b.pct + "  " + root.tr("of_budget") + " " + budgetBox.b.limit : ""
        numeric: true
        font.pixelSize: Style.font.bodySmall
        tone: 0.75
      }
      Item { Layout.fillWidth: true }
      Label {
        text: budgetBox.b ? budgetBox.b.note : ""
        numeric: true
        font.pixelSize: Style.font.bodySmall
        tone: budgetBox.b && budgetBox.b.level === "over" ? 1 : 0.5
        color: budgetBox.b && budgetBox.b.level === "over" ? Commons.Color.urgent : Util.alpha(root.fg, tone)
      }
    }
  }

  // ---- upcoming ---------------------------------------------------------
  SectionHead {
    visible: !!root.totals && !root.empty
    title: root.tr("soon")
    meta: root.upcoming.length ? (root.info.upcoming_title + "  ·  " + root.info.upcoming_sum) : ""
  }

  Label {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(2)
    visible: !!root.totals && !root.empty && root.upcoming.length === 0
    text: root.tr("nothing_soon")
    tone: 0.45
    font.italic: true
  }

  Repeater {
    model: root.upcoming.slice(0, root.visibleUpcoming)
    delegate: Rectangle {
      id: row
      required property var modelData
      required property int index
      readonly property bool hot: index === root.cursor || rowMouse.containsMouse
      Layout.fillWidth: true
      Layout.leftMargin: -Style.space(6)
      Layout.rightMargin: -Style.space(6)
      implicitHeight: rowLayout.implicitHeight + Style.space(10)
      radius: Style.cornerRadius
      color: hot ? Util.alpha(root.fg, 0.06) : "transparent"
      Behavior on color { ColorAnimation { duration: 100 } }

      RowLayout {
        id: rowLayout
        anchors.fill: parent
        anchors.leftMargin: Style.space(6)
        anchors.rightMargin: Style.space(8)
        spacing: Style.space(12)

        DateTile {
          day: row.modelData.day
          month: row.modelData.month
          urgent: row.modelData.days <= 1
          soon: row.modelData.days <= 3
        }
        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(1)
          RowLayout {
            spacing: Style.space(6)
            Layout.fillWidth: true
            Label {
              Layout.fillWidth: true
              Layout.maximumWidth: implicitWidth
              text: row.modelData.service
              font.weight: Font.DemiBold
            }
            Pill { visible: row.modelData.trial; text: root.tr("trial") }
          }
          Label {
            Layout.fillWidth: true
            text: row.modelData.relative + "  ·  " + row.modelData.category.name
            tone: row.modelData.days <= 1 ? 0.8 : 0.45
            font.pixelSize: Style.font.caption
          }
        }
        ColumnLayout {
          spacing: Style.space(1)
          Label {
            Layout.alignment: Qt.AlignRight
            text: row.modelData.amount
            numeric: true
            font.weight: Font.Medium
          }
          Label {
            Layout.alignment: Qt.AlignRight
            visible: row.modelData.converted !== ""
            text: "≈ " + row.modelData.converted
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
        onEntered: root.cursor = row.index
        onClicked: root.openSettings("subscriptions", { sub_id: row.modelData.id })
      }
    }
  }

  Label {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(2)
    visible: !!root.info && root.info.upcoming_more !== ""
    text: root.info ? root.info.upcoming_more + "  \u2192" : ""
    tone: 0.45
    font.pixelSize: Style.font.caption
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: root.openSettings("overview", null)
    }
  }

  // ---- categories -------------------------------------------------------
  SectionHead {
    visible: root.categories.length > 0
    title: root.tr("categories")
  }

  StackBar {
    id: stack
    Layout.fillWidth: true
    Layout.topMargin: Style.space(2)
    visible: root.categories.length > 0
    items: root.categories
    colors: root.catColors
  }

  GridLayout {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(10)
    visible: root.categories.length > 0
    columns: 2
    columnSpacing: Style.space(18)
    rowSpacing: Style.space(6)

    Repeater {
      model: root.shownCategories
      delegate: RowLayout {
        required property var modelData
        required property int index
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        spacing: Style.space(8)
        Rectangle {
          implicitWidth: Style.space(8)
          implicitHeight: Style.space(8)
          radius: width / 2
          color: root.catColors[index] || root.fg
        }
        Label {
          Layout.fillWidth: true
          text: modelData.name
          tone: 0.8
          font.pixelSize: Style.font.bodySmall
        }
        Label {
          text: modelData.amount
          numeric: true
          tone: 0.55
          font.pixelSize: Style.font.bodySmall
        }
        HoverHandler { onHoveredChanged: stack.highlighted = hovered ? index : -1 }
      }
    }
  }

  // ---- history ----------------------------------------------------------
  SectionHead {
    visible: !!root.info && !!root.info.history && root.info.history.length > 1 && !root.empty
    title: root.tr("half_year")
  }

  Columns {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(2)
    visible: !!root.info && !!root.info.history && root.info.history.length > 1 && !root.empty
    items: root.info && root.info.history ? root.info.history : []
    chartHeight: Style.space(52)
    showValues: true
  }

  // ---- insights ---------------------------------------------------------
  ColumnLayout {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(16)
    visible: !!root.info && !!root.info.insights && root.info.insights.length > 0
    spacing: Style.space(6)

    Repeater {
      model: root.info && root.info.insights ? root.info.insights : []
      delegate: RowLayout {
        required property var modelData
        Layout.fillWidth: true
        spacing: Style.space(8)
        Label {
          Layout.alignment: Qt.AlignTop
          text: modelData.kind === "price" ? "\u{F0535}"
            : modelData.kind === "duplicate" ? "\u{F0191}"
            : modelData.kind === "zombie" ? "\u{F04B2}" : "\u{F051F}"
          tone: 0.7
          font.pixelSize: Style.font.icon
        }
        Label {
          Layout.fillWidth: true
          text: modelData.text
          tone: 0.75
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          elide: Text.ElideNone
        }
      }
    }
  }

  // ---- review -----------------------------------------------------------
  Rectangle {
    readonly property var review: root.info ? root.info.review : null
    Layout.fillWidth: true
    Layout.topMargin: Style.space(14)
    visible: !!review && review.count > 0
    implicitHeight: reviewRow.implicitHeight + Style.space(14)
    radius: Style.cornerRadius
    color: reviewMouse.containsMouse ? Util.alpha(root.fg, 0.09) : Util.alpha(root.fg, 0.05)
    border.width: 1
    border.color: Util.alpha(root.fg, 0.14)

    RowLayout {
      id: reviewRow
      anchors.fill: parent
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(10)
      Pill { strong: true; text: parent.parent.review ? String(parent.parent.review.count) : "" }
      Label {
        Layout.fillWidth: true
        text: parent.parent.review ? parent.parent.review.text : ""
        font.pixelSize: Style.font.bodySmall
      }
      Label { text: "→"; tone: 0.6 }
    }
    MouseArea {
      id: reviewMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.openSettings("review", null)
    }
  }

  // ---- footer -----------------------------------------------------------
  Hairline {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(16)
  }
  RowLayout {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(10)
    spacing: Style.space(6)
    Label {
      Layout.fillWidth: true
      text: root.info ? root.info.updated : ""
      tone: 0.35
      font.pixelSize: Style.font.caption
    }
    Button {
      text: root.tr("add")
      iconText: "\u{F0415}"
      bordered: true
      fontSize: Style.font.bodySmall
      onClicked: root.openSettings("subscriptions", { action: "add" })
    }
    Button {
      text: root.tr("open_app")
      iconText: "\u{F0493}"
      bordered: true
      fontSize: Style.font.bodySmall
      onClicked: root.openSettings("overview", null)
    }
  }

  component SectionHead: RowLayout {
    property string title: ""
    property string meta: ""
    Layout.fillWidth: true
    Layout.topMargin: Style.space(20)
    Layout.bottomMargin: Style.space(6)
    spacing: Style.space(8)
    Caps { text: parent.title }
    Hairline { Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter; strength: 0.08 }
    Label {
      visible: parent.meta !== ""
      text: parent.meta
      tone: 0.42
      numeric: true
      font.pixelSize: Style.font.caption
    }
  }
}
