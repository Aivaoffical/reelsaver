# TikSave Backend v7 - High Quality Downloads
# gunicorn app:app

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import json

app = Flask(__name__)
CORS(app, origins="*")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.tiktok.com/',
    'Origin': 'https://www.tiktok.com',
}

@app.route('/')
def home():
    return jsonify({'status': 'TikSave running', 'version': '7.0'})

@app.route('/health')
def health():
    return jsonify({'ok': True})

@app.route('/api')
def api():
    url = request.args.get('url', '').strip()
    if not url or 'tiktok.com' not in url:
        return jsonify({'code': -1, 'msg': 'Invalid TikTok URL'}), 400

    # Try Method 1: tikwm.com with HD flag
    try:
        r = requests.post(
            'https://www.tikwm.com/api/',
            data={'url': url, 'hd': '1'},
            headers=HEADERS,
            timeout=20
        )
        data = r.json()
        if data.get('code') == 0 and data.get('data'):
            v = data['data']
            formats = []

            # HD no watermark
            if v.get('hdplay'):
                formats.append({
                    'quality': 'HD 1080p',
                    'sub': 'No Watermark · Best Quality',
                    'ext': 'mp4',
                    'url': v['hdplay'],
                    'filesize': v.get('hd_size', 0)
                })

            # SD no watermark
            if v.get('play') and v.get('play') != v.get('hdplay'):
                formats.append({
                    'quality': 'SD 720p',
                    'sub': 'No Watermark',
                    'ext': 'mp4',
                    'url': v['play'],
                    'filesize': v.get('size', 0)
                })

            # With watermark
            if v.get('wmplay'):
                formats.append({
                    'quality': 'Original',
                    'sub': 'With TikTok Watermark',
                    'ext': 'mp4',
                    'url': v['wmplay'],
                    'filesize': v.get('wm_size', 0)
                })

            # Audio
            if v.get('music'):
                formats.append({
                    'quality': 'Audio MP3',
                    'sub': 'Music / Sound only',
                    'ext': 'mp3',
                    'url': v['music'],
                    'filesize': 0
                })

            if formats:
                return jsonify({
                    'code': 0,
                    'data': {
                        'title': v.get('title', 'TikTok Video'),
                        'cover': v.get('cover', ''),
                        'author': v.get('author', {}),
                        'formats': formats
                    }
                })
    except Exception as e:
        print(f"tikwm failed: {e}")

    # Try Method 2: snaptik
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        # Get token
        r = session.get('https://snaptik.app/en', timeout=10)
        token_match = re.search(r'name="token"\s+value="([^"]+)"', r.text)
        if token_match:
            token = token_match.group(1)
            r2 = session.post('https://snaptik.app/abc2.php', data={
                'url': url,
                'token': token,
                'lang': 'en'
            }, timeout=15)

            # Extract video URLs from response
            urls = re.findall(r'href="(https://[^"]+\.mp4[^"]*)"', r2.text)
            if urls:
                formats = []
                for i, u in enumerate(urls[:3]):
                    formats.append({
                        'quality': f'HD Quality {i+1}',
                        'sub': 'No Watermark',
                        'ext': 'mp4',
                        'url': u,
                        'filesize': 0
                    })
                return jsonify({
                    'code': 0,
                    'data': {
                        'title': 'TikTok Video',
                        'cover': '',
                        'author': {},
                        'formats': formats
                    }
                })
    except Exception as e:
        print(f"snaptik failed: {e}")

    # Try Method 3: musicaldown
    try:
        session2 = requests.Session()
        session2.headers.update(HEADERS)

        r = session2.get('https://musicaldown.com/en', timeout=10)
        token_match = re.search(r'name="(?:_token|token)"\s+value="([^"]+)"', r.text)
        id_match = re.search(r'name="id"\s+value="([^"]+)"', r.text)

        if token_match and id_match:
            form_data = {
                'id': url,
                id_match.group(0).split('name="')[1].split('"')[0]: id_match.group(1),
                '_token': token_match.group(1)
            }
            r2 = session2.post('https://musicaldown.com/download', data=form_data, timeout=15)
            urls = re.findall(r'href="(https://[^"]+)"[^>]*>\s*(?:HD|Download|MP4)', r2.text)
            if urls:
                formats = [{'quality': 'HD Download', 'sub': 'No Watermark', 'ext': 'mp4', 'url': urls[0], 'filesize': 0}]
                return jsonify({
                    'code': 0,
                    'data': {'title': 'TikTok Video', 'cover': '', 'author': {}, 'formats': formats}
                })
    except Exception as e:
        print(f"musicaldown failed: {e}")

    return jsonify({'code': -1, 'msg': 'Could not fetch this video. Please try again or try a different video.'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
