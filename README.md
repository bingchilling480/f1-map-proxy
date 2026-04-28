# f1-map-proxy

Fetches the next F1 race circuit SVG from `julesr0y/f1-circuits-svg`, rasterizes it to a cropped PNG via cairosvg, and serves it over HTTP so Glance's image widget can display it.

---

## Why it exists

Glance widgets render `<img>` tags — they cannot display inline SVG. Pointing a Glance widget directly at an SVG URL produces a broken image.

This proxy sits between Glance and the SVG source. On each request it:
- Hits the Jolpica API for the next race's circuit ID
- Looks up the correct SVG layout from a local circuit database
- Fetches the SVG from GitHub, patches stroke width for thinner lines
- Rasterizes it to PNG via cairosvg
- Autocrop transparent padding with Pillow
- Returns `image/png`

Glance gets a valid raster image. The result is cached in-process for 1 hour.

---

## Stack

| Component | Role |
|---|---|
| FastAPI + uvicorn | HTTP server |
| cairosvg | SVG → PNG rasterization |
| Pillow | Autocrop transparent padding |
| requests | Fetch SVGs and circuit DB from GitHub, next race from Jolpica |
| libcairo2 / pango / gdk-pixbuf | Native libs required by cairosvg |
| Docker (python:3.12-slim) | Runtime |

---

## How the circuit lookup works

On startup, `circuits.json` is fetched from `julesr0y/f1-circuits-svg` and loaded into memory. This file contains all 78 historical F1 circuits with their layout IDs and the seasons each layout was active.

When a request comes in:
1. Jolpica returns the next race's `circuitId` (e.g. `"miami"`)
2. A hardcoded mapping resolves any IDs that differ between Jolpica and the repo (e.g. `"albert_park"` → `"melbourne"`)
3. The circuit DB is queried for the layout active in the current year
4. The SVG is fetched from `circuits/minimal/white/{layoutId}.svg`

This means the proxy self-adapts as new circuits are added to the calendar — no manual updates needed unless a new circuit's Jolpica ID doesn't match the repo ID.

---

## Deploy

### Compose (recommended)

```yaml
services:
  f1-map-proxy:
    build: ./f1-map-proxy
    container_name: f1-map-proxy
    restart: unless-stopped
    ports:
      - "4464:8080"
```

```bash
docker compose up -d
```

### docker run

```bash
docker build -t f1-map-proxy .
docker run -d \
  --name f1-map-proxy \
  -p 4464:8080 \
  --restart unless-stopped \
  f1-map-proxy
```

---

## Endpoints

```
GET  /next_map.png   → image/png, autocropped, transparent background
HEAD /next_map.png   → same, no body
GET  /health         → JSON with cache state, loaded circuit ID, circuit DB size
```

---

## Example Glance widget config

With race metadata from Jolpica:

```yaml
- type: custom-api
  title: Next Race
  cache: 1h
  url: http://192.168.1.14:4463/f1/next/
  template: |
    <div style="text-align:center">
      <p>{{ .JSON.String "race_name" }}</p>
      <img src="http://192.168.1.14:4464/next_map.png"
           style="width:100%;max-width:400px" />
    </div>
```

Bare image only:

```yaml
- type: custom-api
  title: Track Map
  cache: 1h
  url: http://192.168.1.14:4464/next_map.png
  template: |
    <img src="http://192.168.1.14:4464/next_map.png" style="width:100%" />
```

---

## Dependencies & limitations

- **Requires internet access at runtime** — fetches `circuits.json` and SVG files from `raw.githubusercontent.com`. No offline fallback on first request after a restart.
- **SVG source**: `julesr0y/f1-circuits-svg` — if this repo changes its directory structure or becomes unavailable, the proxy breaks. Pin to a commit SHA in `SVG_BASE` and `CIRCUITS_JSON` if stability matters.
- **Jolpica** (`api.jolpi.ca`) — used for next race lookup. Returns an empty races list at the end of the season; the proxy will error and return a blank PNG until the next season's schedule is published.
- **Circuit ID mapping** — 10 Jolpica `circuitId` values don't match the repo's IDs and are hardcoded in `JOLPICA_TO_REPO`. If a new circuit joins the calendar with a mismatched ID, add it to the dict manually.
- **Cache is in-process only** — no persistence across container restarts. The first request after a restart always hits upstream.
- **Stroke width patch** — replaces `stroke-width:20` with `stroke-width:4` via bytes substitution before rendering. If the repo changes its SVG style format, this silently stops working and lines revert to thick.
- **SVG style** — currently `circuits/minimal/white`. To change style, update `SVG_BASE` in `main.py` to one of: `circuits/minimal/black`, `circuits/minimal/white-outline`, `circuits/minimal/black-outline`, or the `detailed/` equivalents.
