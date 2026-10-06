#!/usr/bin/env python3
"""Wall dashboard prototype: CTA bus arrivals + weather.

    CTA_API_KEY=yourkey python3 server.py      # then open http://localhost:8080

Without CTA_API_KEY it serves mock bus data so you can work on the UI.
Weather comes from Open-Meteo, which needs no key. Standard library only.
"""
import json
import os
import random
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CHICAGO = ZoneInfo("America/Chicago")
CTA_BASE = "https://www.ctabustracker.com/bustime/api/v2"
CONFIG = json.loads((ROOT / "config.json").read_text())
CTA_KEY = os.environ.get("CTA_API_KEY", "").strip()


def http_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "wall-dashboard-prototype"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def cta(endpoint, **params):
    """Call a Bus Tracker endpoint and return the inner 'bustime-response' dict."""
    query = urllib.parse.urlencode({"key": CTA_KEY, "format": "json", **params})
    return http_json(f"{CTA_BASE}/{endpoint}?{query}")["bustime-response"]


class Cached:
    """Runs fn at most once per ttl seconds. Keeps the last good value if a refresh fails."""

    def __init__(self, fn, ttl):
        self.fn, self.ttl = fn, ttl
        self.value, self.error = None, None
        self.attempted_at = 0.0
        self.ok_at = None
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            if time.time() - self.attempted_at >= self.ttl:
                self.attempted_at = time.time()
                try:
                    self.value, self.error = self.fn(), None
                    self.ok_at = self.attempted_at
                except Exception as e:  # network down, bad key, API change...
                    self.error = f"{type(e).__name__}: {e}"
            return {
                "data": self.value,
                "error": self.error,
                "updated_ms": int(self.ok_at * 1000) if self.ok_at else None,
            }


# ---------------------------------------------------------------- buses

def cta_time_to_ms(s):
    """CTA times are Chicago local, e.g. '20261006 08:15' (sometimes with seconds)."""
    fmt = "%Y%m%d %H:%M:%S" if s.count(":") == 2 else "%Y%m%d %H:%M"
    return int(datetime.strptime(s, fmt).replace(tzinfo=CHICAGO).timestamp() * 1000)


def fetch_buses():
    stops = CONFIG["stops"]
    if not CTA_KEY:
        return mock_buses(stops)

    # One request covers up to 10 stops, which keeps us well under the daily quota.
    resp = cta("getpredictions", stpid=",".join(s["id"] for s in stops[:10]), top=20)
    arrivals = {s["id"]: [] for s in stops}
    notes = {}
    for err in resp.get("error", []):
        if "stpid" in err:
            notes[err["stpid"]] = err["msg"]  # e.g. "No service scheduled"
        else:
            raise RuntimeError(err["msg"])  # e.g. invalid key: whole request failed
    for p in resp.get("prd", []):
        arrivals.setdefault(p["stpid"], []).append({
            "route": p["rt"],
            "direction": p["rtdir"],
            "destination": p["des"],
            "arrival_ms": cta_time_to_ms(p["prdtm"]),
            "delayed": bool(p.get("dly")),
        })
    return [stop_view(s, arrivals.get(s["id"], []), notes.get(s["id"])) for s in stops]


def stop_view(stop, arrivals, note):
    wanted = set(stop.get("routes") or [])
    if wanted:
        arrivals = [a for a in arrivals if a["route"] in wanted]
    arrivals.sort(key=lambda a: a["arrival_ms"])
    return {
        "id": stop["id"],
        "name": stop["name"],
        "walk_minutes": stop["walk_minutes"],
        "note": note,
        "arrivals": arrivals,
    }


def mock_buses(stops):
    """Plausible fake arrivals that count down smoothly between refreshes."""
    now = time.time()
    views = []
    for i, stop in enumerate(stops):
        headway = 8 * 60 + i * 150
        first = (now // headway) * headway + i * 170
        route = (stop.get("routes") or ["22"])[0]
        arrivals = []
        for k in range(6):
            slot = first + k * headway
            rnd = random.Random(f"{stop['id']}-{int(slot)}")
            t = slot + rnd.randint(-60, 120)
            if t > now:
                arrivals.append({
                    "route": route,
                    "direction": "Northbound" if i % 2 == 0 else "Southbound",
                    "destination": "Howard" if i % 2 == 0 else "Harrison",
                    "arrival_ms": int(t * 1000),
                    "delayed": rnd.random() < 0.1,
                })
        views.append(stop_view(stop, arrivals[:4], None))
    return views


# ---------------------------------------------------------------- weather

WEATHER_CODES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
    85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}


def fetch_weather():
    home = CONFIG["home"]
    query = urllib.parse.urlencode({
        "latitude": home["lat"],
        "longitude": home["lon"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "minutely_15": "precipitation_probability,precipitation",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,sunset",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/Chicago",
        "forecast_days": 2,
        "forecast_minutely_15": 12,  # next 3 hours
    })
    w = http_json(f"https://api.open-meteo.com/v1/forecast?{query}")
    cur, m15, hourly, daily = w["current"], w["minutely_15"], w["hourly"], w["daily"]

    rain_chance = max(m15["precipitation_probability"], default=0) or 0
    rain_inches = sum(x or 0 for x in m15["precipitation"])
    rain_start = next(
        (t for t, p in zip(m15["time"], m15["precipitation_probability"])
         if (p or 0) >= CONFIG["umbrella_threshold_pct"]),
        None,
    )

    now_hour = datetime.now(CHICAGO).strftime("%Y-%m-%dT%H:00")
    start = next((i for i, t in enumerate(hourly["time"]) if t >= now_hour), 0)
    next_hours = [
        {
            "time": hourly["time"][i],
            "temp_f": round(hourly["temperature_2m"][i]),
            "rain_pct": hourly["precipitation_probability"][i] or 0,
            "summary": WEATHER_CODES.get(hourly["weather_code"][i], "—"),
        }
        for i in range(start + 1, min(start + 7, len(hourly["time"])))
    ]

    feels = cur["apparent_temperature"]
    advice = []
    if rain_chance >= CONFIG["umbrella_threshold_pct"]:
        advice.append("Bring an umbrella")
    if feels < CONFIG["jacket_below_f"]:
        advice.append("Heavy coat" if feels < 35 else "Bring a jacket")

    return {
        "temp_f": round(cur["temperature_2m"]),
        "feels_f": round(feels),
        "summary": WEATHER_CODES.get(cur["weather_code"], "—"),
        "wind_mph": round(cur["wind_speed_10m"]),
        "high_f": round(daily["temperature_2m_max"][0]),
        "low_f": round(daily["temperature_2m_min"][0]),
        "sunset": daily["sunset"][0],
        "rain_next_3h_pct": rain_chance,
        "rain_next_3h_in": round(rain_inches, 2),
        "rain_starts": rain_start,
        "next_hours": next_hours,
        "advice": advice,
    }


# ---------------------------------------------------------------- server

buses = Cached(fetch_buses, CONFIG["bus_refresh_seconds"])
weather = Cached(fetch_weather, CONFIG["weather_refresh_seconds"])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/status":
            body = json.dumps({
                "now_ms": int(time.time() * 1000),  # lets the display correct its own clock
                "mock": not CTA_KEY,
                "refresh_seconds": CONFIG["bus_refresh_seconds"],
                "buses": buses.get(),
                "weather": weather.get(),
            }).encode()
            self.send(200, "application/json", body)
        elif path in ("/", "/index.html"):
            self.send(200, "text/html; charset=utf-8", (ROOT / "index.html").read_bytes())
        else:
            self.send(404, "text/plain", b"not found")

    def send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep the console quiet; errors surface in /api/status


if __name__ == "__main__":
    port = int(os.environ.get("PORT", CONFIG["port"]))
    mode = "live CTA data" if CTA_KEY else "MOCK bus data (set CTA_API_KEY for live)"
    print(f"Dashboard on http://localhost:{port}  ·  {mode}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
