import QtQuick
import QtQuick.Shapes

// The Subwatch mark: a dial whose arc shows how much of the month is spoken
// for (budget used, or how close the next charge is) and a dot in the
// middle when something needs attention.
Item {
  id: ring

  property real size: 16
  property real value: 0
  property color color: "white"
  property color track: Qt.rgba(color.r, color.g, color.b, 0.22)
  property real thickness: Math.max(1.6, size * 0.12)
  property bool dot: false
  property bool animated: true

  readonly property real radius: (size - thickness) / 2
  property real shown: Math.max(0, Math.min(1, value))
  Behavior on shown {
    enabled: ring.animated
    NumberAnimation { duration: 650; easing.type: Easing.OutCubic }
  }

  implicitWidth: size
  implicitHeight: size

  Shape {
    anchors.fill: parent
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
      strokeColor: ring.track
      strokeWidth: ring.thickness
      fillColor: "transparent"
      PathAngleArc {
        centerX: ring.size / 2
        centerY: ring.size / 2
        radiusX: ring.radius
        radiusY: ring.radius
        startAngle: 0
        sweepAngle: 360
      }
    }

    ShapePath {
      strokeColor: ring.shown > 0.001 ? ring.color : "transparent"
      strokeWidth: ring.thickness
      fillColor: "transparent"
      capStyle: ShapePath.RoundCap
      PathAngleArc {
        centerX: ring.size / 2
        centerY: ring.size / 2
        radiusX: ring.radius
        radiusY: ring.radius
        startAngle: -90
        sweepAngle: 360 * ring.shown
      }
    }
  }

  Rectangle {
    anchors.centerIn: parent
    width: Math.max(3, Math.round(ring.size * 0.26))
    height: width
    radius: width / 2
    color: ring.color
    scale: ring.dot ? 1 : 0
    Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutBack } }
  }
}
