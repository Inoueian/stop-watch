#!/usr/bin/env python3
"""Find CTA stop IDs near home (from config.json) for a route.

    CTA_API_KEY=yourkey python3 stops.py 22        # nearest route-22 stops, each direction
    CTA_API_KEY=yourkey python3 stops.py 22 36 151 # several routes

Prints stop IDs plus a rough walk time you can paste into config.json.
"""
import math
import sys

from server import CONFIG, CTA_KEY, cta


def meters_between(lat1, lon1, lat2, lon2):
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main(routes):
    if not CTA_KEY:
        sys.exit("Set CTA_API_KEY first (see README).")
    home = CONFIG["home"]
    for rt in routes:
        resp = cta("getdirections", rt=rt)
        if "error" in resp:
            print(f"Route {rt}: {resp['error'][0]['msg']}")
            continue
        for d in resp["directions"]:
            direction = d.get("dir") or d.get("id")
            stops = cta("getstops", rt=rt, dir=direction).get("stops", [])
            for s in stops:
                s["m"] = meters_between(home["lat"], home["lon"], float(s["lat"]), float(s["lon"]))
            print(f"\nRoute {rt} · {direction}")
            for s in sorted(stops, key=lambda s: s["m"])[:4]:
                # ~80 m/min walking, x1.3 because streets aren't straight lines
                walk = max(1, round(s["m"] * 1.3 / 80))
                print(f"  {s['stpid']:>6}  {s['stpnm']:<40} {s['m']:>5.0f} m  ~{walk} min walk")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
