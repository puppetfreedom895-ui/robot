"""只读管理台：看看它今天干了什么。

所有接口都是 GET，没有任何写操作。默认只绑 127.0.0.1；
如果要放到公网看，必须配 token——否则等于把它的生活挂在网上。
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from robot.life.store import LifeStore
from robot.log import get_logger

logger = get_logger(__name__)

# 只放行长得像截图的名字，挡住 ../ 这类路径穿越
_SHOT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}\.png$")
MAX_SHOTS = 12


def _esc(text: str) -> str:
    """把文本转义进 HTML。

    @param text: 原始文本。
    @returns: 转义后的文本。
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class Dashboard:
    """把 LifeStore 的只读快照和截图通过 HTTP 暴露出来。"""

    def __init__(
        self,
        store: LifeStore,
        *,
        host: str = "127.0.0.1",
        port: int = 8787,
        token: str = "",
        screens_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._host = host
        self._port = port
        self._token = token
        self._screens = screens_dir
        self._server: ThreadingHTTPServer | None = None

    @property
    def port(self) -> int:
        """实际监听端口（传 0 时由系统分配）。

        @returns: 端口号。
        """
        return self._port

    @property
    def running(self) -> bool:
        """是否正在服务。

        @returns: 运行中为 True。
        """
        return self._server is not None

    def start(self) -> None:
        """在后台线程启动 HTTP 服务。"""
        handler = _make_handler(self)
        server = ThreadingHTTPServer((self._host, self._port), handler)
        server.daemon_threads = True
        self._server = server
        self._port = int(server.server_address[1])
        threading.Thread(target=server.serve_forever, name="dashboard", daemon=True).start()
        logger.info("管理台已启动：http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        """停止 HTTP 服务。"""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        logger.info("管理台已停止")

    # ---- 供请求处理使用 ----

    def authorized(self, token: str) -> bool:
        """校验访问令牌；没配令牌表示只允许本机直连。

        @param token: 请求带来的令牌。
        @returns: 放行为 True。
        """
        if not self._token:
            return True
        return token == self._token

    def snapshot(self) -> dict[str, Any]:
        """取一份当前快照。

        @returns: 状态、事件、日记、目标、用量。
        """
        return self._store.snapshot()

    def shot_names(self) -> list[str]:
        """列出最新几张截图。

        @returns: 文件名列表，新的在前。
        """
        if self._screens is None or not self._screens.is_dir():
            return []
        files = sorted(
            (path for path in self._screens.glob("*.png") if _SHOT_NAME.match(path.name)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [path.name for path in files[:MAX_SHOTS]]

    def shot_bytes(self, name: str) -> bytes | None:
        """读取一张截图。

        @param name: 文件名。
        @returns: 文件内容；不合法或不存在时返回 None。
        """
        if self._screens is None or not _SHOT_NAME.match(name):
            return None
        path = self._screens / name
        if not path.is_file():
            return None
        return path.read_bytes()


def _make_handler(dash: Dashboard) -> type[BaseHTTPRequestHandler]:
    """构造绑定到某个管理台的请求处理类。

    @param dash: 管理台实例。
    @returns: 处理类。
    """

    class Handler(BaseHTTPRequestHandler):
        server_version = "robot-dashboard"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的命名约定
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/healthz":
                self._send(200, "text/plain; charset=utf-8", b"ok")
                return

            query = parse_qs(parsed.query)
            token = (query.get("t", [""])[0] or self.headers.get("X-Token", "")).strip()
            if not dash.authorized(token):
                body = "需要令牌：在地址后面加 ?t=你的令牌".encode()
                self._send(401, "text/plain; charset=utf-8", body)
                return

            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
            elif path == "/api/snapshot":
                payload = json.dumps(dash.snapshot(), ensure_ascii=False).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", payload)
            elif path == "/api/shots":
                payload = json.dumps({"shots": dash.shot_names()}, ensure_ascii=False).encode()
                self._send(200, "application/json; charset=utf-8", payload)
            elif path.startswith("/api/shot/"):
                name = unquote(path[len("/api/shot/") :])
                data = dash.shot_bytes(name)
                if data is None:
                    self._send(404, "text/plain; charset=utf-8", b"no such shot")
                else:
                    self._send(200, "image/png", data)
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("管理台 %s %s", self.address_string(), fmt % args)

    return Handler


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>它今天干了什么</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#252a34;--text:#e6e8ee;--dim:#8b93a7;--accent:#6ea8fe}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",
  "PingFang SC","Microsoft YaHei",sans-serif}
header{padding:20px 20px 8px;display:flex;flex-wrap:wrap;gap:12px;align-items:baseline}
h1{font-size:20px;margin:0 12px 0 0}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;
  padding:3px 11px;font-size:12px;color:var(--dim)}
.chip b{color:var(--text);font-weight:600}
main{padding:8px 20px 40px;display:grid;gap:16px;grid-template-columns:1fr 1fr}
@media (max-width:860px){main{grid-template-columns:1fr}}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
h2{font-size:13px;color:var(--dim);font-weight:600;margin:0 0 10px;letter-spacing:.04em}
ol,ul{margin:0;padding-left:0;list-style:none}
li{padding:4px 0;border-bottom:1px dashed rgba(255,255,255,.05)}
li:last-child{border-bottom:none}
.at{color:var(--dim);font-variant-numeric:tabular-nums;margin-right:8px;font-size:12px}
.kind{display:inline-block;min-width:52px;font-size:12px;color:var(--dim)}
.empty{color:var(--dim);font-size:13px}
.day{margin-bottom:10px}
.day h3{font-size:12px;color:var(--dim);margin:0 0 4px;font-weight:500}
.day p{margin:0;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}
.grid img{width:100%;border-radius:8px;border:1px solid var(--line);display:block}
</style>
</head>
<body>
<header>
  <h1 id="name">…</h1>
  <span class="chip">精力 <b id="energy">-</b></span>
  <span class="chip">无聊 <b id="boredom">-</b></span>
  <span class="chip">心情 <b id="mood">-</b></span>
  <span class="chip">今日 <b id="tokens">-</b> token</span>
  <span class="chip" id="focus-chip" hidden>琢磨 <b id="focus"></b></span>
</header>
<main>
  <section><h2>今天做了什么</h2><ol id="events"><li class="empty">加载中…</li></ol></section>
  <section><h2>惦记的事</h2><ul id="goals"><li class="empty">加载中…</li></ul></section>
  <section><h2>日记</h2><div id="diary"><p class="empty">加载中…</p></div></section>
  <section><h2>手机截图</h2><div id="shots" class="grid"></div></section>
</main>
<script>
const T = new URLSearchParams(location.search).get('t') || '';
const withToken = u => T ? u + (u.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(T) : u;
const KIND = {act:'做事', talk:'有人说话', idle:'发呆', sleep:'睡觉', blocked:'被拦住'};

function setText(id, value){ document.getElementById(id).textContent = value; }
function list(el, items, render, emptyText){
  el.innerHTML = '';
  if(!items.length){
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = emptyText;
    el.appendChild(li);
    return;
  }
  items.forEach(item => el.appendChild(render(item)));
}
function line(tag, cls, text){
  const el = document.createElement(tag);
  if(cls) el.className = cls;
  el.textContent = text;
  return el;
}

function render(d){
  setText('name', d.state.name);
  setText('energy', Math.round(d.state.energy));
  setText('boredom', Math.round(d.state.boredom));
  setText('mood', d.state.mood || '—');
  setText('tokens', d.tokens_today.toLocaleString());
  const hasFocus = !!d.state.focus;
  document.getElementById('focus-chip').hidden = !hasFocus;
  if(hasFocus) setText('focus', d.state.focus);

  list(document.getElementById('events'), d.events.slice().reverse(), item => {
    const li = document.createElement('li');
    li.appendChild(line('span','at', item.at));
    li.appendChild(line('span','kind', KIND[item.kind] || item.kind));
    li.appendChild(line('span','', item.content));
    return li;
  }, '还没干什么');

  list(
    document.getElementById('goals'),
    d.goals,
    text => line('li','', '· ' + text),
    '没有惦记的事'
  );

  const diary = document.getElementById('diary');
  diary.innerHTML = '';
  if(!d.diary.length){ diary.appendChild(line('p','empty','还没写日记')); }
  d.diary.forEach(day => {
    const box = line('div','day','');
    box.appendChild(line('h3','', day.day));
    box.appendChild(line('p','', day.lines.join('；')));
    diary.appendChild(box);
  });

  fetch(withToken('/api/shots')).then(r => r.json()).then(data => {
    const grid = document.getElementById('shots');
    grid.innerHTML = '';
    if(!data.shots.length){ grid.appendChild(line('p','empty','还没有截图')); return; }
    data.shots.forEach(name => {
      const img = document.createElement('img');
      img.src = withToken('/api/shot/' + encodeURIComponent(name));
      img.alt = name;
      img.loading = 'lazy';
      grid.appendChild(img);
    });
  });
}

async function load(){
  try{
    const response = await fetch(withToken('/api/snapshot'));
    if(!response.ok) throw new Error(response.status);
    render(await response.json());
  }catch(err){
    setText('name', '连不上管理台');
  }
}
load();
setInterval(load, 5000);
</script>
</body>
</html>
"""
