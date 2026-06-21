"""Bridge to the reused hub device layer.

The hub modules (``controller``, ``config``, ``transport.*``) predate this
package and import each other by bare name, so they only resolve with ``hub/``
itself on ``sys.path``. Rather than edit the (deprecated) hub — which would
break ``make dashboard``/``make run`` that run its scripts directly — we add
``hub/`` to the path here, in one place, and re-export the pieces the backend
needs. The hub stays the single source of truth for the wire protocol.
"""
import os
import sys

_HUB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "hub"))
if _HUB_DIR not in sys.path:
    sys.path.insert(0, _HUB_DIR)

# Imported for re-export; resolved against _HUB_DIR above.
import config  # noqa: E402
from controller import Controller  # noqa: E402
from transport.ble_transport import BLETransport  # noqa: E402

__all__ = ["config", "Controller", "BLETransport"]
