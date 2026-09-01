"""HTML 分享上传服务：页面选一个 .html 文件，传到团队 S3 固定路径，返回公开链接。

用法: python3 upload_server.py [port]   (默认 8000)
"""
import io
import json
import re
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3
from botocore.config import Config

BUCKET = "starlitshorts"
PREFIX = "aigc/drama/html_share/"  # 路径写定
REGION = "us-east-1"
MAX_BYTES = 20 * 1024 * 1024


def make_client():
    """凭证优先读脚本旁的 .s3creds（两行 hex：AK、SK，不入库），否则走 boto3 默认链。"""
    import os
    creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".s3creds")
    kwargs = {}
    if os.path.exists(creds_path):
        with open(creds_path) as f:
            ak_hex, sk_hex = f.read().split()
        kwargs = {
            "aws_access_key_id": bytes.fromhex(ak_hex).decode(),
            "aws_secret_access_key": bytes.fromhex(sk_hex).decode(),
        }
    return boto3.client("s3", region_name=REGION,
                        config=Config(signature_version="s3v4"), **kwargs)


s3 = make_client()

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HTML 分享上传</title>
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; max-width: 520px;
         margin: 4rem auto; padding: 0 1rem; color: #1e293b; }
  h1 { font-size: 1.3rem; }
  button { font-size: 1rem; padding: .5rem 1.5rem; cursor: pointer; }
  #result { margin-top: 1.5rem; word-break: break-all; }
  #result a { color: #2563eb; }
  .err { color: #dc2626; }
</style>
</head>
<body>
<h1>上传 HTML，返回 S3 分享链接</h1>
<p><input type="file" id="file" accept=".html,.htm"></p>
<p><button id="btn">上传</button></p>
<div id="result"></div>
<script>
document.getElementById('btn').onclick = async () => {
  const f = document.getElementById('file').files[0];
  const out = document.getElementById('result');
  if (!f) { out.innerHTML = '<span class="err">请先选择文件</span>'; return; }
  out.textContent = '上传中…';
  try {
    const res = await fetch('/upload?name=' + encodeURIComponent(f.name), {
      method: 'POST', body: f
    });
    const j = await res.json();
    out.innerHTML = res.ok
      ? '链接：<a href="' + j.url + '" target="_blank">' + j.url + '</a>'
      : '<span class="err">' + j.error + '</span>';
  } catch (e) {
    out.innerHTML = '<span class="err">' + e + '</span>';
  }
};
</script>
</body>
</html>"""


def safe_name(raw):
    name = raw.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.html?$", "", name, flags=re.I)
    name = re.sub(r"[^\w一-鿿.-]", "_", name) or "page"
    return name[:80] + ".html"


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/upload":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "空请求体"})
            return
        if length > MAX_BYTES:
            self._json(413, {"error": f"文件超过 {MAX_BYTES // 1024 // 1024}MB 限制"})
            return
        raw_name = urllib.parse.parse_qs(parsed.query).get("name", ["page.html"])[0]
        key = PREFIX + time.strftime("%Y%m%d_%H%M%S_") + safe_name(raw_name)
        data = self.rfile.read(length)
        try:
            s3.upload_fileobj(
                io.BytesIO(data), BUCKET, key,
                ExtraArgs={"ContentType": "text/html; charset=utf-8"},
            )
        except Exception as e:
            self._json(500, {"error": f"S3 上传失败: {e}"})
            return
        url = f"https://{BUCKET}.s3.amazonaws.com/{urllib.parse.quote(key)}"
        self._json(200, {"url": url, "key": key})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"HTML 分享上传服务: http://localhost:{port}  ->  s3://{BUCKET}/{PREFIX}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
