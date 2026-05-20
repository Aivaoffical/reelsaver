# ReelSaver Backend — Using RapidAPI
# pip install flask flask-cors gunicorn requests
# Run: python app.py
# Deploy: gunicorn app:app

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import requests as req
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app, origins="*", allow_headers=["Content-Type"], methods=["GET","POST","OPTIONS"])

# ─────────────────────────────────────────────────
# 🔑 PASTE YOUR RAPIDAPI KEY HERE
RAPIDAPI_KEY = "f5c2b634ccmshe80f45741d18af0p1ad9a8jsn37f935d7fc4e"
# ─────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

def is_tiktok(url):
    return 'tiktok.com' in url or 'vm.tiktok.com' in url

def is_instagram(url):
    return 'instagram.com' in url

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    return response

@app.route('/')
def home():
    return jsonify({'status': 'ReelSaver API is running', 'version': '3.0'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


# ── TIKTOK via RapidAPI ──────────────────────────
def get_tiktok_info(url):
    api_url = "https://tiktok-scraper7.p.rapidapi.com/video/info"
    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": "tiktok-scraper7.p.rapidapi.com"
    }
    params = {"url": url, "hd": "1"}

    r = req.get(api_url, headers=headers, params=params, timeout=20)
    data = r.json()

    if r.status_code != 200 or data.get('code') != 0:
        raise Exception(data.get('msg') or 'Could not fetch TikTok video')

    video = data.get('data', {})

    # Build formats list
    formats = []

    # No watermark HD
    nwm_hd = video.get('hdplay') or video.get('play')
    if nwm_hd:
        formats.append({
            'quality':  'HD — No Watermark',
            'ext':      'mp4',
            'url':      nwm_hd,
            'filesize': video.get('hd_size') or video.get('size'),
        })

    # No watermark SD
    nwm_sd = video.get('play')
    if nwm_sd and nwm_sd != nwm_hd:
        formats.append({
            'quality':  'SD — No Watermark',
            'ext':      'mp4',
            'url':      nwm_sd,
            'filesize': video.get('size'),
        })

    # Watermarked version
    wm = video.get('wmplay')
    if wm:
        formats.append({
            'quality':  'With Watermark',
            'ext':      'mp4',
            'url':      wm,
            'filesize': video.get('wm_size'),
        })

    # Music only
    music = video.get('music')
    if music:
        formats.append({
            'quality':  'Audio Only (MP3)',
            'ext':      'mp3',
            'url':      music,
            'filesize': None,
        })

    return {
        'platform':  'tiktok',
        'title':     video.get('title') or 'TikTok Video',
        'thumbnail': video.get('cover') or video.get('origin_cover'),
        'uploader':  video.get('author', {}).get('nickname') or video.get('author', {}).get('unique_id'),
        'formats':   formats,
    }


# ── INSTAGRAM via RapidAPI ───────────────────────
def get_instagram_info(url):
    api_url = "https://instagram-downloader-download-instagram-videos-stories.p.rapidapi.com/index"
    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": "instagram-downloader-download-instagram-videos-stories.p.rapidapi.com"
    }
    params = {"url": url}

    r = req.get(api_url, headers=headers, params=params, timeout=20)
    data = r.json()

    if r.status_code != 200:
        raise Exception('Could not fetch Instagram video')

    # Handle different response formats
    media = data if isinstance(data, dict) else {}

    # Try to get video URLs
    formats = []

    # Direct video URL
    video_url = (
        media.get('url') or
        media.get('video_url') or
        (media.get('media', [{}])[0].get('url') if media.get('media') else None)
    )

    if video_url:
        formats.append({
            'quality':  'HD Video',
            'ext':      'mp4',
            'url':      video_url,
            'filesize': None,
        })

    # Multiple media
    for item in media.get('media', []):
        u = item.get('url') or item.get('video_url')
        if u and u != video_url:
            formats.append({
                'quality': f"Version {len(formats)+1}",
                'ext':     'mp4',
                'url':     u,
                'filesize': None,
            })

    if not formats:
        raise Exception('No downloadable video found. Make sure it is a public video.')

    return {
        'platform':  'instagram',
        'title':     media.get('title') or media.get('caption') or 'Instagram Video',
        'thumbnail': media.get('thumbnail') or media.get('thumbnail_url'),
        'uploader':  media.get('owner', {}).get('username') if media.get('owner') else None,
        'formats':   formats,
    }


@app.route('/get-info', methods=['POST', 'OPTIONS'])
def get_info():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    body = request.get_json(silent=True) or {}
    url  = (body.get('url') or '').strip()

    if not url:
        return jsonify({'error': 'No URL provided.'}), 400

    if not (is_tiktok(url) or is_instagram(url)):
        return jsonify({'error': 'Only TikTok and Instagram URLs are supported.'}), 400

    if RAPIDAPI_KEY == "f5c2b634ccmshe80f45741d18af0p1ad9a8jsn37f935d7fc4e":
        return jsonify({'error': 'RapidAPI key not configured. Please add your API key to app.py'}), 500

    try:
        if is_tiktok(url):
            result = get_tiktok_info(url)
        else:
            result = get_instagram_info(url)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)[:300]}), 500


# ── PROXY — streams video through server ─────────
@app.route('/proxy')
def proxy():
    import urllib.parse
    video_url = urllib.parse.unquote(request.args.get('url', ''))
    ext       = request.args.get('ext', 'mp4')
    title     = request.args.get('title', 'video')

    if not video_url:
        return jsonify({'error': 'No URL'}), 400

    try:
        headers = {**HEADERS, 'Referer': 'https://www.tiktok.com/'}
        r = req.get(video_url, headers=headers, stream=True, timeout=30)

        if r.status_code != 200:
            return jsonify({'error': f'Could not fetch: {r.status_code}'}), 502

        safe  = "".join(c for c in title if c.isalnum() or c in ' -_').strip()
        fname = f"{safe or 'video'}.{ext}"

        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk: yield chunk

        resp = Response(
            stream_with_context(generate()),
            status=200,
            content_type=r.headers.get('Content-Type', f'video/{ext}'),
        )
        resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        cl = r.headers.get('Content-Length')
        if cl: resp.headers['Content-Length'] = cl
        return resp

    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


if __name__ == '__main__':
    print('\n🚀 ReelSaver API v3 → http://localhost:5000\n')
    app.run(debug=True, port=5000, host='0.0.0.0')
