import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Commons as Commons

// Vertical scrolling for a page, with a thin bar that only shows on hover.
Flickable {
  id: flick
  default property alias content: inner.data
  property real bottomPadding: Style.space(60)

  clip: true
  contentWidth: width
  contentHeight: inner.implicitHeight + Style.space(22) + bottomPadding
  boundsBehavior: Flickable.StopAtBounds
  ScrollBar.vertical: ScrollBar {
    policy: flick.contentHeight > flick.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
    contentItem: Rectangle {
      implicitWidth: Style.space(4)
      radius: width / 2
      color: Util.alpha(Commons.Color.foreground, parent.active ? 0.35 : 0.15)
    }
  }

  Item {
    id: inner
    y: Style.space(22)
    width: flick.width - Style.space(14)
    implicitHeight: childrenRect.height
  }
}
