# TikSave v14 — Server downloads via yt-dlp, streams file to browser
# This bypasses all CDN blocking issues
#
# Run:  python app.py
# Open: http://localhost:5000

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import subprocess, json, os, uuid, tempfile, threading, time, re

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Temp folder for downloaded videos (auto-cleaned every 30 min)
TEMP_DIR = os.path.join(tempfile.gettempdir(), "tiksave_dl")
os.makedirs(TEMP_DIR, exist_ok=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Auto-cleanup old temp files ───────────────────────────────────────────────
def _cleanup_loop():
    while True:
        time.sleep(600)
        try:
            now = time.time()
            for fname in os.listdir(TEMP_DIR):
                fpath = os.path.join(TEMP_DIR, fname)
                if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 1800:
                    os.remove(fpath)
        except Exception:
            pass

threading.Thread(target=_cleanup_loop, daemon=True).start()


# ── yt-dlp runner: tries cookies from each browser, then plain ───────────────
def run_ytdlp(extra_args: list, timeout=90) -> subprocess.CompletedProcess | None:
    """
    Tries yt-dlp with Chrome/Firefox/Edge cookies first, then without.
    Returns CompletedProcess on first success, None if all fail.
    """
    base = [
        "yt-dlp",
        "--no-playlist", "--no-warnings",
        "--user-agent", UA,
        "--extractor-args", "tiktok:app_name=trill;app_version=34.1.2",
        "--add-header", "Referer:https://www.tiktok.com/",
    ]

    attempts = [
        ["--cookies-from-browser", "chrome"],
        ["--cookies-from-browser", "firefox"],
        ["--cookies-from-browser", "edge"],
        [],  # plain — no cookies
    ]

    for cookie_args in attempts:
        try:
            cmd = base + cookie_args + extra_args
            label = cookie_args[1] if cookie_args else "no-cookies"
            print(f"[ytdlp] trying {label}…")
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                print(f"[ytdlp] ✅ success ({label})")
                return r
            else:
                print(f"[ytdlp] {label} failed: {r.stderr[:120]}")
        except FileNotFoundError:
            print("[ytdlp] yt-dlp not installed — run: pip install yt-dlp")
            return None
        except subprocess.TimeoutExpired:
            print(f"[ytdlp] timed out")
        except Exception as e:
            print(f"[ytdlp] error: {e}")
    return None


# ── /api  — get video info (title, thumbnail, author) ────────────────────────
@app.route("/api")
def api():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"code": -1, "msg": "Missing url"}), 400
    if not any(x in url for x in ("tiktok.com", "vm.tiktok", "vt.tiktok")):
        return jsonify({"code": -1, "msg": "Not a TikTok URL"}), 400

    # Get video info with yt-dlp --dump-json (fast, no download)
    r = run_ytdlp(["--dump-json", "--skip-download", url], timeout=40)
    if not r or not r.stdout.strip():
        return jsonify({"code": -1, "msg": "Could not fetch video info. Make sure yt-dlp is installed and try again."}), 500

    try:
        info = json.loads(r.stdout)
    except Exception:
        return jsonify({"code": -1, "msg": "Bad response from yt-dlp"}), 500

    title  = info.get("title", "TikTok Video")
    cover  = info.get("thumbnail", "")
    author = {"nickname": info.get("uploader") or info.get("creator") or ""}

    # Build format buttons — all point to /download which does the actual work
    enc = __import__("urllib.parse", fromlist=["quote"]).quote
    base_url = f"/download?url={enc(url)}"

    formats = [
        {"quality": "HD 1080p",  "sub": "No Watermark · Best Quality", "ext": "mp4", "dl_url": base_url + "&quality=hd"},
        {"quality": "SD 480p",   "sub": "No Watermark · Smaller File",  "ext": "mp4", "dl_url": base_url + "&quality=sd"},
        {"quality": "Audio",     "sub": "MP3 / Sound only",             "ext": "mp3", "dl_url": base_url + "&quality=audio"},
    ]

    return jsonify({"code": 0, "data": {"title": title, "cover": cover, "author": author, "formats": formats}})


# ── /download  — yt-dlp downloads file; Flask streams it to browser ───────────
@app.route("/download")
def download():
    url     = request.args.get("url", "").strip()
    quality = request.args.get("quality", "hd")

    if not url:
        return "Missing url", 400

    # Choose yt-dlp format string
    if quality == "audio":
        fmt = "bestaudio[ext=m4a]/bestaudio/best"
        merge = "m4a"
        out_ext = "mp3"
    elif quality == "sd":
        fmt = "worstvideo[height<=480][ext=mp4]+bestaudio/worst[ext=mp4]/worst"
        merge = "mp4"
        out_ext = "mp4"
    else:  # hd (default)
        fmt = "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best"
        merge = "mp4"
        out_ext = "mp4"

    file_id  = uuid.uuid4().hex[:10]
    out_tmpl = os.path.join(TEMP_DIR, f"{file_id}.%(ext)s")

    r = run_ytdlp([
        "-f", fmt,
        "--merge-output-format", merge,
        "-o", out_tmpl,
        url,
    ], timeout=180)

    if not r:
        return "yt-dlp not installed. Run:  pip install yt-dlp", 500

    # Find the output file (extension may differ slightly)
    out_file = None
    for fname in os.listdir(TEMP_DIR):
        if fname.startswith(file_id):
            out_file = os.path.join(TEMP_DIR, fname)
            break

    if not out_file or not os.path.exists(out_file):
        # Try to get a useful error from stderr
        err = r.stderr[:400] if r else "Unknown error"
        print(f"[download] file not found. stderr: {err}")
        return f"Download failed. Make sure you are logged into TikTok in Chrome and try again.\n\nDetail: {err}", 500

    # Stream file to browser with proper filename
    try:
        title = request.args.get("title", "tiktok-video")
        safe  = re.sub(r"[^\w\s\-]", "", title).strip()[:50] or "tiktok-video"
        fname = f"{safe}.{out_ext}"
        return send_file(out_file, as_attachment=True, download_name=fname,
                         mimetype="audio/mpeg" if out_ext == "mp3" else "video/mp4")
    except Exception as e:
        return str(e), 500


# ── /health  ──────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"ok": True})


# ── /debug  ───────────────────────────────────────────────────────────────────
@app.route("/debug")
def debug():
    info = {}
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
        info["yt_dlp"] = v.stdout.strip() if v.returncode == 0 else "ERROR: " + v.stderr[:100]
    except FileNotFoundError:
        info["yt_dlp"] = "NOT INSTALLED — run: pip install yt-dlp"

    browsers = []
    for b in ["chrome", "firefox", "edge", "safari"]:
        try:
            r = subprocess.run(
                ["yt-dlp", "--cookies-from-browser", b, "--version"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                browsers.append(b)
        except Exception:
            pass
    info["browsers_detected"] = browsers or ["none — log into TikTok in Chrome or Firefox"]
    info["temp_dir"] = TEMP_DIR
    info["tip"] = "Log into TikTok in Chrome for best results, then retry"
    return jsonify(info)


# ── Serve index.html ──────────────────────────────────────────────────────────
@app.route("/")
def home():
    html_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(html_path):
        return send_file(html_path)
    return "Put index.html in the same folder as app.py", 404


if __name__ == "__main__":
    print("\n" + "=" * 52)
    print("  ✅ TikSave is running!")
    print("  👉 Open Chrome and go to: http://localhost:5000")
    print("  🔍 Debug info:            http://localhost:5000/debug")
    print("=" * 52 + "\n")
    app.run(debug=False, port=5000, host="0.0.0.0")
