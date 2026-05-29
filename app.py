# TikSave Backend v11
# Uses only HTTP requests — no yt-dlp binary needed.
# Primary: tikwm.com API  |  Fallbacks: lovetik, ssstik, douyin API
# gunicorn app:app

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, re, json, time

app = Flask(__name__)

# ── CORS: allow every origin (required for browser fetches) ──────────────────
CORS(app, resources={r"/*": {"origins": "*"}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "OPTIONS"])

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Explicit OPTIONS handler so preflight never fails ────────────────────────
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1 — tikwm.com  (fastest, genuine API)
# ─────────────────────────────────────────────────────────────────────────────
def source_tikwm(url):
    for hd in ("1", "0"):
        try:
            r = requests.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": hd},
                headers={**BASE_HEADERS,
                         "Referer": "https://www.tiktok.com/",
                         "Origin":  "https://www.tiktok.com"},
                timeout=28,
            )
            d = r.json()
            if d.get("code") == 0:
                v = d["data"]
                fmts = []
                if v.get("hdplay"):
                    fmts.append({"quality":"HD 1080p","sub":"No Watermark · Best","ext":"mp4","url":v["hdplay"],"filesize":v.get("hd_size",0)})
                if v.get("play") and v.get("play") != v.get("hdplay"):
                    fmts.append({"quality":"SD 720p","sub":"No Watermark","ext":"mp4","url":v["play"],"filesize":v.get("size",0)})
                if v.get("wmplay"):
                    fmts.append({"quality":"Original","sub":"With Watermark","ext":"mp4","url":v["wmplay"],"filesize":v.get("wm_size",0)})
                music = v.get("music") or (v.get("music_info") or {}).get("play")
                if music:
                    fmts.append({"quality":"Audio MP3","sub":"Sound only","ext":"mp3","url":music,"filesize":0})
                if fmts:
                    return {"title":v.get("title","TikTok Video"),"cover":v.get("cover",""),"author":v.get("author",{}),"formats":fmts}
        except Exception as e:
            print(f"[tikwm hd={hd}] {e}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2 — lovetik.com  (stable JSON search endpoint)
# ─────────────────────────────────────────────────────────────────────────────
def source_lovetik(url):
    try:
        r = requests.post(
            "https://lovetik.com/api/ajax/search",
            data={"query": url},
            headers={**BASE_HEADERS,
                     "Referer": "https://lovetik.com/",
                     "Origin":  "https://lovetik.com",
                     "X-Requested-With": "XMLHttpRequest",
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            timeout=22,
        )
        d = r.json()
        links = d.get("links", [])
        fmts = []
        seen = set()
        for item in links:
            u = item.get("a") or item.get("url","")
            if not u or u in seen: continue
            seen.add(u)
            label = (item.get("text") or "Download").strip()
            ext = "mp3" if ("mp3" in u.lower() or "audio" in label.lower()) else "mp4"
            fmts.append({"quality":label,"sub":"No Watermark","ext":ext,"url":u,"filesize":0})
        if fmts:
            return {"title":d.get("title","TikTok Video"),"cover":d.get("cover",""),"author":{},"formats":fmts}
    except Exception as e:
        print(f"[lovetik] {e}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 3 — ssstik.io  (form + token)
# ─────────────────────────────────────────────────────────────────────────────
def source_ssstik(url):
    try:
        s = requests.Session()
        s.headers.update({**BASE_HEADERS,"Referer":"https://ssstik.io/","Origin":"https://ssstik.io"})
        page = s.get("https://ssstik.io/en", timeout=12)
        tok = re.search(r'id="token"\s+value="([^"]+)"', page.text) or \
              re.search(r'name="tt"\s+value="([^"]+)"', page.text)
        if not tok: return None
        r2 = s.post(
            "https://ssstik.io/abc?url=dl",
            data={"id": url, "locale": "en", "tt": tok.group(1)},
            headers={"Content-Type":"application/x-www-form-urlencoded"},
            timeout=18,
        )
        html = r2.text
        fmts = []
        # no-watermark links
        for u in re.findall(r'href="(https://[^"]+\.mp4[^"]*)"', html)[:2]:
            fmts.append({"quality":"HD No Watermark","sub":"No Watermark","ext":"mp4","url":u,"filesize":0})
        for u in re.findall(r'href="(https://[^"]+\.mp3[^"]*)"', html)[:1]:
            fmts.append({"quality":"Audio MP3","sub":"Sound only","ext":"mp3","url":u,"filesize":0})
        if fmts:
            return {"title":"TikTok Video","cover":"","author":{},"formats":fmts}
    except Exception as e:
        print(f"[ssstik] {e}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 4 — snaptik.app  (reliable, widely used)
# ─────────────────────────────────────────────────────────────────────────────
def source_snaptik(url):
    try:
        s = requests.Session()
        s.headers.update({**BASE_HEADERS,"Referer":"https://snaptik.app/","Origin":"https://snaptik.app"})
        page = s.get("https://snaptik.app/en", timeout=12)
        tok = re.search(r'name="token"\s+value="([^"]+)"', page.text)
        if not tok: return None
        r2 = s.post("https://snaptik.app/abc2.php",
                    data={"url": url, "token": tok.group(1), "lang": "en"},
                    headers={"Content-Type":"application/x-www-form-urlencoded"},
                    timeout=18)
        html = r2.text
        fmts = []
        for i, u in enumerate(re.findall(r'href="(https://[^"]+\.mp4[^"]*)"', html)[:3]):
            q = "HD No Watermark" if i == 0 else f"Quality {i+1}"
            fmts.append({"quality":q,"sub":"No Watermark","ext":"mp4","url":u,"filesize":0})
        if fmts:
            return {"title":"TikTok Video","cover":"","author":{},"formats":fmts}
    except Exception as e:
        print(f"[snaptik] {e}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({"status":"ok","version":"11.0"})

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/api")
def api():
    url = request.args.get("url","").strip()
    if not url:
        return jsonify({"code":-1,"msg":"Missing url"}), 400
    if not any(x in url for x in ("tiktok.com","vm.tiktok","vt.tiktok")):
        return jsonify({"code":-1,"msg":"Not a TikTok URL"}), 400

    for name, fn in [("tikwm",source_tikwm),("lovetik",source_lovetik),
                     ("ssstik",source_ssstik),("snaptik",source_snaptik)]:
        print(f"[api] trying {name}")
        try:
            res = fn(url)
            if res and res.get("formats"):
                print(f"[api] OK via {name}")
                return jsonify({"code":0,"data":res,"source":name})
        except Exception as e:
            print(f"[api] {name} error: {e}")

    return jsonify({"code":-1,"msg":"Could not fetch. Make sure the video is public."}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
