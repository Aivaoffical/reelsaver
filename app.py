# TikSave Backend v13
from flask import Flask, request, jsonify, send_file
import os
from flask_cors import CORS
import requests, subprocess, json, re

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ── yt-dlp helper: get best-quality URLs using -g flag ───────────────────────
def ytdlp_get_urls(url, extra_args=[]):
    """
    Uses yt-dlp -g to get direct video URLs.
    Returns dict with hd, sd, audio keys or None on failure.
    """
    base_args = [
        "yt-dlp", "-g",
        "--no-playlist", "--no-warnings",
        "--user-agent", UA,
        "--extractor-args", "tiktok:app_name=trill;app_version=34.1.2",
        "--add-header", "Referer:https://www.tiktok.com/",
    ]
    # HD (best video + audio merged)
    hd_cmd  = base_args + extra_args + ["-f", "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best", url]
    # SD fallback
    sd_cmd  = base_args + extra_args + ["-f", "worstvideo[ext=mp4]+bestaudio/worst[ext=mp4]/worst", url]
    # Audio only
    au_cmd  = base_args + extra_args + ["-f", "bestaudio[ext=m4a]/bestaudio", url]

    hd_url = sd_url = audio_url = None

    for fmt_name, cmd in [("HD", hd_cmd), ("SD", sd_cmd), ("audio", au_cmd)]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            if r.returncode == 0 and r.stdout.strip():
                lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip().startswith("http")]
                if lines:
                    if fmt_name == "HD":    hd_url    = lines[0]
                    elif fmt_name == "SD":  sd_url    = lines[0]
                    elif fmt_name == "audio": audio_url = lines[0]
            else:
                print(f"[ytdlp] {fmt_name} failed: {r.stderr[:120]}")
        except subprocess.TimeoutExpired:
            print(f"[ytdlp] {fmt_name} timed out")
        except FileNotFoundError:
            print("[ytdlp] yt-dlp not found")
            return None
        except Exception as e:
            print(f"[ytdlp] {fmt_name} error: {e}")

    if not hd_url:
        return None

    fmts = []
    fmts.append({"quality": "HD 1080p",  "sub": "No Watermark · Best Quality", "ext": "mp4", "url": hd_url,    "filesize": 0})
    if sd_url and sd_url != hd_url:
        fmts.append({"quality": "SD 480p",   "sub": "No Watermark · Smaller File",  "ext": "mp4", "url": sd_url,    "filesize": 0})
    if audio_url:
        fmts.append({"quality": "Audio",     "sub": "Music / Sound only",           "ext": "m4a", "url": audio_url, "filesize": 0})

    # Also get title via --dump-json
    title = "TikTok Video"
    cover = ""
    author = {}
    try:
        tj = subprocess.run(
            base_args + extra_args + ["--dump-json", "--skip-download", url],
            capture_output=True, text=True, timeout=20
        )
        if tj.returncode == 0 and tj.stdout.strip():
            info = json.loads(tj.stdout)
            title  = info.get("title", title)
            cover  = info.get("thumbnail", "")
            author = {"nickname": info.get("uploader") or ""}
    except Exception:
        pass

    return {"title": title, "cover": cover, "author": author, "formats": fmts}


# ── Source 1: yt-dlp with browser cookies ────────────────────────────────────
def source_ytdlp_cookies(url):
    for browser in ["chrome", "firefox", "edge", "safari", "chromium"]:
        print(f"[ytdlp-cookies] trying {browser}…")
        result = ytdlp_get_urls(url, extra_args=["--cookies-from-browser", browser])
        if result:
            print(f"[ytdlp-cookies] ✅ {browser}")
            return result
        # If yt-dlp not found, stop trying
        if result is None and browser == "chrome":
            break
    return None


# ── Source 2: yt-dlp plain (no cookies) ──────────────────────────────────────
def source_ytdlp_plain(url):
    result = ytdlp_get_urls(url)
    if result:
        print("[ytdlp-plain] ✅")
    return result


# ── Source 3: tikwm.com ───────────────────────────────────────────────────────
def source_tikwm(url):
    for hd in ("1", "0"):
        try:
            r = requests.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": hd},
                headers={"User-Agent": UA, "Referer": "https://www.tikwm.com/", "Origin": "https://www.tikwm.com", "Content-Type": "application/x-www-form-urlencoded"},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") == 0 and data.get("data"):
                v = data["data"]
                fmts = []
                # Always prefer hdplay for best quality
                if v.get("hdplay"):
                    fmts.append({"quality": "HD 1080p", "sub": "No Watermark · Best Quality", "ext": "mp4", "url": v["hdplay"], "filesize": v.get("hd_size", 0)})
                if v.get("play") and v.get("play") != v.get("hdplay"):
                    fmts.append({"quality": "SD 720p",  "sub": "No Watermark",                "ext": "mp4", "url": v["play"],   "filesize": v.get("size", 0)})
                if v.get("wmplay"):
                    fmts.append({"quality": "Original", "sub": "With TikTok Watermark",       "ext": "mp4", "url": v["wmplay"], "filesize": v.get("wm_size", 0)})
                music = v.get("music") or (v.get("music_info") or {}).get("play")
                if music:
                    fmts.append({"quality": "Audio MP3","sub": "Music only",                  "ext": "mp3", "url": music,       "filesize": 0})
                if fmts:
                    print(f"[tikwm hd={hd}] ✅")
                    return {"title": v.get("title", "TikTok Video"), "cover": v.get("cover", ""), "author": v.get("author", {}), "formats": fmts}
        except Exception as e:
            print(f"[tikwm hd={hd}] {e}")
    return None


# ── Source 4: cobalt.tools ────────────────────────────────────────────────────
def source_cobalt(url):
    try:
        r = requests.post(
            "https://api.cobalt.tools/",
            json={"url": url, "videoQuality": "1080", "filenameStyle": "basic"},
            headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": UA},
            timeout=20,
        )
        if not r.ok:
            return None
        data = r.json()
        if data.get("status") == "tunnel" and data.get("url"):
            return {"title": "TikTok Video", "cover": "", "author": {},
                    "formats": [{"quality": "HD", "sub": "No Watermark · Best Quality", "ext": "mp4", "url": data["url"], "filesize": 0}]}
        if data.get("status") == "picker":
            fmts = [{"quality": f"Option {i+1}", "sub": "No Watermark", "ext": "mp4", "url": item["url"], "filesize": 0}
                    for i, item in enumerate(data.get("picker", [])) if item.get("url")]
            if fmts:
                return {"title": "TikTok Video", "cover": "", "author": {}, "formats": fmts}
    except Exception as e:
        print(f"[cobalt] {e}")
    return None


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    html_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(html_path):
        return send_file(html_path)
    return jsonify({"status": "TikSave running — put index.html in the same folder"})

@app.route("/info")
def info():
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
        ytdlp = v.stdout.strip()
    except:
        ytdlp = "NOT INSTALLED"
    return jsonify({"status": "TikSave running", "version": "13.0", "yt_dlp": ytdlp})

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/debug")
def debug():
    info = {}
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
        info["yt_dlp"] = v.stdout.strip()
    except FileNotFoundError:
        info["yt_dlp"] = "NOT FOUND — run: pip install yt-dlp"
    browsers = []
    for b in ["chrome", "firefox", "edge", "safari"]:
        try:
            r = subprocess.run(["yt-dlp", "--cookies-from-browser", b, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                browsers.append(b)
        except:
            pass
    info["browsers"] = browsers or ["none"]
    info["tip"] = "Log into TikTok in Chrome or Firefox for best results"
    return jsonify(info)

@app.route("/api")
def api():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"code": -1, "msg": "Missing url"}), 400
    if not any(x in url for x in ("tiktok.com", "vm.tiktok", "vt.tiktok")):
        return jsonify({"code": -1, "msg": "Not a TikTok URL"}), 400

    for name, fn in [("yt-dlp+cookies", source_ytdlp_cookies), ("yt-dlp", source_ytdlp_plain), ("tikwm", source_tikwm), ("cobalt", source_cobalt)]:
        print(f"[api] trying {name}…")
        try:
            result = fn(url)
            if result and result.get("formats"):
                return jsonify({"code": 0, "data": result, "source": name})
        except Exception as e:
            print(f"[api] {name}: {e}")

    return jsonify({"code": -1, "msg": "Could not fetch video — visit localhost:5000/debug for help"}), 500

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  Open this in Chrome → http://localhost:5000")
    print("  Debug   → http://localhost:5000/debug")
    print("="*50 + "\n")
    app.run(debug=False, port=5000, host="0.0.0.0")
