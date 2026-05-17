# SnapLoad Backend — TikTok & Instagram Downloader
# ─────────────────────────────────────────────────
# SETUP:   pip install flask flask-cors flask-limiter yt-dlp gunicorn
# RUN:     python app.py
# DEPLOY:  gunicorn app:app  (on Render.com free tier)
# ─────────────────────────────────────────────────

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from urllib.parse import urlparse
import yt_dlp

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

limiter = Limiter(
    get_remote_address, app=app,
    default_limits=["15 per minute", "150 per hour"],
    storage_uri="memory://",
)

ALLOWED = ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com', 'instagram.com']

def is_allowed(url):
    try:
        host = urlparse(url).netloc.lower().lstrip('www.')
        return any(host == d or host.endswith('.' + d) for d in ALLOWED)
    except:
        return False

def detect_platform(url):
    if 'tiktok.com' in url: return 'tiktok'
    if 'instagram.com' in url: return 'instagram'
    return 'unknown'

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'SnapLoad'})

@app.route('/get-info', methods=['POST'])
@limiter.limit("15 per minute")
def get_info():
    body = request.get_json(silent=True) or {}
    url  = (body.get('url') or '').strip()

    if not url:
        return jsonify({'error': 'No URL provided.'}), 400
    if not is_allowed(url):
        return jsonify({'error': 'Only TikTok and Instagram URLs are supported.'}), 400

    platform = detect_platform(url)
    ydl_opts = {'quiet': True, 'noplaylist': True, 'no_warnings': True}

    if platform == 'tiktok':
        ydl_opts['extractor_args'] = {
            'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({'error': 'Could not fetch video. It may be private or deleted.'}), 404

        formats, seen = [], set()
        for f in reversed(info.get('formats', [])):
            if not f.get('url') or f.get('vcodec') == 'none':
                continue
            quality = f.get('format_note') or (str(f['height'])+'p' if f.get('height') else 'Standard')
            key = f"{quality}-{f.get('ext','')}"
            if key in seen: continue
            seen.add(key)
            formats.append({
                'quality': quality, 'ext': f.get('ext','mp4'),
                'url': f['url'], 'filesize': f.get('filesize'),
            })

        return jsonify({
            'platform':  platform,
            'title':     info.get('title') or 'Video',
            'thumbnail': info.get('thumbnail'),
            'uploader':  info.get('uploader') or info.get('creator') or info.get('channel'),
            'formats':   formats[:6],
        })

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if 'private' in err.lower(): return jsonify({'error': 'This video is private.'}), 403
        if '404' in err: return jsonify({'error': 'Video not found or deleted.'}), 404
        return jsonify({'error': err.split('ERROR:')[-1].strip()[:220]}), 500
    except Exception as e:
        return jsonify({'error': str(e)[:220]}), 500

if __name__ == '__main__':
    print('\n🚀 SnapLoad → http://localhost:5000\n')
    app.run(debug=True, port=5000, host='0.0.0.0')
