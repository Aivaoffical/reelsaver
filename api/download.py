import requests

def handler(request):
    from http.server import BaseHTTPRequestHandler
    
    url = request.args.get("url", "").strip() if hasattr(request, "args") else ""
    
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json"
    }
    
    if not url or "tiktok.com" not in url:
        return {"statusCode": 400, "headers": headers, "body": "{\"code\": -1, \"msg\": \"Invalid URL\"}"}
    
    try:
        r = requests.post(
            "https://www.tikwm.com/api/",
            data={"url": url, "hd": "1"},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.tiktok.com/"},
            timeout=20
        )
        return {"statusCode": 200, "headers": headers, "body": r.text}
    except Exception as e:
        return {"statusCode": 500, "headers": headers, "body": f"{\"code\": -1, \"msg\": \"{str(e)}\"}" }
