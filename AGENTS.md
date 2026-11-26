# AGENTS.md

Home Assistant integration for **Ermangizer ER-G-220-02** and related variable
frequency drives that control well pumps, reading telemetry and driving the pump
over Modbus. One integration entry = one physical bus; controllers are subentries.

## Commands

```bash
pip install -r requirements-dev.txt
python -m pytest                                    # all tests
python -m pytest tests/test_pump.py -q              # one file
python -m pytest tests/test_init.py -q --timeout=30 # e2e only (slow)
python -m pyflakes custom_components/ermangizer scripts tests
```

Unit tests (`test_protocol`, `test_layouts`, `test_codes`, `test_pump`) do not
require Home Assistant — the core (`const`, `models`, `protocol`, `codes`,
`params`, `layouts`, `pump`, `units`) imports without it. `__init__.py` loads
platforms lazily for this reason: do not break it, or scripts and unit tests
will stop running outside HA.

## Structure

```
const.py        configuration keys, defaults
models.py       RegisterDef / ParamDef / CoilDef / BlockDef
layouts.py      register maps (legacy_220_01, modern_220_02_05) and read blocks
params.py       P001..P2xx parameter registry with access levels
codes.py        status-word and alarm-word decoding
protocol.py     CRC-16 and RTU frames (for rtu_over_tcp and serial)
pump.py         PumpData assembly, block reads, decode_registers, detect_layout
modbus_client.py gateway: one connection per entry, registry in hass.data
coordinator.py  two polling rates on one coordinator
entity.py       PumpIdentity + entity base classes
config_flow.py  network -> controller -> "add another" -> menu
sensor/binary_sensor/switch/button/number/select.py
```

## Invariants — change only with a reason

- **Pressure is labelled `bar` without conversion.** The register, the device
  display and Home Assistant show the same number. 1 kgf/cm² = 0.980665 bar; the
  ~2 % error is deliberate: converting would diverge from the device panel. Do
  not add a "for accuracy" conversion — it breaks setpoint correspondence.
- **`unique_id` = `{subentry_id}-{key}`.** The key is the register/parameter/coil
  name. It becomes the entity_id, so it cannot be renamed: HA would delete the
  entity and lose history and user settings. The UI name changes via
  `translations`.
- **Entities are added one subentry at a time** —
  `async_add_entities(list, config_subentry_id=...)`. A flat list across all
  pumps would attach them to the config entry and break device grouping.
- **Switch position is read from the status word, not the coil.** Start/stop
  coils are command pulses; their state is not stored.
- **tmodbus: writes use `write_single_register` / `write_single_coil`.** There is
  no `write_holding_register` method; the typo surfaces only on a live write,
  i.e. in production.
- **Do not widen read blocks blindly.** Adjacent registers are merged into one
  read, but the gap is capped: an extra request on a half-duplex bus costs more
  than a few registers read in vain.
- **Layout autodetection picks the first responder.** If the device answers both
  status addresses, the layout must be set manually.

## Tests

`tests/fake_device.py` is a fake Modbus TCP device. Two facts it has already
tripped on:

- MBAP `pack(">HHHB", transaction, 0, length, unit)` — an 8-byte format, and the
  transaction id must match the request: the client correlates responses by it
  and silently drops the rest.
- `Server.wait_closed()` hangs the fixture: it waits for handlers to finish, and
  a handler lives until the integration unloads. The fixture closes the sockets
  itself.

`tests/test_init.py` are end-to-end tests that boot a real HA. They are the only
ones that catch errors like a missing `unique_id` or a wrong tmodbus method name:
a run through the real `config flow` is mandatory for changes to `config_flow.py`,
`entity.py` and the platforms.

The `enable_socket()` fixture is needed inside the async device fixture — the
`pytest.mark.enable_socket` marker does not reach async fixtures.

## CI

`.github/workflows/ci.yml` — lint + tests on GitHub's `ubuntu-latest` runner,
with `actions/setup-python` pinned to Python 3.13 (HA requires >= 3.13.2).

## Versions and the install archive

The version lives in `custom_components/ermangizer/manifest.json` (`version`) —
the single source; `hacs.json` does not carry a version and takes it from the
release.

A release is created on GitHub with the archive for manual installation attached:
`custom_components/`, `LICENSE`, `README.md`, without `__pycache__`.

The test stack in `requirements-dev.txt` is pinned and excluded from Dependabot
in `.github/dependabot.yml`: `pytest-homeassistant-custom-component` is built
against a specific Home Assistant version, and a desync shows up as fixtures
silently missing, not as a clear error.

## Manufacturer documentation

The register map and status codes come from the official ER-G-220-02 documents:
the user manual, the parameter table, and the "MODBUS communication protocol"
sheet. When editing `layouts.py` / `codes.py`, check against them — the
manufacturer's tables contain typos, and corrections must be marked in a comment.
