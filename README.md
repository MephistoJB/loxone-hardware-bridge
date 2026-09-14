# Loxone Hardware Bridge

Loxone Hardware Bridge is a HACS custom integration for Home Assistant that
discovers physical Loxone hardware directly through the local Miniserver API.
It does not require virtual status blocks and does not depend on entities being
visible in the normal Loxone app structure.

The first supported device is the **Loxone Window Handle Air**.

## Features

- Automatic discovery through `/jdev/sps/enumdev`, `/jdev/sps/enumin` and
  `/data/status`
- One Home Assistant device per physical window handle
- Three-state position: closed, tilted and open
- Native window and vibration binary sensors
- Battery percentage and low-battery warning
- Physical online state, last reception time, radio hops and radio quality
- Encrypted WebSocket push when a matching LoxAPP state UUID exists
- Fast HTTP polling that always remains active as a reliability fallback
- UI configuration and reconfiguration of host, port and credentials
- Configurable update intervals
- Redacted Home Assistant diagnostics

## Installation with HACS

1. Open HACS in Home Assistant.
2. Open **Custom repositories**.
3. Add this repository as category **Integration**.
4. Download **Loxone Hardware Bridge**.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration** and select
   **Loxone Hardware Bridge**.
7. Enter the local Miniserver address and a Loxone user with permission to read
   the physical inputs and status endpoints.

Credentials are stored in the Home Assistant config entry. They are never
written to logs or diagnostics.

## Update mechanisms

The integration deliberately combines several mechanisms:

| Data | Mechanism | Default interval |
| --- | --- | --- |
| Position and vibration | Encrypted WebSocket push where available | Immediate |
| Position and vibration | HTTP polling fallback | 2 seconds |
| Device discovery and online status | HTTP polling | 30 seconds |
| Battery percentage and battery-low input | HTTP polling | 15 minutes |

All intervals and WebSocket push can be changed under the integration's
**Configure** button.

### Why polling remains enabled

Loxone WebSocket events are identified by state UUIDs from `LoxAPP3.json`.
Physical addresses such as `0C000001.B299C3.AI2` are always readable over HTTP,
but only produce assignable push events when the input is published in the
Loxone visualization and therefore has a state UUID. Polling guarantees that
every discovered handle works even without that configuration and also repairs
a missed event or temporary WebSocket outage.

### Enabling push for a window handle

Publishing only these two physical inputs is recommended:

- `AI2` — Position
- `I4` — Alarm/vibration

Give them unique names based on the physical device, for example:

```text
EG_WZ_Fenster_Rechts_Position
EG_WZ_Fenster_Rechts_Alarm
```

The integration matches the physical input name from `/jdev/sps/enumin` with
the corresponding `InfoOnlyAnalog` or `InfoOnlyDigital` control in
`LoxAPP3.json`. The redundant `closed` (`I2`) and `tilted` (`I3`) inputs are not
required because both states are derived from `AI2`.

## Position values

| Raw value | Home Assistant state |
| --- | --- |
| `1` | Closed |
| `2` | Tilted |
| `3` | Open |
| anything else | Unknown |

An offline device may still return a cached value from `/jdev/sps/io`. The
integration therefore treats `/data/status` as authoritative for availability
and does not present a stale position as live.

## Entities

Each Window Handle Air creates:

- Position enum sensor
- Window binary sensor (on for tilted or open)
- Vibration binary sensor
- Battery sensor
- Battery-low binary sensor
- Online binary sensor
- Last-received timestamp
- Device and Air Base radio-quality sensors
- Radio-hop sensor

The Air Base device also exposes the encrypted push-connection state.

## Security

- Prefer a dedicated Loxone user with only the read permissions needed by this
  integration.
- Use local access. Do not expose the Miniserver HTTP port to the internet.
- HTTPS/WSS and certificate verification can be enabled for installations that
  support them.
- Passwords are removed from Home Assistant diagnostics.

## Troubleshooting

If **Push connection** is off, the integration continues to work through HTTP
polling. Check that the user can open `LoxAPP3.json`, that the selected inputs
are visible in the Loxone visualization and that their names are unique.

For detailed logging:

```yaml
logger:
  logs:
    custom_components.loxone_hardware: debug
```

Do not publish logs containing private network topology or unredacted Loxone
responses.

## Supported environment

- Home Assistant 2026.8 or newer
- Loxone Miniserver with local Web Services and WebSocket API
- Loxone Air Base Extension
- Loxone Window Handle Air

## License

MIT

