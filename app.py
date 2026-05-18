# ReelSaver Backend — with proxy download to fix 403 errors
# pip install flask flask-cors yt-dlp gunicorn requests
# Run: python app.py
# Deploy: gunicorn app:app

from flask import Flask, request, jsonify, make_response, Response, stream_with_context
from flask_cors import CORS
from urllib.parse import urlparse
import yt_dlp
import requests as req

app = Flask(__name__)
CORS(app, origins="*", allow_headers=["Content-Type"], methods=["GET","POST","OPTIONS"])

ALLOWED = ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com', 'instagram.com', 'www.tiktok.com', 'www.instagram.com']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.tiktok.com/',
    'Accept': '*/*',
}

def is_allowed(url):
    try:
        host = urlparse(url).netloc.lower().replace('www.', '')
        return any(host == d or host.endswith('.' + d) for d in ALLOWED)
    except:
        return False

def detect_platform(url):
    if 'tiktok.com' in url: return 'tiktok'
    if 'instagram.com' in url: return 'instagram'
    return 'unknown'

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    return response

@app.route('/')
def home():
    return jsonify({'status': 'ReelSaver API is running', 'version': '2.0'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/get-info', methods=['POST', 'OPTIONS'])
def get_info():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    body     = request.get_json(silent=True) or {}
    url      = (body.get('url') or '').strip()

    if not url:
        return jsonify({'error': 'No URL provided.'}), 400
    if not is_allowed(url):
        return jsonify({'error': 'Only TikTok and Instagram URLs are supported.'}), 400

    platform = detect_platform(url)

    ydl_opts = {
        'quiet':       True,
        'noplaylist':  True,
        'no_warnings': True,
        'http_headers': HEADERS,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({'error': 'Could not fetch video. It may be private or deleted.'}), 404

        formats = []
        seen    = set()

        for f in reversed(info.get('formats', [])):
            if not f.get('url'):
                continue
            if f.get('vcodec', 'none') == 'none':
                continue

            height  = f.get('height') or 0
            quality = (
                f.get('format_note')
                or (str(height) + 'p' if height else None)
                or 'Standard'
            )

            key = f"{quality}-{f.get('ext','')}"
            if key in seen:
                continue
            seen.add(key)

            # Build a proxy URL so the browser downloads via our server
            # This avoids the 403 Forbidden error from TikTok/Instagram
            import urllib.parse
            encoded = urllib.parse.quote(f['url'], safe='')
            proxy_url = f"/proxy?url={encoded}&ext={f.get('ext','mp4')}&title={urllib.parse.quote(info.get('title','video')[:50], safe='')}"

            formats.append({
                'quality':  quality,
                'ext':      f.get('ext', 'mp4'),
                'url':      proxy_url,   # use proxy instead of direct URL
                'filesize': f.get('filesize'),
            })

        # Fallback if no formats
        if not formats:
            for f in info.get('formats', []):
                if f.get('url') and f.get('ext') in ['mp4', 'webm']:
                    import urllib.parse
                    encoded   = urllib.parse.quote(f['url'], safe='')
                    proxy_url = f"/proxy?url={encoded}&ext={f.get('ext','mp4')}&title=video"
                    formats.append({
                        'quality':  f.get('format_note') or 'Download',
                        'ext':      f.get('ext', 'mp4'),
                        'url':      proxy_url,
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
            return jsonify({'error': 'This video is private.'}), 403
        if '404' in err:
            return jsonify({'error': 'Video not found or deleted.'}), 404
        clean = err.split('ERROR:')[-1].strip()[:300]
        return jsonify({'error': clean or 'Could not fetch this video.'}), 500
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)[:200]}'}), 500


@app.route('/proxy')
def proxy():
    """
    Proxy endpoint — fetches the video from TikTok/Instagram
    and streams it to the browser with proper download headers.
    This fixes the 403 Forbidden error when clicking download.
    """
    video_url = request.args.get('url', '')
    ext       = request.args.get('ext', 'mp4')
    title     = request.args.get('title', 'video')

    if not video_url:
        return jsonify({'error': 'No URL'}), 400

    import urllib.parse
    video_url = urllib.parse.unquote(video_url)

    try:
        # Stream the video through our server
        r = req.get(video_url, headers=HEADERS, stream=True, timeout=30)

        if r.status_code != 200:
            return jsonify({'error': f'Could not fetch video: {r.status_code}'}), 502

        # Clean filename
        safe_title = "".join(c for c in title if c.isalnum() or c in ' -_').strip()
        filename   = f"{safe_title or 'video'}.{ext}"

        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        response = Response(
            stream_with_context(generate()),
            status=200,
            content_type=r.headers.get('Content-Type', f'video/{ext}'),
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Access-Control-Allow-Origin'] = '*'

        content_length = r.headers.get('Content-Length')
        if content_length:
            response.headers['Content-Length'] = content_length

        return response

    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


if __name__ == '__main__':
    print('\n🚀 ReelSaver API v2 → http://localhost:5000\n')
    app.run(debug=True, port=5000, host='0.0.0.0')
