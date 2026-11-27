"""Hard network block for offline_local runs (plan §3.3: offline forbids external APIs).

``forbid_network()`` patches socket connect/DNS so that any attempt raises NetworkForbidden,
which makes "no network access" testable rather than a convention.
"""
from __future__ import annotations

import socket
from contextlib import contextmanager
from typing import Iterator


class NetworkForbidden(RuntimeError):
    pass


_ACTIVE = 0
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo
_orig_create_connection = socket.create_connection


def _blocked(*_a, **_k):
    raise NetworkForbidden("network access is forbidden in offline_local mode")


def _connect(self, address):  # allow local AF_UNIX sockets (sqlite does not use them, subprocess pipes neither)
    if self.family == socket.AF_UNIX:
        return _orig_connect(self, address)
    _blocked()


def _connect_ex(self, address):
    if self.family == socket.AF_UNIX:
        return _orig_connect_ex(self, address)
    _blocked()


@contextmanager
def forbid_network() -> Iterator[None]:
    global _ACTIVE
    _ACTIVE += 1
    if _ACTIVE == 1:
        socket.socket.connect = _connect          # type: ignore[method-assign]
        socket.socket.connect_ex = _connect_ex    # type: ignore[method-assign]
        socket.getaddrinfo = _blocked             # type: ignore[assignment]
        socket.create_connection = _blocked       # type: ignore[assignment]
    try:
        yield
    finally:
        _ACTIVE -= 1
        if _ACTIVE == 0:
            socket.socket.connect = _orig_connect           # type: ignore[method-assign]
            socket.socket.connect_ex = _orig_connect_ex     # type: ignore[method-assign]
            socket.getaddrinfo = _orig_getaddrinfo          # type: ignore[assignment]
            socket.create_connection = _orig_create_connection  # type: ignore[assignment]


def network_forbidden() -> bool:
    return _ACTIVE > 0
