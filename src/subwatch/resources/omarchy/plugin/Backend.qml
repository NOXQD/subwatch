import QtQuick
import Quickshell.Io
import "Env.js" as Env

// Bridge to `subwatch gui-server`: one JSON object per line each way. The
// process lives as long as the settings window; the shell unloads the
// window (and with it this process) when it is closed.
Item {
  id: root

  property bool started: false
  property int nextId: 1
  property var callbacks: ({})
  property var queue: []

  signal event(var message)
  signal failed(string message)

  function request(cmd, args, callback) {
    var msg = {}
    for (var k in (args || {})) msg[k] = args[k]
    msg.id = nextId++
    msg.cmd = cmd
    if (callback) callbacks[msg.id] = callback
    var line = JSON.stringify(msg) + "\n"
    if (started) proc.write(line)
    else queue.push(line)
    return msg.id
  }

  function handleLine(line) {
    var msg
    try {
      msg = JSON.parse(line)
    } catch (e) {
      return
    }
    if (msg.event !== undefined) {
      root.event(msg)
      return
    }
    var cb = callbacks[msg.id]
    if (!cb) return
    delete callbacks[msg.id]
    cb(msg.ok === true, msg.ok ? msg.data : (msg.error || ""), msg.hint || "")
  }

  Process {
    id: proc
    command: [Env.exe, "--quiet", "gui-server"]
    running: true
    stdinEnabled: true

    stdout: SplitParser {
      onRead: function(line) { root.handleLine(line) }
    }
    stderr: SplitParser {
      onRead: function(line) { console.warn("subwatch:", line) }
    }

    onStarted: {
      root.started = true
      var pending = root.queue
      root.queue = []
      for (var i = 0; i < pending.length; i++) proc.write(pending[i])
    }

    onExited: function(code) {
      root.started = false
      var pending = root.callbacks
      root.callbacks = ({})
      for (var id in pending) {
        try { pending[id](false, "", "") } catch (e) {}
      }
      root.failed(String(code))
      restart.start()
    }
  }

  Timer {
    id: restart
    interval: 1500
    onTriggered: proc.running = true
  }
}
