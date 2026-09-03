"""Single-instance IPC: let a second launch summon the running instance.

The first instance listens on a local socket. Any later launch of the
binary sends a command token (e.g. "activate") and exits, so compositor
keybinds / launchers / CLI can always "summon" the app without depending
on a specific desktop environment (niri, hyprland, GNOME custom binds…).
"""

from __future__ import annotations

import logging
import uuid

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

ACTIVATE_SERVER_NAME = "ai-translator-activate"


class ActivateServer(QObject):
    """Listens for command tokens from second-instance launches."""

    command_received = Signal(str)

    def __init__(self, name: str = ACTIVATE_SERVER_NAME, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self._name = name
        self._server = QLocalServer(self)
        self._clients: list[QLocalSocket] = []

    def start(self) -> bool:
        """Bind the socket; False means another app owns the name (degrade)."""
        # A leftover socket file from a crashed run must not block us.
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            log.warning("activate server listen failed: %s", self._server.errorString())
            return False
        self._server.newConnection.connect(self._accept_client)
        return True

    def stop(self) -> None:
        self._server.close()
        for sock in list(self._clients):
            sock.disconnectFromServer()
        self._clients.clear()

    def _accept_client(self) -> None:
        while True:
            sock = self._server.nextPendingConnection()
            if sock is None:
                return
            self._clients.append(sock)
            sock.readyRead.connect(lambda s=sock: self._drain(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _drain(self, sock: QLocalSocket) -> None:
        data = bytes(sock.readAll()).decode("utf-8", errors="ignore")
        for token in data.split():
            token = token.strip()
            if token:
                self.command_received.emit(token)

    def _drop(self, sock: QLocalSocket) -> None:
        if sock in self._clients:
            self._clients.remove(sock)
        sock.deleteLater()


def notify_running(
    command: str = "activate",
    timeout_ms: int = 400,
    name: str = ACTIVATE_SERVER_NAME,
) -> bool:
    """Tell the running instance to handle `command`; True when delivered.

    Requires a QCoreApplication to exist (QLocalSocket belongs to QtNetwork).
    """
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        log.info("no running instance reachable on %s", ACTIVATE_SERVER_NAME)
        return False
    payload = (command.strip() + "\n").encode("utf-8")
    sock.write(payload)
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


def unique_server_name() -> str:
    """A per-test socket name to avoid cross-test interference."""
    return f"{ACTIVATE_SERVER_NAME}-test-{uuid.uuid4().hex[:8]}"
