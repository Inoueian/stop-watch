# stop-watch — "Heading Out" wall dashboard prototype

CTA bus "leave by" times for your stops, plus weather. Python 3.9+ standard library only.

```
server.py     backend: polls CTA + Open-Meteo, caches, serves /api/status and the page
index.html    the display (one file; ticks every second, refetches every 30 s)
stops.py      helper: find stop IDs and walk times near home
config.json   your home location, stops, walk times, thresholds
```

## Run

```
python3 server.py                      # mock bus data, real weather
CTA_API_KEY=yourkey python3 server.py  # live bus data
```

Open http://localhost:8080. Other devices on your Wi-Fi can use http://<this-computer's-IP>:8080.

## Set up your stops

1. Get a key: https://www.transitchicago.com/developers/bustracker/ (approval can take a day or so).
2. Put your home coordinates in `config.json` → `home` (right-click your building in Google Maps to copy them).
3. `CTA_API_KEY=yourkey python3 stops.py 22 36` — lists the nearest stops for each route and direction.
4. Copy the IDs into `config.json` → `stops`. `walk_minutes` is a rough estimate, so time your real walk once.
   `routes` (optional) limits a stop to certain routes, e.g. `["22"]`.

The key stays in an environment variable, not in a file, so it can't end up in a git commit by accident.

## How it decides

- **Leave in N min** = predicted arrival − walk time. **Hurry** means you'd need to rush (up to half your walk time late). **Too late** buses are only shown when nothing better is coming.
- **Umbrella** if the chance of rain in the next 3 hours reaches `umbrella_threshold_pct`. **Jacket** if feels-like temperature is below `jacket_below_f`.
- The footer shows how old the data is and any errors, so stale data is never shown as if it were current.

## API budget

One `getpredictions` call covers up to 10 stops. Every 30 s that's about 2,900 calls a day, well below CTA's default limit of 10,000.
