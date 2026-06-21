"""WebSocket message vocabulary (shared mental model for both ends).

Every frame is JSON ``{"type": ...}``. Validation is intentionally light — the
server checks the type and a couple of enum fields, then routes to the command
queue / event flags; it never touches the Controller from the socket.
"""
from backend.control.arbiter import MODES  # ("manual","auto","ml")
from backend.hardware.roles import ROLES    # ("stirrer","glucose","naoh","light")

# ── client → server ──────────────────────────────────────────────────────────
C_SET_ACTUATOR = "set_actuator"        # {role, value}
C_PULSE_ACTUATOR = "pulse_actuator"    # {role, ms}
C_SET_MODE = "set_mode"                # {mode}
C_SET_MODEL = "set_model"              # {name}
C_SET_MODEL_PARAMS = "set_model_params"  # {params}
C_RECALIBRATE = "recalibrate"          # {}
C_RELOAD_CONFIG = "reload_config"      # {}
C_RESET_RUN = "reset_run"              # {}
C_PING = "ping"                        # {}

# ── server → client ──────────────────────────────────────────────────────────
S_STATE = "state"          # full snapshot + narr_new[]
S_CONFIG = "config"        # hardware layout + roles + models (sent on connect / reload)
S_ACK = "ack"              # {ref, ok, msg?}
S_CALIBRATION = "calibration"  # {status, wb, white_c}

VALID_ROLES = set(ROLES)
VALID_MODES = set(MODES)
