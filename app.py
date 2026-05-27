# TikSave Backend v9 - Reliable Multi-Source TikTok Downloader
# Deploy: gunicorn app:app
# Requirements: flask flask-cors requests

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import json
import time

app = Flask(__name__)
CORS(app, origins="*")

# ── Shared headers that mimic a real browser ──────────────────────────────────
BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.tiktok.com/',
    'Origin': 'https://www.tiktok.com',
    'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'cross-site',
}

# ── Helper ────────────────────────────────────────────────────────────────────

def fmt_size(n):
    """Return human-readable byte count or empty string."""
    if not n:
        return ""
    n = int(n)
    if n > 1_000_000:
        return f"{n/1_000_000:.1f} MB"
    if n > 1_000:
        return f"{n//1_000} KB"
    return f"{n} B"


def build_formats(v: dict) -> list:
    """Turn a tikwm data dict into our standard formats list."""
    fmts = []

    # HD no-watermark (best)
    if v.get('hdplay'):
        fmts.append({
            'quality': 'HD 1080p',
            'sub': 'No Watermark · Best Quality',
            'ext': 'mp4',
            'url': v['hdplay'],
            'filesize': v.get('hd_size', 0),
        })

    # SD no-watermark
    play = v.get('play') or v.get('nwm_video_url_HQ') or v.get('nwm_video_url')
    if play and play != v.get('hdplay'):
        fmts.append({
            'quality': 'SD 720p',
            'sub': 'No Watermark',
            'ext': 'mp4',
            'url': play,
            'filesize': v.get('size', 0),
        })

    # With watermark
    if v.get('wmplay'):
        fmts.append({
            'quality': 'Original',
            'sub': 'With TikTok Watermark',
            'ext': 'mp4',
            'url': v['wmplay'],
            'filesize': v.get('wm_size', 0),
        })

    # Audio / music
    music = v.get('music') or v.get('music_info', {}).get('play')
    if music:
        fmts.append({
            'quality': 'Audio MP3',
            'sub': 'Music / Sound only',
            'ext': 'mp3',
            'url': music,
            'filesize': 0,
        })

    return fmts


# ── Source 1: tikwm.com (most reliable, real API) ────────────────────────────

def source_tikwm(url: str) -> dict | None:
    """
    tikwm.com provides a genuine TikTok CDN proxy API.
    We try HD first, then fall back to non-HD on failure.
    """
    for hd_flag in ('1', '0'):
        try:
            r = requests.post(
                'https://www.tikwm.com/api/',
                data={'url': url, 'hd': hd_flag},
                headers=BROWSER_HEADERS,
                timeout=25,
            )
            r.raise_for_status()
            data = r.json()
            if data.get('code') == 0 and data.get('data'):
                v = data['data']
                fmts = build_formats(v)
                if fmts:
                    return {
                        'title': v.get('title', 'TikTok Video'),
                        'cover': v.get('cover', ''),
                        'author': v.get('author', {}),
                        'formats': fmts,
                    }
        except Exception as e:
            print(f"[tikwm hd={hd_flag}] {e}")
    return None


# ── Source 2: ssstik.io ──────────────────────────────────────────────────────

def source_ssstik(url: str) -> dict | None:
    """
    ssstik.io is a popular, stable TikTok downloader.
    It uses a simple form POST and returns HTML with direct CDN links.
    """
    try:
        session = requests.Session()
        session.headers.update({
            **BROWSER_HEADERS,
            'Referer': 'https://ssstik.io/',
            'Origin': 'https://ssstik.io',
        })

        # Step 1: load page to grab token
        r = session.get('https://ssstik.io/en', timeout=12)
        token_match = re.search(r'id="token"\s+value="([^"]+)"', r.text) or \
                      re.search(r'name="(?:tt|id)"\s+value="([^"]+)"', r.text)
        if not token_match:
            return None

        # Step 2: submit download form
        r2 = session.post(
            'https://ssstik.io/abc?url=dl',
            data={'id': url, 'locale': 'en', 'tt': token_match.group(1)},
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=18,
        )

        html = r2.text

        # Extract video links
        fmts = []
        # No-watermark download links
        nwm = re.findall(
            r'href="(https://[^"]+)"[^>]*>\s*(?:[^<]*?)<[^>]*>(?:[^<]*?)(?:Without watermark|No watermark|HD)',
            html, re.IGNORECASE
        )
        # Broader fallback
        if not nwm:
            nwm = re.findall(r'href="(https://[^"]+\.mp4[^"]*)"', html)

        for i, u in enumerate(nwm[:2]):
            label = 'HD No Watermark' if i == 0 else 'SD No Watermark'
            fmts.append({'quality': label, 'sub': 'No Watermark', 'ext': 'mp4', 'url': u, 'filesize': 0})

        # Watermark version
        wm = re.findall(r'href="(https://[^"]+)"[^>]*>.*?watermark', html, re.IGNORECASE | re.DOTALL)
        if wm and wm[0] not in nwm:
            fmts.append({'quality': 'Original', 'sub': 'With Watermark', 'ext': 'mp4', 'url': wm[0], 'filesize': 0})

        # Audio
        mp3 = re.findall(r'href="(https://[^"]+\.mp3[^"]*)"', html)
        if mp3:
            fmts.append({'quality': 'Audio MP3', 'sub': 'Music only', 'ext': 'mp3', 'url': mp3[0], 'filesize': 0})

        # Title / author
        title_m = re.search(r'<title[^>]*>([^<]+)</title>', html)
        title = title_m.group(1).strip() if title_m else 'TikTok Video'

        if fmts:
            return {'title': title, 'cover': '', 'author': {}, 'formats': fmts}

    except Exception as e:
        print(f"[ssstik] {e}")

    return None


# ── Source 3: lovetik.com ────────────────────────────────────────────────────

def source_lovetik(url: str) -> dict | None:
    """
    lovetik.com — another reliable scraper, uses JSON endpoint.
    """
    try:
        r = requests.post(
            'https://lovetik.com/api/ajax/search',
            data={'query': url},
            headers={
                **BROWSER_HEADERS,
                'Referer': 'https://lovetik.com/',
                'Origin': 'https://lovetik.com',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        links = data.get('links', [])
        fmts = []
        seen = set()

        for item in links:
            v_url = item.get('a') or item.get('url', '')
            if not v_url or v_url in seen:
                continue
            seen.add(v_url)
            label = (item.get('text') or item.get('resolution') or 'Download').strip()
            ext = 'mp3' if 'mp3' in v_url.lower() or 'audio' in label.lower() else 'mp4'
            fmts.append({
                'quality': label,
                'sub': 'No Watermark' if 'watermark' not in label.lower() else 'With Watermark',
                'ext': ext,
                'url': v_url,
                'filesize': 0,
            })

        if fmts:
            title = data.get('title') or 'TikTok Video'
            cover = data.get('cover') or data.get('thumb') or ''
            return {'title': title, 'cover': cover, 'author': {}, 'formats': fmts}

    except Exception as e:
        print(f"[lovetik] {e}")

    return None


# ── Source 4: tikmate.online ─────────────────────────────────────────────────

def source_tikmate(url: str) -> dict | None:
    """
    tikmate.online has a clean JSON API that returns CDN links.
    """
    try:
        r = requests.post(
            'https://tikmate.online/api/',
            data={'url': url},
            headers={
                **BROWSER_HEADERS,
                'Referer': 'https://tikmate.online/',
                'Origin': 'https://tikmate.online',
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        fmts = []
        if data.get('no_watermark'):
            fmts.append({
                'quality': 'HD No Watermark',
                'sub': 'No Watermark · Best Quality',
                'ext': 'mp4',
                'url': data['no_watermark'],
                'filesize': 0,
            })
        if data.get('no_watermark_hd') and data['no_watermark_hd'] != data.get('no_watermark'):
            fmts.insert(0, {
                'quality': 'HD 1080p',
                'sub': 'No Watermark · Best Quality',
                'ext': 'mp4',
                'url': data['no_watermark_hd'],
                'filesize': 0,
            })
        if data.get('watermark'):
            fmts.append({
                'quality': 'Original',
                'sub': 'With Watermark',
                'ext': 'mp4',
                'url': data['watermark'],
                'filesize': 0,
            })
        if data.get('music') or data.get('audio'):
            fmts.append({
                'quality': 'Audio MP3',
                'sub': 'Music only',
                'ext': 'mp3',
                'url': data.get('music') or data.get('audio'),
                'filesize': 0,
            })

        if fmts:
            return {
                'title': data.get('title', 'TikTok Video'),
                'cover': data.get('cover', ''),
                'author': {},
                'formats': fmts,
            }

    except Exception as e:
        print(f"[tikmate] {e}")

    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def home():
    return jsonify({'status': 'TikSave running', 'version': '9.0'})


@app.route('/health')
def health():
    return jsonify({'ok': True})


@app.route('/api')
def api():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'code': -1, 'msg': 'Missing url parameter'}), 400

    # Accept short links and full links
    if 'tiktok.com' not in url and 'vm.tiktok' not in url and 'vt.tiktok' not in url:
        return jsonify({'code': -1, 'msg': 'Invalid TikTok URL'}), 400

    # Try each source in order; first success wins
    sources = [
        ('tikwm',    source_tikwm),
        ('lovetik',  source_lovetik),
        ('tikmate',  source_tikmate),
        ('ssstik',   source_ssstik),
    ]

    for name, fn in sources:
        print(f"[api] trying {name} …")
        try:
            result = fn(url)
            if result and result.get('formats'):
                print(f"[api] success via {name}")
                return jsonify({'code': 0, 'data': result, 'source': name})
        except Exception as e:
            print(f"[api] {name} raised: {e}")

    return jsonify({
        'code': -1,
        'msg': 'Could not fetch this video. Make sure it is a public TikTok video and try again.'
    }), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
