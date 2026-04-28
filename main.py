import io
import time
import datetime
import requests
from fastapi import FastAPI, Response
from cairosvg import svg2png
from PIL import Image

JOLPICA_URL = "https://api.jolpi.ca/ergast/f1/current/next.json"
CIRCUITS_JSON = "https://raw.githubusercontent.com/julesr0y/f1-circuits-svg/main/circuits.json"
SVG_BASE = "https://raw.githubusercontent.com/julesr0y/f1-circuits-svg/main/circuits/minimal/white"
CACHE_TTL = 3600

JOLPICA_TO_REPO = {
    "albert_park":   "melbourne",
    "villeneuve":    "montreal",
    "barcelona":     "catalunya",
    "red_bull_ring": "spielberg",
    "spa":           "spa-francorchamps",
    "marina_bay":    "marina-bay",
    "americas":      "austin",
    "rodriguez":     "mexico-city",
    "vegas":         "las-vegas",
    "yas_marina":    "yas-marina",
}

app = FastAPI()

_circuit_db: dict = {}
_circuit_db_loaded = False
_cached_png: bytes | None = None
_cached_at: float = 0
_cached_circuit: str = ""


def load_circuit_db():
    global _circuit_db, _circuit_db_loaded
    resp = requests.get(CIRCUITS_JSON, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _circuit_db = {c["id"]: c["layouts"] for c in data}
    _circuit_db_loaded = True
    print(f"Loaded {len(_circuit_db)} circuits from repo")


def get_layout_id(repo_id: str, year: int) -> str:
    layouts = _circuit_db.get(repo_id)
    if not layouts:
        raise ValueError(f"Circuit {repo_id!r} not found in circuits.json")
    for layout in reversed(layouts):
        for part in layout["seasons"].split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-")
                if int(start) <= year <= int(end):
                    return layout["layoutId"]
            else:
                if int(part) == year:
                    return layout["layoutId"]
    return layouts[-1]["layoutId"]


def fetch_next_circuit_id() -> str:
    resp = requests.get(JOLPICA_URL, timeout=10)
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]
    if not races:
        raise ValueError("No upcoming races from Jolpica")
    return races[0]["Circuit"]["circuitId"]


@app.on_event("startup")
def startup():
    try:
        load_circuit_db()
    except Exception as e:
        print(f"WARNING: Failed to load circuit DB at startup: {e}")


@app.api_route("/next_map.png", methods=["GET", "HEAD"])
def get_next_map():
    global _cached_png, _cached_at, _cached_circuit
    now = time.time()
    if _cached_png and (now - _cached_at) < CACHE_TTL:
        return Response(_cached_png, media_type="image/png")
    try:
        if not _circuit_db_loaded:
            load_circuit_db()
        jolpica_id = fetch_next_circuit_id()
        repo_id = JOLPICA_TO_REPO.get(jolpica_id, jolpica_id)
        year = datetime.date.today().year
        layout_id = get_layout_id(repo_id, year)
        url = f"{SVG_BASE}/{layout_id}.svg"
        print(f"Fetching: {url}")
        svg_resp = requests.get(url, timeout=10)
        svg_resp.raise_for_status()
        svg_content = svg_resp.content.replace(b"stroke-width:20", b"stroke-width:4")
        png_bytes = svg2png(bytestring=svg_content, output_width=800, background_color="transparent")
        img = Image.open(io.BytesIO(png_bytes))
        bbox = img.getbbox()
        if bbox:
            pad = 20
            w, h = img.size
            bbox = (max(0, bbox[0]-pad), max(0, bbox[1]-pad), min(w, bbox[2]+pad), min(h, bbox[3]+pad))
            img = img.crop(bbox)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        _cached_png = png_bytes
        _cached_at = now
        _cached_circuit = layout_id
        return Response(png_bytes, media_type="image/png")
    except Exception as e:
        print(f"ERROR generating map: {e}")
        if _cached_png:
            return Response(_cached_png, media_type="image/png")
        return Response(b"", media_type="image/png")


@app.get("/health")
def health():
    return {
        "circuit_db_loaded": _circuit_db_loaded,
        "circuit_db_size": len(_circuit_db),
        "cached_circuit": _cached_circuit,
        "cache_age_seconds": int(time.time() - _cached_at) if _cached_at else None,
    }
