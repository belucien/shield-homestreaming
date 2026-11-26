#!/usr/bin/env python3
"""
Shield Carousel - wallpaper generator for Projectivy Launcher (Overflight plugin).

Pulls just-aired episodes, upcoming series, upcoming movies and new
movies from TMDB, current weather from
Open-Meteo, and renders each title as a 4K wallpaper with logo, year, rating,
runtime, genres, overview, "Watch on Stremio" / premiere date, and the
current weather.
Writes everything plus an overflight.json feed into the output folder.

Usage:
    TMDB_API_KEY=xxxx python generate.py --out site
    python generate.py --out site --demo      # offline test with sample data
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
BASE_W, BASE_H = 1920, 1080  # layout is designed at 1080p and scaled

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"

# --------------------------------------------------------------------------
# Networking
# --------------------------------------------------------------------------

_session = None


def http():
    global _session
    if _session is None:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        s = requests.Session()
        retry = Retry(total=4, backoff_factor=1.5,
                      status_forcelist=(429, 500, 502, 503, 504))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers["User-Agent"] = "shield-carousel/1.0"
        _session = s
    return _session


class TMDB:
    def __init__(self, key, language, region):
        self.key = key.strip()
        self.language = language
        self.region = region
        # v4 "API Read Access Token" is a long JWT; v3 "API Key" is 32 hex chars
        self.bearer = self.key.startswith("eyJ") or len(self.key) > 40
        self.languages = []

    def get(self, path, **params):
        params.setdefault("language", self.language)
        headers = {"accept": "application/json"}
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        r = http().get(f"{TMDB_API}{path}", params=params, headers=headers, timeout=20)
        r.raise_for_status()
        return r.json()

    # ---- lists -----------------------------------------------------------
    NOT_SHOWS = "10763|10764|10766|10767"  # news, reality, soap, talk

    def _discover(self, kind, **p):
        p.setdefault("include_adult", "false")
        p.setdefault("sort_by", "popularity.desc")
        if self.languages:
            p.setdefault("with_original_language", "|".join(self.languages))
        return self.get(f"/discover/{kind}", **p)["results"]

    def new_tv(self):
        """Brand-new series that premiered in the last 30 days."""
        t = dt.date.today()
        return self._discover("tv", without_genres=self.NOT_SHOWS, **{
            "first_air_date.gte": str(t - dt.timedelta(days=30)),
            "first_air_date.lte": str(t)})

    def upcoming_tv(self):
        """Brand-new series premiering in the next 60 days."""
        t = dt.date.today()
        return self._discover("tv", without_genres=self.NOT_SHOWS, **{
            "first_air_date.gte": str(t + dt.timedelta(days=1)),
            "first_air_date.lte": str(t + dt.timedelta(days=60))})

    def upcoming_movies(self):
        """Movies opening in the next 90 days."""
        t = dt.date.today()
        return self._discover("movie", region=self.region, with_release_type="2|3", **{
            "release_date.gte": str(t + dt.timedelta(days=1)),
            "release_date.lte": str(t + dt.timedelta(days=90))})

    def new_movies(self):
        """Movies that came out on digital in the last 60 days (ready to stream)."""
        t = dt.date.today()
        return self._discover("movie", region=self.region, with_release_type="4", **{
            "release_date.gte": str(t - dt.timedelta(days=60)), "release_date.lte": str(t),
            "vote_count.gte": 10})

    def trending_movies(self):
        """TMDB's Trending This Week catalogue (movies)."""
        return self.get("/trending/movie/week")["results"]

    def details(self, kind, tmdb_id):
        return self.get(
            f"/{kind}/{tmdb_id}",
            append_to_response="images",
            include_image_language="en,null",
        )


def download_image(url):
    r = http().get(url, timeout=60)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


# --------------------------------------------------------------------------
# Weather (Open-Meteo, free, no key)
# --------------------------------------------------------------------------

WMO = {
    0: ("Clear", "sun"), 1: ("Mostly Clear", "sun"), 2: ("Partly Cloudy", "partly"),
    3: ("Cloudy", "cloud"), 45: ("Fog", "fog"), 48: ("Fog", "fog"),
    51: ("Drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Drizzle", "rain"),
    56: ("Freezing Drizzle", "rain"), 57: ("Freezing Drizzle", "rain"),
    61: ("Light Rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy Rain", "rain"),
    66: ("Freezing Rain", "rain"), 67: ("Freezing Rain", "rain"),
    71: ("Light Snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy Snow", "snow"),
    77: ("Snow", "snow"), 80: ("Showers", "rain"), 81: ("Showers", "rain"),
    82: ("Heavy Showers", "rain"), 85: ("Snow Showers", "snow"),
    86: ("Snow Showers", "snow"), 95: ("Thunderstorms", "storm"),
    96: ("Thunderstorms", "storm"), 99: ("Thunderstorms", "storm"),
}


def get_weather(cfg):
    w = cfg["weather"]
    params = {
        "latitude": w["latitude"], "longitude": w["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": w.get("units", "fahrenheit"),
        "timezone": w["timezone"], "forecast_days": 7,
    }
    r = http().get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status()
    d = r.json()
    cur, daily = d["current"], d["daily"]
    desc, icon = WMO.get(int(cur["weather_code"]), ("", "cloud"))
    if icon == "sun" and not cur.get("is_day", 1):
        icon = "moon"
    if icon == "partly" and not cur.get("is_day", 1):
        icon = "partly_night"
    return {
        "temp": round(cur["temperature_2m"]),
        "feels": round(cur["apparent_temperature"]),
        "high": round(daily["temperature_2m_max"][0]),
        "low": round(daily["temperature_2m_min"][0]),
        "rain": daily.get("precipitation_probability_max", [None])[0],
        "desc": desc, "icon": icon, "label": w.get("label", ""),
        "days": [
            {"dow": dt.date.fromisoformat(day).strftime("%a").upper(),
             "icon": WMO.get(int(code), ("", "cloud"))[1],
             "hi": round(hi), "lo": round(lo)}
            for day, code, hi, lo in zip(daily["time"], daily["weather_code"],
                                         daily["temperature_2m_max"],
                                         daily["temperature_2m_min"])
        ],
    }


# --------------------------------------------------------------------------
# Building the list of titles
# --------------------------------------------------------------------------

def pick_titles(tmdb, cfg):
    mix = cfg["mix"]
    buckets = []
    # (config key, kind, badge, fetch, allowed days from today: (min, max) or None)
    sources = [
        ("new_tv", "tv", "NEW SERIES", tmdb.new_tv, (-30, 0)),
        ("new_movies", "movie", "NEW MOVIE", tmdb.new_movies, (-365, 0)),
        ("upcoming_tv", "tv", "UPCOMING SERIES", tmdb.upcoming_tv, (1, 120)),
        ("upcoming_movies", "movie", "COMING SOON", tmdb.upcoming_movies, (1, 180)),
        ("trending_movies", "movie", "TRENDING", tmdb.trending_movies, (-365, 180)),
    ]
    for key, kind, badge, fn, window in sources:
        n = int(mix.get(key, 0))
        if n <= 0:
            continue
        try:
            results = fn()
        except Exception as e:  # keep going if one list fails
            print(f"! list {key} failed: {e}", file=sys.stderr)
            results = []
        today = dt.date.today()

        def ok_date(r, window=window):
            # judge by the title's ORIGINAL release date, so re-releases and
            # old shows never show up as "new" or "coming soon"
            try:
                d = dt.date.fromisoformat(r.get("release_date") or r.get("first_air_date") or "")
            except ValueError:
                return False
            return window[0] <= (d - today).days <= window[1]

        items = [(kind, r, badge) for r in results if r.get("backdrop_path")
                 and r.get("overview") and not r.get("adult") and ok_date(r)]
        buckets.append((n, items))

    # interleave buckets so movies / shows alternate, skipping duplicates
    seen, chosen = set(), []
    taken = [0] * len(buckets)
    idx = [0] * len(buckets)
    progress = True
    while progress:
        progress = False
        for b, (n, items) in enumerate(buckets):
            while taken[b] < n and idx[b] < len(items):
                kind, r, badge = items[idx[b]]
                idx[b] += 1
                k = (kind, r["id"])
                if k in seen:
                    continue
                seen.add(k)
                chosen.append((kind, r["id"], badge))
                taken[b] += 1
                progress = True
                break
    return chosen


def best_logo(images):
    logos = [l for l in images.get("logos", []) if l.get("iso_639_1") in ("en", None)
             and l["file_path"].lower().endswith(".png")]
    logos.sort(key=lambda l: (l.get("iso_639_1") == "en", l.get("vote_average", 0)), reverse=True)
    return logos[0]["file_path"] if logos else None


def best_backdrop(images, fallback):
    # prefer textless backdrops (no language) at 4K/high resolution
    bds = [b for b in images.get("backdrops", []) if b.get("iso_639_1") is None
           and b.get("width", 0) >= 1920]
    bds.sort(key=lambda b: (b.get("vote_average", 0), b.get("width", 0)), reverse=True)
    return bds[0]["file_path"] if bds else fallback


def build_item(tmdb, cfg, kind, tmdb_id, badge):
    d = tmdb.details(kind, tmdb_id)
    title = d.get("title") or d.get("name")
    date = d.get("release_date") or d.get("first_air_date") or ""
    year = date[:4]
    genres = [g["name"].replace("Action & Adventure", "Action")
              .replace("Sci-Fi & Fantasy", "Sci-Fi") for g in d.get("genres", [])][:2]
    if kind == "movie":
        rt = d.get("runtime") or 0
        length = f"{rt // 60}h {rt % 60:02d}min" if rt >= 60 else (f"{rt}min" if rt else "")
    else:
        s = d.get("number_of_seasons") or 0
        length = f"{s} Season{'s' if s != 1 else ''}" if s else ""
    rating = d.get("vote_average") or 0
    votes = d.get("vote_count") or 0
    rating_str = f"{rating:.1f}" if votes >= cfg.get("min_votes_for_rating", 20) and rating else ""

    # call-to-action line under the description
    watch = cfg.get("watch_label", "Stremio")
    cta, cta_icon = f"Watch on {watch}", "play"
    future = date > str(dt.date.today())
    if badge == "NEW SERIES":
        cta = f"Premiered {nice_date(date)}  ·  Watch on {watch}"
    elif badge == "UPCOMING SERIES" or (kind == "tv" and future):
        cta, cta_icon = f"Premieres {nice_date(date)}", "calendar"
    elif future:  # coming soon / trending but not out yet
        cta, cta_icon = f"In theaters {nice_date(date)}", "calendar"

    images = d.get("images", {})
    return {
        "kind": kind, "id": tmdb_id, "badge": badge, "title": title, "year": year,
        "rating": rating_str, "length": length, "genres": genres,
        "overview": d.get("overview", ""), "cta": cta, "cta_icon": cta_icon,
        "backdrop": f"{TMDB_IMG}/original{best_backdrop(images, d.get('backdrop_path'))}",
        "logo": (f"{TMDB_IMG}/w780{best_logo(images)}" if best_logo(images) else None),
    }


def nice_date(iso):
    try:
        return dt.date.fromisoformat(iso).strftime("%a %m/%d")
    except Exception:
        return iso


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.s = w / BASE_W
        self._fonts = {}

    def px(self, v):
        return int(round(v * self.s))

    def font(self, name, size):
        key = (name, size)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(str(FONTS / name), self.px(size))
        return self._fonts[key]


def cover(img, w, h, focus_x=0.65, focus_y=0.35):
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    nw, nh = int(img.width * scale + 0.5), int(img.height * scale + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = int((nw - w) * focus_x)
    y = int((nh - h) * focus_y)
    return img.crop((x, y, x + w, y + h))


def gradient_mask(w, h, stops, horizontal=True):
    """stops: list of (position 0..1, alpha 0..255) -> L mask"""
    n = w if horizontal else h
    line = Image.new("L", (n, 1))
    px = line.load()
    for i in range(n):
        t = i / max(1, n - 1)
        for (p0, a0), (p1, a1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                u = (t - p0) / max(1e-6, p1 - p0)
                u = u * u * (3 - 2 * u)  # smoothstep
                px[i, 0] = int(a0 + (a1 - a0) * u)
                break
        else:
            px[i, 0] = stops[-1][1] if t > stops[-1][0] else stops[0][1]
    if horizontal:
        return line.resize((w, h))
    return line.transpose(Image.ROTATE_270).transpose(Image.FLIP_LEFT_RIGHT).resize((w, h))


def apply_scrims(img):
    w, h = img.size
    black = Image.new("RGB", (w, h), (8, 8, 10))
    # left: readable text panel
    img = Image.composite(black, img, gradient_mask(
        w, h, [(0, 238), (0.30, 200), (0.55, 70), (0.72, 0), (1, 0)]))
    # bottom: dock for Projectivy app row
    img = Image.composite(black, img, gradient_mask(
        w, h, [(0, 0), (0.55, 0), (0.80, 170), (1, 245)], horizontal=False))
    # top: light shade so the clock & weather stay legible
    img = Image.composite(black, img, gradient_mask(
        w, h, [(0, 120), (0.22, 0), (1, 0)], horizontal=False))
    return img


def wrap(draw, text, font, max_w, max_lines):
    words = text.split()
    lines, cur = [], ""
    for wd in words:
        trial = f"{cur} {wd}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = wd
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    used = " ".join(lines).split()
    if len(used) < len(words):  # truncated -> ellipsis
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last.rstrip(",.;:—- ") + "…"
    return lines


def draw_tracked(draw, xy, text, font, fill, tracking):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def tracked_width(draw, text, font, tracking):
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


# ---- weather icons, drawn as vectors so they're crisp at any size ---------

def draw_weather_icon(layer, cx, cy, r, kind):
    d = ImageDraw.Draw(layer)
    white = (255, 255, 255, 255)
    sun = (255, 205, 90, 255)
    lw = max(2, int(r * 0.12))

    def sun_at(x, y, rr):
        import math
        d.ellipse((x - rr * .45, y - rr * .45, x + rr * .45, y + rr * .45), fill=sun)
        for k in range(8):
            a = k * math.pi / 4
            d.line((x + math.cos(a) * rr * .65, y + math.sin(a) * rr * .65,
                    x + math.cos(a) * rr * .92, y + math.sin(a) * rr * .92), fill=sun, width=lw)

    def moon_at(x, y, rr):
        d.ellipse((x - rr * .6, y - rr * .6, x + rr * .6, y + rr * .6), fill=(235, 235, 245, 255))
        d.ellipse((x - rr * .25, y - rr * .85, x + rr * .95, y + rr * .35), fill=(0, 0, 0, 0))

    def cloud_at(x, y, rr, col=white):
        d.ellipse((x - rr * .85, y - rr * .05, x - rr * .15, y + rr * .6), fill=col)
        d.ellipse((x - rr * .45, y - rr * .5, x + rr * .35, y + rr * .3), fill=col)
        d.ellipse((x + rr * .05, y - rr * .2, x + rr * .85, y + rr * .6), fill=col)
        d.rounded_rectangle((x - rr * .55, y + rr * .15, x + rr * .55, y + rr * .6),
                            radius=rr * .2, fill=col)

    if kind == "sun":
        sun_at(cx, cy, r)
    elif kind == "moon":
        moon_at(cx, cy, r)
    elif kind in ("partly", "partly_night"):
        (sun_at if kind == "partly" else moon_at)(cx - r * .3, cy - r * .3, r * .75)
        cloud_at(cx + r * .1, cy + r * .1, r * .8)
    elif kind == "cloud":
        cloud_at(cx, cy - r * .05, r)
    elif kind == "fog":
        for k in range(3):
            yy = cy - r * .4 + k * r * .4
            d.rounded_rectangle((cx - r * .85, yy, cx + r * .85, yy + lw * 1.4),
                                radius=lw, fill=white)
    else:  # rain / snow / storm
        cloud_at(cx, cy - r * .3, r * .9)
        for k in range(3):
            x = cx - r * .45 + k * r * .45
            if kind == "rain":
                d.line((x, cy + r * .45, x - r * .12, cy + r * .8),
                       fill=(140, 190, 255, 255), width=lw)
            elif kind == "snow":
                d.ellipse((x - lw, cy + r * .55, x + lw, cy + r * .55 + lw * 2), fill=white)
            elif k == 1:
                d.polygon([(x + r * .1, cy + r * .35), (x - r * .2, cy + r * .7),
                           (x, cy + r * .7), (x - r * .1, cy + r * .98),
                           (x + r * .25, cy + r * .58), (x + r * .02, cy + r * .58)],
                          fill=sun)


def render_weather(img, c, wx, now):
    """Weather block, top-left. Projectivy's own clock sits top-right."""
    if not wx:
        return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0 = c.px(96), c.px(60)
    r = c.px(30)
    draw_weather_icon(layer, x0 + r, y0 + r + c.px(4), r, wx["icon"])
    tx = x0 + r * 2 + c.px(18)
    f_temp = c.font("InterDisplay-Light.otf", 56)
    d.text((tx, y0 - c.px(6)), f"{wx['temp']}°", font=f_temp, fill=(255, 255, 255, 255))
    tx2 = tx + d.textlength(f"{wx['temp']}°", font=f_temp) + c.px(18)
    f1 = c.font("Inter-SemiBold.otf", 21)
    f2 = c.font("Inter-Regular.otf", 18)
    d.text((tx2, y0 + c.px(6)), wx["desc"], font=f1, fill=(255, 255, 255, 240))
    sub = f"H {wx['high']}°  L {wx['low']}°"
    if wx.get("rain") not in (None, 0) and wx["rain"] >= 20:
        sub += f"  ·  {wx['rain']}% rain"
    d.text((tx2, y0 + c.px(34)), sub, font=f2, fill=(255, 255, 255, 190))
    f3 = c.font("Inter-Medium.otf", 15)
    stamp = wx['label'].upper()
    draw_tracked(d, (x0 + c.px(2), y0 + c.px(76)), stamp, f3, (255, 255, 255, 120), c.px(1.5))

    # 7-day forecast strip
    days = wx.get("days") or []
    if days:
        col = c.px(66)
        fy = y0 + c.px(112)
        f_dow = c.font("Inter-SemiBold.otf", 13)
        f_hi = c.font("Inter-SemiBold.otf", 16)
        f_lo = c.font("Inter-Regular.otf", 16)
        for i, day in enumerate(days[:7]):
            cx = x0 + i * col + col // 2
            label = "TODAY" if i == 0 else day["dow"]
            alpha = 235 if i == 0 else 170
            lw = tracked_width(d, label, f_dow, c.px(1))
            draw_tracked(d, (cx - lw / 2, fy), label, f_dow, (255, 255, 255, alpha), c.px(1))
            draw_weather_icon(layer, cx, fy + c.px(40), c.px(15), day["icon"])
            hi, lo = f"{day['hi']}°", f"{day['lo']}°"
            d.text((cx - d.textlength(hi, font=f_hi) / 2, fy + c.px(62)), hi, font=f_hi,
                   fill=(255, 255, 255, 235))
            d.text((cx - d.textlength(lo, font=f_lo) / 2, fy + c.px(82)), lo, font=f_lo,
                   fill=(255, 255, 255, 140))
        # thin divider between today and the week
        d.line((x0 + col, fy + c.px(2), x0 + col, fy + c.px(100)), fill=(255, 255, 255, 50),
               width=max(1, c.px(1)))
    img.paste(layer, (0, 0), layer)


def logo_fit(logo, max_w, max_h):
    logo = logo.convert("RGBA")
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    scale = min(max_w / logo.width, max_h / logo.height)
    logo = logo.resize((max(1, int(logo.width * scale)), max(1, int(logo.height * scale))),
                       Image.LANCZOS)
    # dark logos disappear on a dark scrim: recolor them white
    a = logo.getchannel("A")
    lum = ImageOps.grayscale(logo.convert("RGB"))
    opaque = a.point(lambda v: 255 if v > 128 else 0)
    vals = [l for l, m in zip(lum.getdata(), opaque.getdata()) if m]
    if vals and sum(vals) / len(vals) < 70:
        white = Image.new("RGBA", logo.size, (255, 255, 255, 255))
        white.putalpha(a)
        logo = white
    return logo


def render_wallpaper(item, backdrop, logo, wx, cfg, now):
    W, H = cfg["output_width"], cfg["output_height"]
    c = Canvas(W, H)
    img = cover(backdrop, W, H)
    img = apply_scrims(img)
    d = ImageDraw.Draw(img, "RGBA")

    render_weather(img, c, wx, now)
    d = ImageDraw.Draw(img, "RGBA")

    x = c.px(96)
    # badge
    f_badge = c.font("Inter-SemiBold.otf", 15)
    track = c.px(2.4)
    bw = tracked_width(d, item["badge"], f_badge, track)
    by = c.px(296)
    pad_x, pad_y = c.px(14), c.px(8)
    d.rounded_rectangle((x, by, x + bw + pad_x * 2, by + c.px(17) + pad_y * 2),
                        radius=c.px(6), fill=(255, 255, 255, 38),
                        outline=(255, 255, 255, 70), width=max(1, c.px(1)))
    draw_tracked(d, (x + pad_x, by + pad_y - c.px(1)), item["badge"], f_badge,
                 (255, 255, 255, 235), track)

    # logo or title text
    top = c.px(346)
    max_w, max_h = c.px(560), c.px(150)
    if logo is not None:
        lg = logo_fit(logo, max_w, max_h)
        # soft shadow under the logo
        sh = Image.new("RGBA", lg.size, (0, 0, 0, 0))
        sh.putalpha(lg.getchannel("A").point(lambda v: int(v * .55)))
        sh = sh.filter(ImageFilter.GaussianBlur(c.px(10)))
        img.paste(sh, (x + c.px(3), top + c.px(5)), sh)
        img.paste(lg, (x, top), lg)
        bottom = top + lg.height
    else:
        f_t = c.font("InterDisplay-Bold.otf", 88)
        lines = wrap(d, item["title"], f_t, max_w, 2)
        if len(lines) == 2:
            f_t = c.font("InterDisplay-Bold.otf", 72)
            lines = wrap(d, item["title"], f_t, max_w, 2)
        lh = int(f_t.size * 1.05)
        for i, ln in enumerate(lines):
            d.text((x, top + i * lh), ln, font=f_t, fill=(255, 255, 255, 255))
        bottom = top + lh * len(lines)
    d = ImageDraw.Draw(img, "RGBA")

    # meta line: 2026 · [TMDB 8.5] · 2h 14min · Action, Drama
    y = bottom + c.px(30)
    f_meta = c.font("Inter-Medium.otf", 22)
    f_meta_b = c.font("Inter-Bold.otf", 22)
    gray = (255, 255, 255, 215)
    cx = x
    parts = []
    if item["year"]:
        parts.append(("text", item["year"]))
    if item["rating"]:
        parts.append(("rating", item["rating"]))
    if item["length"]:
        parts.append(("text", item["length"]))
    if item["genres"]:
        parts.append(("text", ", ".join(item["genres"])))
    for i, (kind, val) in enumerate(parts):
        if i:
            d.text((cx + c.px(12), y), "·", font=f_meta, fill=(255, 255, 255, 140))
            cx += c.px(12) * 2 + d.textlength("·", font=f_meta)
        if kind == "rating":
            f_lab = c.font("Inter-Bold.otf", 12)
            lw_ = d.textlength("TMDB", font=f_lab) + c.px(12)
            d.rounded_rectangle((cx, y + c.px(4), cx + lw_, y + c.px(25)), radius=c.px(4),
                                fill=(1, 180, 228, 255))
            d.text((cx + c.px(6), y + c.px(7)), "TMDB", font=f_lab, fill=(13, 37, 63, 255))
            cx += lw_ + c.px(8)
            d.text((cx, y), val, font=f_meta_b, fill=(255, 255, 255, 255))
            cx += d.textlength(val, font=f_meta_b)
        else:
            d.text((cx, y), val, font=f_meta, fill=gray)
            cx += d.textlength(val, font=f_meta)

    # overview
    y += c.px(52)
    f_ov = c.font("Inter-Regular.otf", 23)
    lines = wrap(d, item["overview"], f_ov, c.px(780), 3)
    lh = c.px(35)
    for i, ln in enumerate(lines):
        d.text((x, y + i * lh), ln, font=f_ov, fill=(255, 255, 255, 200))
    y += lh * len(lines)

    # call to action: "Watch on Stremio" / "Premieres Fri 12/05"
    if item.get("cta"):
        y += c.px(20)
        f_p = c.font("Inter-SemiBold.otf", 20)
        ic = c.px(18)
        iy = y + c.px(5)
        if item.get("cta_icon") == "calendar":
            d.rounded_rectangle((x, iy, x + ic, iy + ic), radius=c.px(3),
                                outline=(255, 255, 255, 235), width=max(2, c.px(2)))
            d.rectangle((x, iy, x + ic, iy + c.px(5)), fill=(255, 255, 255, 235))
        else:
            tri = c.px(11)
            d.polygon([(x, iy + c.px(1)), (x, iy + c.px(1) + tri * 1.6),
                       (x + tri * 1.35, iy + c.px(1) + tri * .8)], fill=(255, 255, 255, 235))
        d.text((x + ic + c.px(12), y + c.px(1)), item["cta"], font=f_p, fill=(255, 255, 255, 235))

    # small attribution in the corner (TMDB terms)
    f_att = c.font("Inter-Regular.otf", 11)
    d.text((W - c.px(96) - d.textlength("Data: TMDB", font=f_att), H - c.px(26)),
           "Data: TMDB", font=f_att, fill=(255, 255, 255, 70))
    return img


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "title"


# --------------------------------------------------------------------------
# Demo data (offline test)
# --------------------------------------------------------------------------

def demo_items():
    base = {
        "kind": "movie", "id": 346, "badge": "TRENDING MOVIE", "title": "Seven Samurai",
        "year": "1954", "rating": "8.5", "length": "3h 27min", "genres": ["Action", "Drama"],
        "overview": ("A samurai answers a village's request for protection after he falls on hard "
                     "times. The town needs protection from bandits, so the samurai gathers six "
                     "others to help him teach the people how to defend themselves, and the "
                     "villagers provide the soldiers with food."),
        "cta": "Watch on Stremio", "cta_icon": "play", "backdrop": str(ROOT / "demo" / "sample.png"), "logo": None,
    }
    tv = dict(base, kind="tv", id=1, title="The Long Valley",
              year="2026", rating="8.1", length="2 Seasons", genres=["Drama", "Mystery"],
              overview="A demo entry showing how a new series looks before it premieres.",
              badge="NEW SERIES", cta="Premieres Fri 12/05", cta_icon="calendar")
    return [base, tv]


def demo_backdrop(path):
    img = Image.open(path).convert("RGB")
    # the sample is a screenshot with text on the left; keep the photo on the right
    w, h = img.size
    img = img.crop((int(w * .47), int(h * .16), int(w * .905), int(h * .86)))
    canvas = Image.new("RGB", (int(img.height * 16 / 9), img.height), (20, 20, 22))
    canvas.paste(img, (canvas.width - img.width, 0))
    return canvas


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def write_index(out, entries, generated):
    cards = "\n".join(
        f'<figure><img loading="lazy" src="{e["file"]}"><figcaption>{e["title"]}</figcaption></figure>'
        for e in entries)
    (out / "index.html").write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Shield Carousel</title>
<style>body{{margin:0;background:#0b0b0d;color:#ddd;font:15px system-ui,sans-serif;padding:24px}}
h1{{font-weight:600;font-size:20px}}p{{color:#888}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:18px}}
img{{width:100%;border-radius:10px;display:block}}figure{{margin:0}}figcaption{{padding:6px 2px;color:#aaa}}
code{{background:#1b1b1f;padding:2px 6px;border-radius:4px}}</style></head><body>
<h1>Shield Carousel</h1><p>Updated {generated}. Overflight feed: <code>overflight.json</code></p>
<main>{cards}</main></body></html>""", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--demo", action="store_true", help="offline test with sample data")
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL", ""),
                    help="public URL where the output folder is served")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    out = Path(args.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    tz = ZoneInfo(cfg["weather"]["timezone"])
    now = dt.datetime.now(tz)
    version = now.strftime("%Y%m%d%H%M")

    if args.demo:
        wx = {"temp": 68, "feels": 67, "high": 72, "low": 48, "rain": 0, "desc": "Sunny",
              "icon": "sun", "label": cfg["weather"]["label"],
              "days": [{"dow": d, "icon": i, "hi": h, "lo": l} for d, i, h, l in [
                  ("WED", "sun", 72, 48), ("THU", "partly", 70, 47), ("FRI", "cloud", 66, 46),
                  ("SAT", "rain", 61, 45), ("SUN", "partly", 64, 44), ("MON", "sun", 69, 46),
                  ("TUE", "sun", 73, 49)]]}
        items = demo_items()
    else:
        key = os.environ.get("TMDB_API_KEY", "")
        if not key:
            sys.exit("TMDB_API_KEY is not set")
        tmdb = TMDB(key, cfg["language"], cfg["region"])
        tmdb.languages = cfg.get("original_languages", [])
        try:
            wx = get_weather(cfg)
        except Exception as e:
            print(f"! weather failed: {e}", file=sys.stderr)
            wx = None
        items = []
        for kind, tid, badge in pick_titles(tmdb, cfg):
            try:
                items.append(build_item(tmdb, cfg, kind, tid, badge))
            except Exception as e:
                print(f"! details {kind}/{tid} failed: {e}", file=sys.stderr)

    entries, feed = [], []
    base_url = args.base_url.rstrip("/")
    for i, it in enumerate(items):
        try:
            if args.demo:
                bd = demo_backdrop(it["backdrop"])
                lg = None
            else:
                bd = download_image(it["backdrop"])
                lg = download_image(it["logo"]) if it["logo"] else None
            img = render_wallpaper(it, bd, lg, wx, cfg, now)
        except Exception as e:
            print(f"! render {it.get('title')} failed: {e}", file=sys.stderr)
            continue
        name = f"{i:02d}-{it['kind']}-{slug(it['title'])}.jpg"
        img.save(out / "img" / name, "JPEG", quality=cfg["jpeg_quality"],
                 optimize=True, progressive=True, subsampling=0)
        url = f"{base_url}/img/{name}?v={version}" if base_url else f"img/{name}?v={version}"
        entries.append({"title": it["title"], "file": f"img/{name}?v={version}"})
        feed.append({
            "location": "Shield Carousel",
            "title": it["title"],
            "author": "TMDB",
            # Overflight needs at least one url_* field; images are accepted in each
            "url_img": url, "url_1080p": url, "url_1080p_hdr": url,
            "url_4k": url, "url_4k_hdr": url,
        })
        print(f"✓ {it['badge']:<17} {it['title']}")

    if not feed:
        sys.exit("No wallpapers were generated")
    (out / "overflight.json").write_text(json.dumps(feed, indent=2), encoding="utf-8")
    write_index(out, entries, now.strftime("%a %m/%d %-I:%M %p %Z"))
    print(f"Wrote {len(feed)} wallpapers to {out}/")


if __name__ == "__main__":
    main()
