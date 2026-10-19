#!/usr/bin/env python3
"""dbus-pwrtool: publish PwrTool 500 (ESPHome) readings on the Venus OS dbus.

Each PwrTool in config.json becomes one Venus service, chosen by its role:
  battery   -> com.victronenergy.battery.<id>   (battery monitor: V, A, W, SoC, capacity)
  dcsystem  -> com.victronenergy.dcsystem.<id>  (measured "DC system" loads)
  dcload    -> com.victronenergy.dcload.<id>    (a single DC load, shown but not counted as DC system)

Readings come from the PwrTool's ESPHome web_server event stream (/events, server-sent
events), so stock PwrTool firmware works unchanged and values are pushed, not polled.
Works with web_server v2 ids ("sensor-bus_-_current") and v3 ids ("sensor/Bus - Current").
If a PwrTool sends nothing for STALE_S seconds, its values go invalid and /Connected = 0.

Config: config.json next to this file (see config.example.json).
"""
import json
import logging
import os
import re
import sys
import threading
import time
import http.client

sys.path.insert(1, "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
from gi.repository import GLib  # noqa: E402
import dbus  # noqa: E402
from vedbus import VeDbusService  # noqa: E402

VERSION = "0.1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
STALE_S = 5.0
log = logging.getLogger("dbus-pwrtool")

# PwrTool sensor (normalised name) -> Venus path, per role
SENSORS = {
    "bus___voltage": "/Dc/0/Voltage",
    "bus___current": "/Dc/0/Current",
    "bus___power": "/Dc/0/Power",
    "state_of_charge__soc_": "/Soc",
}
ROLE_PATHS = {
    "battery": ["/Dc/0/Voltage", "/Dc/0/Current", "/Dc/0/Power", "/Soc"],
    "dcsystem": ["/Dc/0/Voltage", "/Dc/0/Current", "/Dc/0/Power"],
    "dcload": ["/Dc/0/Voltage", "/Dc/0/Current", "/Dc/0/Power"],
}
UNITS = {"/Dc/0/Voltage": "V", "/Dc/0/Current": "A", "/Dc/0/Power": "W", "/Soc": "%"}


def norm(entity_id):
    """'sensor-bus_-_current' or 'sensor/Bus - Current' -> 'bus___current'"""
    name = re.split(r"[-/]", entity_id, maxsplit=1)[1] if re.match(r"^sensor[-/]", entity_id) else entity_id
    return re.sub(r"[^a-z0-9]", "_", name.lower())


class PwrToolStream(threading.Thread):
    """Reads one PwrTool's /events stream forever and keeps the latest sensor values."""

    def __init__(self, host):
        super().__init__(daemon=True)
        self.host = host
        self.values = {}
        self.last_update = 0.0
        self.lock = threading.Lock()

    def run(self):
        backoff = 1
        while True:
            try:
                conn = http.client.HTTPConnection(self.host, 80, timeout=10)
                conn.request("GET", "/events", headers={"Accept": "text/event-stream"})
                resp = conn.getresponse()
                if resp.status != 200:
                    raise IOError("HTTP %d" % resp.status)
                log.info("%s: connected", self.host)
                backoff = 1
                event = None
                while True:
                    line = resp.readline()
                    if not line:
                        raise IOError("stream closed")
                    line = line.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event == "state":
                        self._state(line[5:])
                    elif line.startswith("data:") and event == "ping":
                        with self.lock:
                            self.last_update = time.monotonic()
            except Exception as e:  # network errors, device reboot, timeouts
                log.warning("%s: %s, reconnecting in %ds", self.host, e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _state(self, data):
        try:
            d = json.loads(data)
        except ValueError:
            return
        key = norm(d.get("id", ""))
        v = d.get("value")
        if key in SENSORS and isinstance(v, (int, float)):
            with self.lock:
                self.values[SENSORS[key]] = float(v)
                self.last_update = time.monotonic()

    def snapshot(self):
        with self.lock:
            fresh = time.monotonic() - self.last_update < STALE_S
            return (dict(self.values) if fresh else None)


class PwrToolService:
    def __init__(self, cfg):
        self.cfg = cfg
        role = cfg["role"]
        if role not in ROLE_PATHS:
            raise SystemExit("unknown role %r for %s" % (role, cfg["host"]))
        self.paths = ROLE_PATHS[role]
        ident = re.sub(r"[^a-z0-9]", "_", cfg["host"].split(".")[0].lower())
        bus = dbus.SystemBus(private=True)
        self.svc = VeDbusService("com.victronenergy.%s.pwrtool_%s" % (role, ident), bus=bus, register=False)
        s = self.svc
        s.add_path("/Mgmt/ProcessName", "dbus-pwrtool")
        s.add_path("/Mgmt/ProcessVersion", VERSION)
        s.add_path("/Mgmt/Connection", "ESPHome web_server %s" % cfg["host"])
        s.add_path("/DeviceInstance", int(cfg["instance"]))
        s.add_path("/ProductId", 0xFFFF)
        s.add_path("/ProductName", "PwrTool 500")
        s.add_path("/CustomName", cfg.get("name", "PwrTool 500"), writeable=True)
        s.add_path("/FirmwareVersion", None)
        s.add_path("/HardwareVersion", None)
        s.add_path("/Serial", ident)
        s.add_path("/Connected", 0)
        if role == "battery":
            s.add_path("/Capacity", cfg.get("capacity"))
            s.add_path("/InstalledCapacity", cfg.get("capacity"))
        for p in self.paths:
            s.add_path(p, None, gettextcallback=lambda path, v, u=UNITS[p]: "%.2f%s" % (v, u) if v is not None else "")
        s.register()
        self.stream = PwrToolStream(cfg["host"])
        self.stream.start()

    def update(self):
        vals = self.stream.snapshot()
        with self.svc as s:
            if vals is None or not all(p in vals for p in self.paths):
                s["/Connected"] = 0
                for p in self.paths:
                    s[p] = None
            else:
                s["/Connected"] = 1
                for p in self.paths:
                    s[p] = round(vals[p], 3)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    services = [PwrToolService(c) for c in cfg]
    log.info("dbus-pwrtool %s: %d device(s)", VERSION, len(services))

    def tick():
        for s in services:
            s.update()
        return True

    GLib.timeout_add(1000, tick)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
