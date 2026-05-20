# ReelSaver Backend — RapidAPI Version 5
# Deploy command: gunicorn app:app

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import requests as req

app = Flask(__name__)
CORS(app, origins="*", allow_headers=["Content-Type"], methods=["GET","POST","OPTIONS"])

RAPIDAPI_KEY = "f5c2b634ccmshe80f45741d18af0p1ad9a8jsn37f935d7fc4e"

BROWSER_HEADERS = {
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
    return jsonify({'status': 'ReelSaver API is running', 'version': '5.0'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


def get_tiktok_info(url):
    # Using Social Media Video Downloader API — works for TikTok
    api_url = "https://social-media-video-downloader.p.rapidapi.com/smvd/get/all"
    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": "social-media-video-downloader.p.rapidapi.com"
    }
    params = {"url": url}

    r    = req.get(api_url, headers=headers, params=params, timeout=25)
    data = r.json()

    if r.status_code != 200:
        raise Exception(f'API error: {r.status_code}')

    if not data.get('success') and not data.get('links'):
        raise Exception(data.get('message') or 'Could not fetch video')

    formats = []
    links   = data.get('links') or []

    for item in links:
        quality = item.get('quality') or item.get('resolution') or 'Download'
        dl_url  = item.get('link') or item.get('url')
        ext     = item.get('extension') or item.get('type') or 'mp4'

        if dl_url and 'video' in ext.lower() or ext in ['mp4','webm','mov']:
            formats.append({
                'quality':  quality,
                'ext':      'mp4',
                'url':      dl_url,
                'filesize': None,
            })

    # fallback — try direct url in response
    if not formats and data.get('url'):
        formats.append({
            'quality':  'Download',
            'ext':      'mp4',
            'url':      data['url'],
            'filesize': None,
        })

    if not formats:
        raise Exception('No downloadable formats found.')

    return {
        'platform':  'tiktok',
        'title':     data.get('title') or 'TikTok Video',
        'thumbnail': data.get('thumbnail') or data.get('picture'),
        'uploader':  data.get('author') or data.get('uploader'),
        'formats':   formats[:5],
    }


def get_instagram_info(url):
    api_url = "https://social-media-video-downloader.p.rapidapi.com/smvd/get/all"
    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": "social-media-video-downloader.p.rapidapi.com"
    }
    params = {"url": url}

    r    = req.get(api_url, headers=headers, params=params, timeout=25)
    data = r.json()

    if r.status_code != 200:
        raise Exception(f'API error: {r.status_code}')

    if not data.get('success') and not data.get('links'):
        raise Exception(data.get('message') or 'Could not fetch video')

    formats = []
    links   = data.get('links') or []

    for item in links:
        quality = item.get('quality') or item.get('resolution') or 'Download'
        dl_url  = item.get('link') or item.get('url')
        ext     = item.get('extension') or item.get('type') or 'mp4'

        if dl_url:
            formats.append({
                'quality':  quality,
                'ext':      ext,
                'url':      dl_url,
                'filesize': None,
            })

    if not formats and data.get('url'):
        formats.append({
            'quality':  'Download',
            'ext':      'mp4',
            'url':      data['url'],
            'filesize': None,
        })

    if not formats:
        raise Exception('No downloadable video found. Make sure it is a public post.')

    return {
        'platform':  'instagram',
        'title':     data.get('title') or 'Instagram Video',
        'thumbnail': data.get('thumbnail') or data.get('picture'),
        'uploader':  data.get('author') or data.get('uploader'),
        'formats':   formats[:5],
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

    try:
        result = get_tiktok_info(url) if is_tiktok(url) else get_instagram_info(url)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)[:300]}), 500


@app.route('/proxy')
def proxy():
    import urllib.parse
    video_url = urllib.parse.unquote(request.args.get('url', ''))
    ext       = request.args.get('ext', 'mp4')
    title     = request.args.get('title', 'video')

    if not video_url:
        return jsonify({'error': 'No URL'}), 400

    try:
        headers = {**BROWSER_HEADERS, 'Referer': 'https://www.tiktok.com/'}
        r       = req.get(video_url, headers=headers, stream=True, timeout=30)

        if r.status_code != 200:
            return jsonify({'error': f'Could not fetch: {r.status_code}'}), 502

        safe  = "".join(c for c in title if c.isalnum() or c in ' -_').strip()
        fname = f"{safe or 'video'}.{ext}"

        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        resp = Response(
            stream_with_context(generate()),
            status=200,
            content_type=r.headers.get('Content-Type', f'video/{ext}'),
        )
        resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        cl = r.headers.get('Content-Length')
        if cl:
            resp.headers['Content-Length'] = cl
        return resp

    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


if __name__ == '__main__':
    print('\n🚀 ReelSaver API v5 → http://localhost:5000\n')
    app.run(debug=True, port=5000, host='0.0.0.0')
