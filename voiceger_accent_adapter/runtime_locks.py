"""Process-global locks for upstream runtimes with mutable global state."""

from threading import RLock


LANGSEGMENT_LOCK = RLock()
