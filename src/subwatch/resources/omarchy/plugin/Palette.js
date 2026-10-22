.pragma library

// Colours for charts, taken from the current Omarchy theme (colors.toml).
// Colourful themes give every category its own hue. Monochrome themes
// (Vantablack, Matte Black and friends) get an evenly spaced grey ramp
// instead, because their "blue" and "green" are greys a few steps apart.

var ORDER = ["blue", "magenta", "cyan", "green", "yellow", "orange", "red",
             "bright_blue", "bright_magenta", "bright_cyan", "bright_green", "bright_yellow"]

function parse(text) {
  var out = {}
  var lines = String(text || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var m = lines[i].match(/^\s*([a-z_]+)\s*=\s*"(#[0-9a-fA-F]{6})"/)
    if (m) out[m[1]] = m[2]
  }
  return out
}

function _rgb(hex) {
  return [parseInt(hex.substr(1, 2), 16) / 255, parseInt(hex.substr(3, 2), 16) / 255,
          parseInt(hex.substr(5, 2), 16) / 255]
}

function saturation(hex) {
  var c = _rgb(hex)
  var max = Math.max(c[0], c[1], c[2]), min = Math.min(c[0], c[1], c[2])
  if (max === 0) return 0
  return (max - min) / max
}

function monochrome(palette) {
  var seen = 0, colourful = 0
  for (var i = 0; i < ORDER.length; i++) {
    var hex = palette[ORDER[i]]
    if (!hex) continue
    seen++
    if (saturation(hex) > 0.12) colourful++
  }
  return seen === 0 || colourful < 2
}

// n colours for n series; `fg` is the theme foreground (a QML color).
function series(palette, n, fg) {
  var out = []
  if (!monochrome(palette)) {
    var hues = []
    for (var i = 0; i < ORDER.length; i++) {
      var hex = palette[ORDER[i]]
      if (hex && hues.indexOf(hex.toLowerCase()) === -1) hues.push(hex.toLowerCase())
    }
    for (var j = 0; j < n; j++) out.push(hues[j % hues.length])
    return out
  }
  // Grey ramp from the foreground down, steps wide enough to tell apart.
  for (var k = 0; k < n; k++) {
    var a = n <= 1 ? 1 : 1 - (k / Math.max(1, n - 1)) * 0.72
    out.push(Qt.rgba(fg.r, fg.g, fg.b, a))
  }
  return out
}
