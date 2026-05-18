# ReelSaver Backend
# pip install flask flask-cors yt-dlp gunicorn
# Run locally: python app.py
# Deploy: gunicorn app:app

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from urllib.parse import urlparse
import yt_dlp

app = Flask(__name__)

# Allow ALL origins - fixes CORS errors completely
CORS(app, origins="*", allow_headers=["Content-Type"], methods=["GET","POST","OPTIONS"])

ALLOWED = ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com', 'instagram.com', 'www.tiktok.com', 'www.instagram.com']

def is_allowed(url):
    try:
        host = urlparse(url).netloc.lower()
        host = host.replace('www.', '')
        return any(host == d or host.endswith('.' + d) for d in ALLOWED)
    except:
        return False

def detect_platform(url):
    if 'tiktok.com' in url: return 'tiktok'
    if 'instagram.com' in url: return 'instagram'
    return 'unknown'

# Handle preflight OPTIONS requests (needed for CORS)
@app.before_request
def handle_options():
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
        return response

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    return response

@app.route('/')
def home():
    return jsonify({'status': 'ReelSaver API is running', 'version': '1.0'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/get-info', methods=['POST', 'OPTIONS'])
def get_info():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    body = request.get_json(silent=True) or {}
    url  = (body.get('url') or '').strip()

    if not url:
        return jsonify({'error': 'No URL provided.'}), 400

    if not is_allowed(url):
        return jsonify({'error': 'Only TikTok and Instagram URLs are supported.'}), 400

    platform = detect_platform(url)

    # yt-dlp options
    ydl_opts = {
        'quiet':        True,
        'noplaylist':   True,
        'no_warnings':  True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        }
    }

    if platform == 'tiktok':
        ydl_opts['extractor_args'] = {
            'tiktok': {
                'webpage_download': ['true'],
            }
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({'error': 'Could not fetch video. It may be private or deleted.'}), 404

        # Build formats list
        formats = []
        seen    = set()

        for f in reversed(info.get('formats', [])):
            if not f.get('url'):
                continue
            # Skip audio-only
            if f.get('vcodec', 'none') == 'none':
                continue
            # Skip very low quality
            height = f.get('height') or 0
            if height and height < 100:
                continue

            quality = (
                f.get('format_note')
                or (str(height) + 'p' if height else None)
                or 'Standard'
            )

            key = f"{quality}-{f.get('ext','')}"
            if key in seen:
                continue
            seen.add(key)

            formats.append({
                'quality':  quality,
                'ext':      f.get('ext', 'mp4'),
                'url':      f['url'],
                'filesize': f.get('filesize'),
            })

        # If no formats found, try any format with a URL
        if not formats:
            for f in info.get('formats', []):
                if f.get('url') and f.get('ext') in ['mp4', 'webm', 'mov']:
                    formats.append({
                        'quality':  f.get('format_note') or 'Download',
                        'ext':      f.get('ext', 'mp4'),
                        'url':      f['url'],
                        'filesize': f.get('filesize'),
                    })
                    if len(formats) >= 3:
                        break

        return jsonify({
            'platform':  platform,
            'title':     info.get('title') or 'Video',
            'thumbnail': info.get('thumbnail'),
            'uploader':  info.get('uploader') or info.get('creator') or info.get('channel'),
            'formats':   formats[:6],
        })

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if 'private' in err.lower():
            return jsonify({'error': 'This video is private and cannot be downloaded.'}), 403
        if '404' in err:
            return jsonify({'error': 'Video not found. It may have been deleted.'}), 404
        if 'login' in err.lower() or 'sign in' in err.lower():
            return jsonify({'error': 'This video requires login. Only public videos are supported.'}), 403
        clean = err.split('ERROR:')[-1].strip()[:300]
        return jsonify({'error': clean or 'Could not download this video.'}), 500

    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)[:200]}'}), 500

if __name__ == '__main__':
    print('\n🚀 ReelSaver API → http://localhost:5000\n')
    app.run(debug=True, port=5000, host='0.0.0.0')
