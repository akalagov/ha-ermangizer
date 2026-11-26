"""Constants for the Ermangizer integration."""
from __future__ import annotations

DOMAIN = "ermangizer"
MANUFACTURER = "КБ АГАВА / ЭРМАНДЖАЙЗЕР"

# --- Config entry / subentry keys ------------------------------------------
CONF_CONNECTION_TYPE = "connection_type"
CONF_LAYOUT = "layout"
CONF_UNIT_ID = "unit_id"
CONF_POLL_INTERVAL = "poll_interval"
CONF_SLOW_POLL_INTERVAL = "slow_poll_interval"
CONF_ACCESS_LEVEL = "access_level"

# Serial-only keys (connection_type == CONNECTION_SERIAL)
CONF_BAUDRATE = "baudrate"
CONF_PARITY = "parity"
CONF_STOPBITS = "stopbits"
CONF_BYTESIZE = "bytesize"

# Pause between two Modbus requests on one bus, milliseconds. RS-485 is half
# duplex and cheap adapters need a moment after a response before they can
# carry the next request; Home Assistant's own modbus integration defaults to
# 30 ms for the same reason.
CONF_WAIT_BETWEEN_REQUESTS = "wait_between_requests_ms"

SUBENTRY_TYPE_PUMP = "pump"

# --- Connection types ------------------------------------------------------
# Native Modbus TCP: the gateway speaks Modbus itself and wraps the PDU in an
# MBAP header. This is what a multi-port serial-to-Ethernet gateway (MGate and
# clones) uses when a port is configured as "Modbus TCP" - one TCP port per
# serial port. The RS-485 baud rate of such a port is set on the gateway and is
# invisible to Home Assistant.
CONNECTION_TCP = "tcp"
# Transparent serial-to-TCP bridge: raw RTU frames (CRC included) forwarded
# over a socket, e.g. Elfin EW11, USR-W610/TCP232.
CONNECTION_RTU_OVER_TCP = "rtu_over_tcp"
# USB-RS485 adapter plugged into the machine running Home Assistant.
CONNECTION_SERIAL = "serial"

CONNECTION_TYPES = [CONNECTION_TCP, CONNECTION_RTU_OVER_TCP, CONNECTION_SERIAL]

DEFAULT_TCP_PORT = 502
DEFAULT_BAUDRATE = 9600
DEFAULT_PARITY = "N"
DEFAULT_STOPBITS = 1
DEFAULT_BYTESIZE = 8

PARITY_OPTIONS = ["N", "E", "O"]

# Network gateways queue requests themselves, a plain serial bus does not.
DEFAULT_WAIT_BETWEEN_REQUESTS_NETWORK = 20
DEFAULT_WAIT_BETWEEN_REQUESTS_SERIAL = 30

# --- Register layouts ------------------------------------------------------
LAYOUT_AUTO = "auto"
# ER-G-220-01(02) "MODBUS communication protocol" (doc v1.4, FW 1.0.9.2): telemetry in
# the low input-register block, status word at 1024, alarm word at 1026.
LAYOUT_LEGACY = "legacy_220_01"
# ER-G-220-02 / ERG-220-05 (2025): telemetry at 2000+, menu parameters at
# 1000+NNN.
LAYOUT_MODERN = "modern_220_02_05"

LAYOUTS = [LAYOUT_LEGACY, LAYOUT_MODERN]

# --- Polling ---------------------------------------------------------------
# Fast block = run/stop state, which automations act on. Slow block = analogue
# telemetry, which changes on the scale of seconds to minutes.
DEFAULT_POLL_INTERVAL = 5
DEFAULT_SLOW_POLL_INTERVAL = 60

# Alarm history is polled on demand only, never per cycle.
HISTORY_BASE_ADDRESS = 3000
HISTORY_RECORDS = 50
HISTORY_RECORD_STRIDE = 10

# --- Read block tuning -----------------------------------------------------
# Merging nearby registers into one request costs a few wasted registers but
# saves a full round trip on a half duplex bus.
MAX_REGISTER_GAP = 8
MIN_REGISTERS_PER_READ = 16

# Access levels mirror the device's own P099 access levels.
ACCESS_MONITOR = "monitor"
ACCESS_GENERAL = "general"
ACCESS_ADVANCED = "advanced"
ACCESS_FACTORY = "factory"

ACCESS_LEVELS = [ACCESS_MONITOR, ACCESS_GENERAL, ACCESS_ADVANCED, ACCESS_FACTORY]
