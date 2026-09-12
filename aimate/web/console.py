"""AIMate 浏览器管控台（信创首发 · 纯 stdlib，零第三方运行时依赖）。

用标准库 http.server 起一个轻量 Web 管控台，前端为单 HTML + 原生 JS，
后端复用 System（数字员工 / RAG / 记忆 / 审计 / 内网 LLM 网关），
让本地/内网部署无需任何 Node/前端脚手架即可操作数字员工。

端点：
-  GET  /                单页管控台 UI
-  GET  /api/info        平台与网关概览（版本、后端、默认模型、代理数、技能数）
-  GET  /api/agents      数字员工列表
-  POST /api/chat        调度数字员工（复用 System.llm 内网网关）
-  POST /api/kb/search   知识库检索（加权融合）
-  GET  /api/audit       审计日志
-  GET  /api/memory      记忆快照（按 agent）
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from aimate.agents.core import get as get_agent
from aimate.gateway.api.api import ChatRequest
from aimate.llm.gateway import LLMError

_PAGE = """<!DOCTYPE html><html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIMate 管控台</title>
<style>
:root{--bg:#0f1420;--panel:#171d2e;--line:#253051;--fg:#e6ebf5;--mut:#8a95ad;
--acc:#4f8cff;--ok:#34c98a;--warn:#f5b84b;--err:#ff5c5c}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{display:flex;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--line);
background:linear-gradient(90deg,#171d2e,#1b2440)}
header h1{font-size:17px;letter-spacing:.5px}
header .sub{color:var(--mut);font-size:12px}
main{display:grid;grid-template-columns:300px 1fr 340px;gap:14px;padding:16px}
.col{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;overflow:auto}
h2{font-size:13px;color:var(--acc);margin-bottom:10px;letter-spacing:.5px}
.stat{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed var(--line)}
.stat:last-child{border:0}
.stat b{color:var(--fg)}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px}
.badge.ok{background:#123124;color:var(--ok)} .badge.down{background:#3a1b1b;color:var(--err)}
.agent{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 10px;
border:1px solid var(--line);border-radius:8px;margin-bottom:8px;cursor:pointer}
.agent.active{border-color:var(--acc);background:#1c2440}
.agent .nm{font-weight:600} .agent .id{color:var(--mut);font-size:11px}
#chatbox{display:flex;flex-direction:column;height:calc(100vh - 120px)}
#log{flex:1;overflow:auto;padding:6px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:85%;padding:9px 12px;border-radius:10px;white-space:pre-wrap;word-break:break-word}
.msg.u{align-self:flex-end;background:#24406e}.msg.a{align-self:flex-start;background:#1f2740}
.msg .who{font-size:11px;color:var(--mut);margin-bottom:3px}
#inputrow{display:flex;gap:8px;margin-top:12px}
#text{flex:1;background:#0f1420;border:1px solid var(--line);color:var(--fg);
border-radius:8px;padding:10px 12px;outline:none}
button{background:var(--acc);border:0;color:#fff;border-radius:8px;padding:10px 18px;
cursor:pointer;font-weight:600}
button:disabled{opacity:.5;cursor:default}
.small{font-size:12px;color:var(--mut)}
.err{color:var(--err)} .ok{color:var(--ok)}
#audit{font-family:ui-monospace,Menlo,monospace;font-size:11px}
.kv{display:flex;gap:6px;padding:3px 0;border-bottom:1px dashed var(--line);font-size:12px}
.kv .k{color:var(--mut);min-width:60px}
textarea{width:100%;height:60px;background:#0f1420;border:1px solid var(--line);color:var(--fg);
border-radius:8px;padding:8px;resize:vertical;font-family:inherit}
</style></head><body>
<header><h1>🛠 AIMate 管控台</h1><span class="sub" id="sub">信创 · 数据不出域</span></header>
<main>
  <div class="col">
    <h2>平台状态</h2>
    <div id="stats"></div>
    <h2 style="margin-top:16px">数字员工</h2>
    <div id="agents"></div>
  </div>
  <div class="col" id="chatbox">
    <h2>对话（<span id="curagent">—</span>）</h2>
    <div id="log"></div>
    <div id="inputrow"><input id="text" placeholder="输入指令…（Enter 发送）"
      autocomplete="off"><button id="send">发送</button></div>
  </div>
  <div class="col">
    <h2>知识库检索</h2>
    <div id="inputrow"><input id="kbq" placeholder="RAG 查询…" autocomplete="off"
      style="flex:1;background:#0f1420;border:1px solid var(--line);color:var(--fg);
      border-radius:8px;padding:8px 10px;outline:none"><button id="kbbtn">检索</button></div>
    <div id="kbout" style="margin-top:10px"></div>
    <h2 style="margin-top:16px">审计日志</h2>
    <div id="audit"></div>
  </div>
</main>
<script>
let agents=[],cur=null,backends=null;
const $=s=>document.querySelector(s);
function esc(s){const d=document.createElement('div');d.textContent=s??'';return d.innerHTML;}
function status(b){return b?'<span class="badge ok">在线</span>':'<span class="badge down">未连接</span>';}
function log(role,who,txt,extra=''){
  const m=document.createElement('div');m.className='msg '+role;
  m.innerHTML='<div class="who">'+esc(who)+'</div><div>'+esc(txt)+'</div>'+(extra||'');
  $('#log').appendChild(m);$('#log').scrollTop=$('#log').scrollHeight;
}
async function loadInfo(){
  const r=await (await fetch('/api/info')).json();
  backends=r.backends;
  let h='<div class="stat"><span>后端数</span><b>'+backends.length+'</b></div>';
  h+='<div class="stat"><span>默认模型</span><b>'+esc(r.default_model||'—')+'</b></div>';
  h+='<div class="stat"><span>数字员工</span><b>'+r.agents+'</b></div>';
  h+='<div class="stat"><span>技能库</span><b>'+r.skills+'</b></div>';
  h+='<div class="stat"><span>审计条数</span><b>'+r.audit+'</b></div>';
  h+='<div class="stat"><span>请输入令牌</span><b>'+r.tokens+'</b></div>';
  $('#stats').innerHTML=h;
  for(const b of backends) log('a','[后端] '+b.alias,'『'+(b.base_url)+'』 '+(b.model||''),status(true));
}
async function loadAgents(){
  const r=await (await fetch('/api/agents')).json();
  agents=r.agents;
  $('#agents').innerHTML=agents.map(a=>'<div class="agent" data-id="'+a.id+'">'+
    '<div><div class="nm">'+esc(a.name)+'</div><div class="id">'+esc(a.id)+'</div></div>'+
    '<div class="small">'+esc(a.model||'inner')+'</div></div>').join('');
  document.querySelectorAll('.agent').forEach(el=>el.onclick=()=>select(el.dataset.id));
  select(agents[0]?.id);
}
function select(id){
  cur=agents.find(a=>a.id===id);
  document.querySelectorAll('.agent').forEach(a=>a.classList.toggle('active',a.dataset.id===id));
  $('#curagent').textContent=cur?cur.name:'—';
}
async function send(){
  const t=$('#text').value;if(!t||!cur)return;
  $('#text').value='';log('u','我',t);
  $('#send').disabled=true;
  try{
    const r=await (await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({agent_id:cur.id,messages:[{role:'user',content:t}]})})).json();
    if(r.error)log('a','[错误] '+esc(r.model||''),r.error,'<div class="err">⚠ 网关未连上或模型名不匹配</div>');
    else log('a',cur.name+' · '+esc(r.model),r.reply||r.echo?.content||'');
  }catch(e){log('a','[异常]',String(e));}
  $('#send').disabled=false;
}
async function kb(){
  const q=$('#kbq').value;if(!q)return;
  const r=await (await fetch('/api/kb/search',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({q})})).json();
  $('#kbout').innerHTML=(r.hits||[]).map(h=>
    '<div class="kv"><div class="k">'+esc(h.kind||'doc')+'</div><div>'+esc(h.text.slice(0,160))+'…</div></div>'
    ).join('')||'<div class="small">无命中</div>';
}
async function audit(){
  const r=await (await fetch('/api/audit')).json();
  $('#audit').innerHTML=(r.events||[]).slice(0,40).map(e=>
    '<div>'+(e.time?.slice(11)||'')+' <b>'+esc(e.action)+'</b> '+esc(e.detail||'')+'</div>').join('');
}
$('#send').onclick=send;$('#text').onkeydown=e=>{if(e.key==='Enter')send()};
$('#kbbtn').onclick=kb;$('#kbq').onkeydown=e=>{if(e.key==='Enter')kb()};
loadInfo();loadAgents();audit();setInterval(audit,3000);
</script></body></html>"""


class ConsoleHandler(BaseHTTPRequestHandler):
    system: Any = None          # 装配好的 System（类级注入）
    agent_ids: list[str] = []   # 管控台可见的数字员工 id

    # ---- 工具 ----
    def _send(self, code: int, obj: Any, ctype: str = "application/json; charset=utf-8") -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8") if not isinstance(obj, str) \
            else obj.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        ln = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(ln) if ln else b"{}"
        try:
            d = json.loads(raw.decode("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    # ---- 路由 ----
    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("", "/"):
            self._send(200, _PAGE, "text/html; charset=utf-8")
        elif path == "/api/info":
            self._info()
        elif path == "/api/agents":
            self._agents()
        elif path == "/api/audit":
            self._audit()
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/chat":
            self._chat()
        elif path == "/api/kb/search":
            self._kb()
        else:
            self._send(404, {"error": "not found"})

    # ---- 端点实现 ----
    def _info(self) -> None:
        s = self.system
        backends = []
        llm = getattr(s, "llm", None)
        if llm is not None:
            for alias, b in (llm._backends or {}).items():
                backends.append({"alias": alias, "base_url": b.config.base_url,
                                 "model": b.config.model})
        skills = 0
        try:
            skills = len(s.skills.index_of("tenant-demo"))
        except Exception:  # noqa: BLE001
            pass
        self._send(200, {
            "backends": backends,
            "default_model": getattr(s, "llm_default", None),
            "agents": len(self.agent_ids),
            "skills": skills,
            "audit": len(s.audit.query("tenant-demo")),
            "tokens": llm.estimate_tokens("aimate console") if llm is not None else 0,
        })

    def _agents(self) -> None:
        out = []
        for aid in self.agent_ids:
            a = get_agent(aid, "tenant-demo")
            if a:
                out.append({"id": a.id, "name": a.name, "model": a.model,
                            "soul": bool(a.soul_md)})
        self._send(200, {"agents": out})

    def _chat(self) -> None:
        body = self._body()
        agent_id = body.get("agent_id") or (self.agent_ids[0] if self.agent_ids else "")
        tenant = "tenant-demo"
        api = self.system.api   # System 上挂好的 GatewayAPI
        tenant = "tenant-demo"
        key = api.auth.issue_api_key(tenant, "admin")
        principal = api.auth.authenticate_api_key(key)
        try:
            out = api.dispatch(principal, ChatRequest(
                agent_id=agent_id, tenant_id=tenant, messages=body.get("messages", [])))
            self._send(200, out)
        except LookupError as e:
            self._send(404, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _kb(self) -> None:
        body = self._body()
        q = body.get("q", "")
        try:
            hits = self.system.search_kb(q)[:5]
            self._send(200, {"hits": [{"text": h.text, "kind": h.kind,
                                       "score": round(h.score, 3) if hasattr(h, "score") else None}
                                      for h in hits]})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def _audit(self) -> None:
        try:
            events = [{"time": getattr(e, "ts", ""), "action": getattr(e, "action", ""),
                       "actor": getattr(e, "actor", ""), "detail": getattr(e, "detail", "")}
                      for e in self.system.audit.query("tenant-demo")]
            self._send(200, {"events": events[::-1]})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # 静音访问日志，避免刷屏；异常仍打 stderr
        pass


def serve(host: str = "127.0.0.1", port: int = 8900, system: Any = None,
          agent_ids: list[str] | None = None) -> ThreadingHTTPServer:
    """起管控台 HTTP 服务，返回 server（调用方决定是否阻塞 serve_forever）。"""
    ConsoleHandler.system = system
    ConsoleHandler.agent_ids = agent_ids or []
    srv = ThreadingHTTPServer((host, port), ConsoleHandler)
    return srv
