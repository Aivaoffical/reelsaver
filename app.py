# TikSave Backend v8 - yt-dlp for maximum quality
# gunicorn app:app

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import subprocess
import json

app = Flask(__name__)
CORS(app, origins="*")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.tiktok.com/",
}

@app.route("/")
def home():
    return jsonify({"status": "TikSave running", "version": "8.0"})

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/api")
def api():
    url = request.args.get("url", "").strip()
    if not url or "tiktok.com" not in url:
        return jsonify({"code": -1, "msg": "Invalid TikTok URL"}), 400

    # Method 1: yt-dlp (highest quality)
    try:
        cmd = ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings", "-j",
               "--extractor-args", "tiktok:webpage_download=true", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout:
            info = json.loads(result.stdout)
            formats = []
            seen = set()
            all_fmts = sorted(
                [f for f in info.get("formats", []) if f.get("vcodec") != "none" and f.get("url")],
                key=lambda x: (x.get("height") or 0), reverse=True
            )
            for f in all_fmts:
                height = f.get("height") or 0
                note = f.get("format_note", "") or ""
                key = f"{height}-{note}"
                if key in seen: continue
                seen.add(key)
                if height >= 1080: quality, sub = "HD 1080p", "No Watermark - Best Quality"
                elif height >= 720: quality, sub = "HD 720p", "No Watermark - High Quality"
                elif height >= 480: quality, sub = "SD 480p", "No Watermark"
                elif "watermark" in note.lower(): quality, sub = "Original", "With Watermark"
                else: quality, sub = note or (f"{height}p" if height else "Standard"), "No Watermark"
                formats.append({"quality": quality, "sub": sub, "ext": f.get("ext", "mp4"),
                    "url": f["url"], "filesize": f.get("filesize") or f.get("filesize_approx") or 0})
                if len(formats) >= 4: break
            audio = [f for f in info.get("formats", []) if f.get("vcodec") == "none" and f.get("url")]
            if audio:
                formats.append({"quality": "Audio MP3", "sub": "Music only", "ext": "mp3",
                    "url": audio[-1]["url"], "filesize": 0})
            if formats:
                return jsonify({"code": 0, "data": {
                    "title": info.get("title", "TikTok Video"),
                    "cover": info.get("thumbnail", ""),
                    "author": {"nickname": info.get("uploader", "")},
                    "formats": formats}})
    except Exception as e:
        print(f"yt-dlp failed: {e}")

    # Method 2: tikwm fallback
    try:
        r = requests.post("https://www.tikwm.com/api/",
            data={"url": url, "hd": "1"}, headers=HEADERS, timeout=20)
        data = r.json()
        if data.get("code") == 0 and data.get("data"):
            v = data["data"]
            formats = []
            if v.get("hdplay"): formats.append({"quality": "HD 1080p", "sub": "No Watermark - Best", "ext": "mp4", "url": v["hdplay"], "filesize": v.get("hd_size", 0)})
            if v.get("play") and v["play"] != v.get("hdplay"): formats.append({"quality": "SD 720p", "sub": "No Watermark", "ext": "mp4", "url": v["play"], "filesize": v.get("size", 0)})
            if v.get("wmplay"): formats.append({"quality": "Original", "sub": "With Watermark", "ext": "mp4", "url": v["wmplay"], "filesize": v.get("wm_size", 0)})
            if v.get("music"): formats.append({"quality": "Audio MP3", "sub": "Music only", "ext": "mp3", "url": v["music"], "filesize": 0})
            if formats:
                return jsonify({"code": 0, "data": {"title": v.get("title", "TikTok Video"),
                    "cover": v.get("cover", ""), "author": v.get("author", {}), "formats": formats}})
    except Exception as e:
        print(f"tikwm failed: {e}")

    return jsonify({"code": -1, "msg": "Could not fetch this video. Please try again."}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
