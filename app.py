# TikSave Backend v11 - Fixed & Improved
# Run locally:  python app.py
# Deploy:       gunicorn app:app
#
# Sources tried in order:
#   1. tikwm.com  (fast JSON API, most reliable)
#   2. yt-dlp     (local, updated extractor args)
#   3. ssstik.io  (form-based fallback)

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import subprocess
import json
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


# ── Source 1: tikwm.com (fast JSON API, very reliable) ───────────────────────

def source_tikwm(url: str) -> dict | None:
    for hd in ("1", "0"):
        try:
            r = requests.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": hd},
                headers={
                    "User-Agent": BROWSER_UA,
                    "Referer": "https://www.tikwm.com/",
                    "Origin": "https://www.tikwm.com",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            print(f"[tikwm hd={hd}] response code: {data.get('code')}")
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
                        "title":  v.get("title", "TikTok Video"),
                        "cover":  v.get("cover", ""),
                        "author": v.get("author", {}),
                        "formats": fmts,
                    }
        except Exception as e:
            print(f"[tikwm hd={hd}] error: {e}")
    return None


# ── Source 2: yt-dlp (runs locally, updated 2024 args) ───────────────────────

def source_ytdlp(url: str) -> dict | None:
    try:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist",
            "--no-warnings",
            # Updated extractor args for 2024/2025 TikTok API
            "--extractor-args", "tiktok:app_name=trill;app_version=34.1.2;manifest_app_version=2024102201",
            "--user-agent", BROWSER_UA,
            "--add-header", "Referer:https://www.tiktok.com/",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if result.returncode != 0 or not result.stdout.strip():
            print(f"[ytdlp] failed, stderr: {result.stderr[:400]}")
            return None

        info = json.loads(result.stdout)
        fmts = []
        seen_urls = set()
        formats = info.get("formats", [])

        hd_url = sd_url = wm_url = audio_url = None

        for f in reversed(formats):
            fu = f.get("url", "")
            if not fu or fu in seen_urls:
                continue
            seen_urls.add(fu)

            note   = (f.get("format_note") or "").lower()
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            height = f.get("height") or 0

            is_video      = vcodec != "none"
            is_audio_only = vcodec == "none" and acodec != "none"

            if is_audio_only and not audio_url:
                audio_url = fu
                continue
            if not is_video:
                continue
            if "watermark" in note and not wm_url:
                wm_url = fu
                continue
            if height >= 720 and not hd_url:
                hd_url = fu
                continue
            if height > 0 and not sd_url and fu != hd_url:
                sd_url = fu

        # Fallback: use yt-dlp's best single URL
        if not hd_url:
            hd_url = info.get("url") or info.get("webpage_url")

        if hd_url:
            fmts.append({"quality": "HD 1080p",  "sub": "No Watermark · Best Quality", "ext": "mp4", "url": hd_url,    "filesize": 0})
        if sd_url and sd_url != hd_url:
            fmts.append({"quality": "SD 720p",   "sub": "No Watermark",                "ext": "mp4", "url": sd_url,    "filesize": 0})
        if wm_url:
            fmts.append({"quality": "Original",  "sub": "With TikTok Watermark",       "ext": "mp4", "url": wm_url,    "filesize": 0})
        if audio_url:
            fmts.append({"quality": "Audio MP3", "sub": "Music / Sound only",          "ext": "mp3", "url": audio_url, "filesize": 0})

        if not fmts:
            return None

        return {
            "title":  info.get("title", "TikTok Video"),
            "cover":  info.get("thumbnail", ""),
            "author": {"nickname": info.get("uploader") or info.get("creator") or ""},
            "formats": fmts,
        }

    except subprocess.TimeoutExpired:
        print("[ytdlp] timed out")
        return None
    except Exception as e:
        print(f"[ytdlp] error: {e}")
        return None


# ── Source 3: ssstik.io (form-based fallback) ─────────────────────────────────

def source_ssstik(url: str) -> dict | None:
    try:
        session = requests.Session()
        base_headers = {
            "User-Agent": BROWSER_UA,
            "Accept-Language": "en-US,en;q=0.9",
        }
        session.headers.update(base_headers)

        r = session.get("https://ssstik.io/en", timeout=12)
        # Extract tt (the token used in the form)
        tt = re.search(r'id="s_tt"\s+value="([^"]+)"', r.text)
        if not tt:
            tt = re.search(r'name="tt"\s+value="([^"]+)"', r.text)
        if not tt:
            print("[ssstik] could not find token")
            return None

        r2 = session.post(
            "https://ssstik.io/abc?url=dl",
            data={"id": url, "locale": "en", "tt": tt.group(1)},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://ssstik.io/en",
                "Origin": "https://ssstik.io",
                "HX-Request": "true",
                "HX-Target": "target",
                "HX-Trigger": "form",
                "HX-Current-URL": "https://ssstik.io/en",
            },
            timeout=20,
        )

        html = r2.text
        fmts = []

        # Parse download links from the HTML response
        # Look for anchor tags with download links
        links = re.findall(r'href="(https://[^"]+)"[^>]*>\s*(?:<[^>]+>)*\s*([^<]{3,})', html)
        for link_url, label in links:
            label = label.strip()
            if not any(kw in link_url for kw in ["tiktok", "cdn", "download", "tikcdn", "v19", "v26", "v39"]):
                continue
            ext = "mp3" if ("mp3" in link_url or "audio" in label.lower() or "music" in label.lower()) else "mp4"
            sub = "No Watermark" if ("watermark" not in label.lower()) else "With Watermark"
            fmts.append({"quality": label[:30], "sub": sub, "ext": ext, "url": link_url, "filesize": 0})

        if fmts:
            # Try to get title from HTML
            title_m = re.search(r'<p[^>]*class="[^"]*maintext[^"]*"[^>]*>([^<]+)</p>', html)
            title = title_m.group(1).strip() if title_m else "TikTok Video"
            cover_m = re.search(r'<img[^>]+src="(https://[^"]+)"[^>]*class="[^"]*img[^"]*"', html)
            cover = cover_m.group(1) if cover_m else ""
            return {"title": title, "cover": cover, "author": {}, "formats": fmts}

    except Exception as e:
        print(f"[ssstik] error: {e}")
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
        ytdlp_ver = v.stdout.strip()
    except Exception:
        ytdlp_ver = "not found"
    return jsonify({"status": "TikSave running", "version": "11.0", "yt_dlp": ytdlp_ver})


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
        ("tikwm",   source_tikwm),
        ("ytdlp",   source_ytdlp),
        ("ssstik",  source_ssstik),
    ]

    for name, fn in sources:
        print(f"[api] trying {name}…")
        try:
            result = fn(url)
            if result and result.get("formats"):
                print(f"[api] ✅ success via {name}")
                return jsonify({"code": 0, "data": result, "source": name})
        except Exception as e:
            print(f"[api] {name} raised: {e}")

    return jsonify({
        "code": -1,
        "msg": "Could not fetch this video. Make sure it is a public TikTok video and try again.",
    }), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
