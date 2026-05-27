# TikSave Backend v10 - yt-dlp primary + tikwm fallback
# Deploy on Render:
#   Build command:  pip install -r requirements.txt
#   Start command:  gunicorn app:app
#
# yt-dlp runs directly on your server — no third-party API needed.
# tikwm.com is used as a fast JSON fallback.

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import subprocess
import json
import os
import tempfile
import re

app = Flask(__name__)
CORS(app, origins="*")

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.tiktok.com/",
    "Origin": "https://www.tiktok.com",
}


# ── Source 1: yt-dlp (runs locally on your server, most reliable) ─────────────

def source_ytdlp(url: str) -> dict | None:
    """
    Use yt-dlp to extract video info. No API keys, no third-party scraping.
    yt-dlp handles TikTok natively and is updated regularly.
    Returns our standard result dict.
    """
    try:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist",
            "--no-warnings",
            "--extractor-args", "tiktok:api_hostname=api22-normal-c-alisg.tiktokv.com",
            "--user-agent", BROWSER_UA,
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not result.stdout.strip():
            print(f"[ytdlp] stderr: {result.stderr[:300]}")
            return None

        info = json.loads(result.stdout)

        fmts = []
        seen_urls = set()

        # yt-dlp returns all formats sorted by quality; pick the best ones
        formats = info.get("formats", [])

        # Best video+audio (no watermark) — yt-dlp's default best
        best_url = info.get("url") or info.get("webpage_url")

        # Collect distinct quality tiers from formats list
        hd_url = sd_url = wm_url = audio_url = None

        for f in reversed(formats):  # reversed = highest quality first
            fu = f.get("url", "")
            if not fu or fu in seen_urls:
                continue
            seen_urls.add(fu)

            fid   = f.get("format_id", "")
            note  = (f.get("format_note") or "").lower()
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            height = f.get("height") or 0

            is_video = vcodec != "none"
            is_audio_only = vcodec == "none" and acodec != "none"

            if is_audio_only and not audio_url:
                audio_url = fu
                continue

            if not is_video:
                continue

            # Watermark version
            if "watermark" in note and not wm_url:
                wm_url = fu
                continue

            # HD tier (≥720 p)
            if height >= 720 and not hd_url:
                hd_url = fu
                continue

            # SD tier
            if height > 0 and not sd_url and fu != hd_url:
                sd_url = fu

        # If yt-dlp didn't split into quality tiers, use the single best URL
        if not hd_url and best_url:
            hd_url = best_url

        if hd_url:
            fmts.append({
                "quality": "HD 1080p",
                "sub": "No Watermark · Best Quality",
                "ext": "mp4",
                "url": hd_url,
                "filesize": 0,
            })

        if sd_url and sd_url != hd_url:
            fmts.append({
                "quality": "SD 720p",
                "sub": "No Watermark",
                "ext": "mp4",
                "url": sd_url,
                "filesize": 0,
            })

        if wm_url:
            fmts.append({
                "quality": "Original",
                "sub": "With TikTok Watermark",
                "ext": "mp4",
                "url": wm_url,
                "filesize": 0,
            })

        if audio_url:
            fmts.append({
                "quality": "Audio MP3",
                "sub": "Music / Sound only",
                "ext": "mp3",
                "url": audio_url,
                "filesize": 0,
            })

        if not fmts:
            return None

        author_info = info.get("uploader") or info.get("creator") or ""
        return {
            "title": info.get("title", "TikTok Video"),
            "cover": info.get("thumbnail", ""),
            "author": {"nickname": author_info},
            "formats": fmts,
        }

    except subprocess.TimeoutExpired:
        print("[ytdlp] timed out")
        return None
    except Exception as e:
        print(f"[ytdlp] error: {e}")
        return None


# ── Source 2: tikwm.com JSON API (fast, no scraping) ─────────────────────────

def source_tikwm(url: str) -> dict | None:
    """
    tikwm.com is a TikTok CDN proxy API. Tries HD first, then SD.
    Very fast (~1–2 s) when their servers aren't overloaded.
    """
    for hd in ("1", "0"):
        try:
            r = requests.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": hd},
                headers=HEADERS,
                timeout=25,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") == 0 and data.get("data"):
                v = data["data"]
                fmts = []

                if v.get("hdplay"):
                    fmts.append({"quality": "HD 1080p",  "sub": "No Watermark · Best Quality", "ext": "mp4", "url": v["hdplay"],  "filesize": v.get("hd_size", 0)})
                play = v.get("play")
                if play and play != v.get("hdplay"):
                    fmts.append({"quality": "SD 720p",   "sub": "No Watermark",                "ext": "mp4", "url": play,         "filesize": v.get("size", 0)})
                if v.get("wmplay"):
                    fmts.append({"quality": "Original",  "sub": "With TikTok Watermark",       "ext": "mp4", "url": v["wmplay"],  "filesize": v.get("wm_size", 0)})
                music = v.get("music") or v.get("music_info", {}).get("play")
                if music:
                    fmts.append({"quality": "Audio MP3", "sub": "Music / Sound only",          "ext": "mp3", "url": music,        "filesize": 0})

                if fmts:
                    return {
                        "title": v.get("title", "TikTok Video"),
                        "cover": v.get("cover", ""),
                        "author": v.get("author", {}),
                        "formats": fmts,
                    }
        except Exception as e:
            print(f"[tikwm hd={hd}] {e}")
    return None


# ── Source 3: SSS.plus (form-based, reliable fallback) ───────────────────────

def source_sssplus(url: str) -> dict | None:
    """sss.plus — lightweight TikTok downloader with a stable form POST."""
    try:
        session = requests.Session()
        session.headers.update({**HEADERS, "Referer": "https://sss.plus/", "Origin": "https://sss.plus"})

        r = session.get("https://sss.plus/", timeout=12)
        token = re.search(r'name="token"\s+value="([^"]+)"', r.text)
        if not token:
            token = re.search(r'"token"\s*:\s*"([^"]+)"', r.text)
        if not token:
            return None

        r2 = session.post(
            "https://sss.plus/api",
            data={"url": url, "token": token.group(1)},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=18,
        )
        data = r2.json()
        links = data.get("data", {}).get("links", []) or data.get("links", [])
        fmts = []
        for item in links:
            u = item.get("url") or item.get("a", "")
            if not u:
                continue
            label = item.get("text", "Download")
            ext = "mp3" if "mp3" in u or "audio" in label.lower() else "mp4"
            fmts.append({"quality": label, "sub": "No Watermark", "ext": ext, "url": u, "filesize": 0})
        if fmts:
            return {"title": data.get("title", "TikTok Video"), "cover": data.get("thumb", ""), "author": {}, "formats": fmts}
    except Exception as e:
        print(f"[sssplus] {e}")
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    # Also report yt-dlp version so you can confirm it's installed
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
        ytdlp_ver = v.stdout.strip()
    except Exception:
        ytdlp_ver = "not found"
    return jsonify({"status": "TikSave running", "version": "10.0", "yt_dlp": ytdlp_ver})


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/api")
def api():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"code": -1, "msg": "Missing url parameter"}), 400

    is_tiktok = any(x in url for x in ("tiktok.com", "vm.tiktok", "vt.tiktok"))
    if not is_tiktok:
        return jsonify({"code": -1, "msg": "Invalid TikTok URL"}), 400

    sources = [
        ("ytdlp",   source_ytdlp),
        ("tikwm",   source_tikwm),
        ("sssplus", source_sssplus),
    ]

    for name, fn in sources:
        print(f"[api] trying {name}…")
        try:
            result = fn(url)
            if result and result.get("formats"):
                print(f"[api] success via {name}")
                return jsonify({"code": 0, "data": result, "source": name})
        except Exception as e:
            print(f"[api] {name} raised: {e}")

    return jsonify({
        "code": -1,
        "msg": "Could not fetch this video. Make sure it is a public TikTok video and try again.",
    }), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
