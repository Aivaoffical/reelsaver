# TikSave Backend - Simple proxy for tikwm.com
# Deploy: gunicorn app:app

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app, origins="*")

@app.route('/')
def home():
    return jsonify({'status': 'TikSave API running'})

@app.route('/api', methods=['GET'])
def get_video():
    url = request.args.get('url', '')
    if not url or 'tiktok.com' not in url:
        return jsonify({'code': -1, 'msg': 'Invalid TikTok URL'}), 400
    
    try:
        r = requests.post(
            'https://www.tikwm.com/api/',
            data={'url': url, 'hd': '1'},
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
            timeout=15
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
