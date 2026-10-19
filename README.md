# dbus-pwrtool

A Venus OS driver that shows [PwrTool 500](https://vdbx.io) shunts (ESPHome, ESP32-C3) as native devices on a Victron GX or a Raspberry Pi running Venus OS.

Each PwrTool gets one role:

| Role | Venus service | Shows up as |
| --- | --- | --- |
| `battery` | `com.victronenergy.battery` | A battery monitor: voltage, current, power, state of charge, capacity. Selectable under Settings → System setup → Battery monitor |
| `dcsystem` | `com.victronenergy.dcsystem` | Measured "DC loads". Venus adds every `dcsystem` meter into its DC system figure instead of calculating it |
| `dcload` | `com.victronenergy.dcload` | A single DC load, listed on its own but not counted as DC system |

Use `dcsystem` only when every DC load branch has its own meter. Otherwise unmetered branches drop out of the DC loads figure. Until then, use `dcload` and let Venus keep calculating DC system.

**Status: prototype (v0.1.0).** It runs on the author's own system (Venus OS v3.81 on a Raspberry Pi 3B). There's no installer yet, and see [Security](#security) before putting it on a network you don't fully trust.

## How it works

The driver opens each PwrTool's ESPHome `web_server` event stream (`http://<pwrtool>/events`) and publishes the readings once a second, so stock PwrTool firmware works with no YAML changes. It accepts both web_server v2 ids (`sensor-bus_-_current`) and v3 ids (`sensor/Bus - Current`).

If a PwrTool sends nothing for 5 seconds, its values go invalid and `/Connected` is set to 0, so Venus doesn't act on stale data.

| PwrTool sensor | Venus path |
| --- | --- |
| Bus - Voltage | `/Dc/0/Voltage` |
| Bus - Current | `/Dc/0/Current` (positive = into the battery / into the loads) |
| Bus - Power | `/Dc/0/Power` |
| State of Charge (SoC) | `/Soc` (battery role only) |

## Install (manual, for now)

On the Venus device, as root:

```sh
mkdir -p /data/apps/dbus-pwrtool
# copy dbus-pwrtool.py, start.sh and service/ into /data/apps/dbus-pwrtool
cd /data/apps/dbus-pwrtool
cp config.example.json config.json   # then edit it
chmod +x dbus-pwrtool.py start.sh service/run service/log/run
echo 'bash /data/apps/dbus-pwrtool/start.sh >> /data/apps/dbus-pwrtool/start.log 2>&1 &' >> /data/rc.local
bash start.sh
```

`/data` survives Venus OS firmware updates. `/service` is rebuilt at every boot by `start.sh`. Logs go to `/var/log/dbus-pwrtool/current`.

## config.json

```json
[
  {"host": "pwrtool500-cold-2404.local", "role": "battery", "name": "PwrTool Battery Shunt", "instance": 140, "capacity": 314},
  {"host": "pwrtool500-237bbc.local", "role": "dcsystem", "name": "PwrTool DC Loads", "instance": 141}
]
```

- `host`: the PwrTool's `.local` name (Venus resolves mDNS) or IP address.
- `instance`: the Venus device instance. Pick a free one per device.
- `capacity`: battery role only, in Ah.

## Security

The PwrTool's `web_server` currently has no authentication, so anyone on the LAN can read it (and toggle its outputs). This driver reads it the same way. Before this is ready for general use, it needs to work with authenticated or encrypted access. The plan is either web_server digest auth or the encrypted native API; see the issues.

## License

MIT, see [LICENSE](LICENSE). Uses Victron's `velib_python` from the Venus OS image.
