"""AIMate 浏览器管控台（信创首发 · 纯 stdlib，零第三方运行时依赖）。

用标准库 http.server 起一个轻量 Web 管控台，前端为单 HTML + 原生 JS，
后端复用 System（数字员工 / RAG / 记忆 / 审计 / 内网 LLM 网关 / 技能 / MCP），
让本地/内网部署无需任何 Node/前端脚手架即可操作数字员工。

界面风格参考 Hermes agent desktop：左侧导航 rail + 顶部栏 + 面板卡片，
深色主题、圆角卡片、克制强调色（借鉴设计思想，非照搬代码）。

端点：
-  GET  /                   单页管控台 UI
-  GET  /api/info          平台与网关概览
-  GET  /api/agents        数字员工列表
-  POST /api/chat          调度数字员工
-  GET  /api/audit         审计日志
-  GET  /api/memory        记忆快照
-  知识库: GET  /api/kb/docs · POST /api/kb/index · POST /api/kb/search · POST /api/kb/clear
-  大模型: GET  /api/llm · POST /api/llm · POST /api/llm/test
-  技能库: GET  /api/skills · POST /api/skills · POST /api/skills/status
-  MCP:    GET  /api/mcp · POST /api/mcp · POST /api/mcp/call · POST /api/mcp/remove
"""
from __future__ import annotations

import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from aimate.agents.core import get as get_agent
from aimate.gateway.api.api import ChatRequest
from aimate.llm.gateway import LLMError
from aimate.skills.store import SkillStatus

_CSS = """
:root{--bg:#0b0e17;--bg2:#11151f;--panel:#141a28;--panel2:#1a2134;--line:#232b3f;
--fg:#e8edf7;--mut:#7c89a8;--acc:#5b8cff;--acc2:#7aa2ff;--ok:#3ecf8e;--warn:#f5b84b;--err:#ff6b6b}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;height:100vh;overflow:hidden}
/* 左侧导航 rail（借鉴 Hermes desktop 的 profile rail 布局） */
nav{width:64px;background:var(--bg2);border-right:1px solid var(--line);display:flex;flex-direction:column;align-items:center;padding:14px 0;gap:4px;flex-shrink:0}
nav .logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#5b8cff,#7a5bff);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:15px;margin-bottom:12px}
nav button{width:44px;height:44px;border:0;background:transparent;color:var(--mut);border-radius:10px;cursor:pointer;font-size:19px;display:flex;align-items:center;justify-content:center}
nav button:hover{background:var(--panel);color:var(--fg)}
nav button.on{background:var(--panel2);color:var(--acc)}
nav .bottom{margin-top:auto}
nav .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);margin-bottom:4px}
/* 主区 */
main{flex:1;display:flex;flex-direction:column;overflow:hidden}
header{display:flex;align-items:center;gap:14px;padding:12px 22px;border-bottom:1px solid var(--line);background:var(--bg2)}
header h1{font-size:16px;letter-spacing:.4px}
header .crumb{color:var(--mut);font-size:12px}
header .spacer{flex:1}
.chip{font-size:11px;padding:2px 10px;border-radius:12px;border:1px solid var(--line);color:var(--mut)}
.chip.ok{color:var(--ok);border-color:#1d3a2f;background:#0f241c}
.chip.warn{color:var(--warn);border-color:#3a2f1d;background:#241f0f}
.page{flex:1;overflow:auto;padding:20px 24px;display:none}
.page.on{display:block}
h2{font-size:14px;margin-bottom:4px}
.pgsub{color:var(--mut);font-size:12px;margin-bottom:16px}
.bar{display:flex;gap:10px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
.card h3{font-size:13px;color:var(--acc2);margin-bottom:10px}
.row{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px dashed var(--line);flex-wrap:wrap}
.row:last-child{border:0}
.row .nm{font-weight:600;flex:1}
.row .id{color:var(--mut);font-size:11px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
input,textarea{background:var(--bg);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:9px 12px;outline:none;font-family:inherit;font-size:13px}
input:focus,textarea:focus{border-color:var(--acc)}
textarea{resize:vertical}
input[type=text],input:not([type]){min-width:180px;flex:1}
button{background:var(--acc);border:0;color:#fff;border-radius:8px;padding:8px 14px;cursor:pointer;font-weight:600;font-size:13px}
button:disabled{opacity:.45;cursor:default}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--fg)}
button.danger{background:#3a1620;color:var(--err);border:1px solid #5c2233}
button.mini{padding:4px 10px;font-size:12px}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.badge{display:inline-block;padding:1px 9px;border-radius:11px;font-size:11px}
.badge.ok{background:#0f241c;color:var(--ok)}.badge.down{background:#301820;color:var(--err)}
.badge.warn{background:#241f0f;color:var(--warn)}.badge.dim{background:var(--panel2);color:var(--mut)}
.ok{color:var(--ok)}.err{color:var(--err)}.mut{color:var(--mut)}.small{font-size:12px;color:var(--mut)}
.kv{display:flex;gap:8px;padding:4px 0;font-size:12px}
.kv .k{color:var(--mut);min-width:74px;flex-shrink:0}
.agent{display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid var(--line);border-radius:10px;margin-bottom:8px;cursor:pointer;background:var(--bg2)}
.agent.active{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc) inset}
.agent .avatar{width:36px;height:36px;border-radius:9px;background:var(--panel2);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
#chatbox{display:flex;flex-direction:column;height:calc(100vh - 60px)}
#log{flex:1;overflow:auto;padding:6px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:82%;padding:10px 14px;border-radius:12px;white-space:pre-wrap;word-break:break-word;line-height:1.55}
.msg.u{align-self:flex-end;background:#24365c;border-bottom-right-radius:4px}
.msg.a{align-self:flex-start;background:var(--panel2);border-bottom-left-radius:4px}
.msg .who{font-size:11px;color:var(--mut);margin-bottom:4px}
#inputrow{display:flex;gap:8px;margin-top:12px}
#audit{font-family:ui-monospace,Menlo,monospace;font-size:11px}
.stat{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line)}
.stat:last-child{border:0}.stat b{color:var(--fg)}
code.inline{background:var(--panel2);padding:1px 6px;border-radius:5px;font-size:12px}
"""

_JS = r"""
let cur=null;
const $=s=>document.querySelector(s);
function esc(s){const d=document.createElement('div');d.textContent=s??'';return d.innerHTML;}
function badge(b){return b?'<span class="badge ok">在线</span>':'<span class="badge down">离线</span>';}
function toast(m){const e=document.createElement('div');e.textContent=m;e.style.cssText='position:fixed;bottom:20px;right:20px;background:#1a2134;border:1px solid var(--acc);padding:10px 18px;border-radius:10px;z-index:99';document.body.appendChild(e);setTimeout(()=>e.remove(),2500);}
async function jf(url,body){const o={headers:{'Content-Type':'application/json'}};if(body)o.method='POST',o.body=JSON.stringify(body);const r=await fetch(url,o);let d={};try{d=await r.json()}catch(e){}if(!r.ok)throw new Error(d.error||('请求失败 '+r.status));return d;}
function nav(){document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on'));b.classList.add('on');document.querySelectorAll('.page').forEach(p=>p.classList.remove('on'));const pg=document.getElementById(b.dataset.page+'page');if(pg)pg.classList.add('on');if(b.dataset.page==='chat')loadChat();if(b.dataset.page==='kb')loadKb();if(b.dataset.page==='llm')loadLlm();if(b.dataset.page==='skills')loadSkills();if(b.dataset.page==='mcp')loadMcp();if(b.dataset.page==='audit')loadAudit();});}
/* ---------- 对话 ---------- */
async function loadChat(){
  const r=await jf('/api/agents');cur=r.agents[0];
  const box=document.getElementById('chat');box.innerHTML='';
  const r2=await jf('/api/info');
  document.getElementById('crumb').textContent='对话';
  const hl='<div class="aid"></div>';
  box.innerHTML='<div class="card" style="padding:8px 12px"><b id="curagent">'+esc(cur?.name||'IT 支持专家')+'</b> <span class="mut small">'+esc(cur?.id||'')+'</span><span class="chip ok" style="margin-left:10px">● 内网网关</span></div>'+'<div id="log"></div><div id="inputrow"><input id="text" placeholder="输入指令…（Enter 发送）" autocomplete="off"><button id="send">发送</button></div>';
  document.getElementById('send').onclick=send;
  document.getElementById('text').onkeydown=e=>{if(e.key==='Enter')send()};
  const ii=await jf('/api/info');(ii.backends||[]).forEach(b=>log('a','[后端] '+b.alias,'『'+b.base_url+'』 '+(b.model||'')));
}
function log(role,who,txt,extra=''){const m=document.createElement('div');m.className='msg '+role;m.innerHTML='<div class="who">'+esc(who)+'</div><div>'+esc(txt)+'</div>'+(extra||'');const l=document.getElementById('log');if(!l)return;l.appendChild(m);l.scrollTop=l.scrollHeight;}
async function send(){
  const t=document.getElementById('text').value;if(!t||!cur)return;
  document.getElementById('text').value='';log('u','我',t);document.getElementById('send').disabled=true;
  try{const r=await jf('/api/chat',{agent_id:cur.id,messages:[{role:'user',content:t}]});
    if(r.error)log('a','[错误]',r.error);
    else log('a',cur.name,r.reply||r.echo?.content||'');}
  catch(e){log('a','[异常]',String(e));}
  document.getElementById('send').disabled=false;
}
/* ---------- 知识库 ---------- */
async function loadKb(){document.getElementById('crumb').textContent='知识库';
  let h='<div class="card"><h3>录入文档</h3><div class="row"><input type="text" id="kb-id" placeholder="doc_id（如 doc-xxx）"><input type="text" id="kb-kind" placeholder="类型（doc/memory/rules…）" value="doc" style="max-width:120px"></div><textarea id="kb-text" placeholder="粘贴文档内容…"></textarea><div class="bar" style="margin-top:10px"><button id="kb-add">索引入库</button><button class="ghost danger" id="kb-clear">清空知识库</button></div></div>';
  h+='<div class="card"><h3>检索</h3><div class="row"><input type="text" id="kb-q" placeholder="RAG 查询…"><button id="kb-go">检索</button></div><div id="kb-out" style="margin-top:8px"></div></div>';
  h+='<h2>已索引文档</h2><div class="pgsub" id="kb-count"></div><div id="kb-docs"></div>';
  $('#kbpage').innerHTML=h;
  $('#kb-add').onclick=async()=>{try{const r=await jf('/api/kb/index',{doc_id:$('#kb-id').value,text:$('#kb-text').value,kind:$('#kb-kind').value});toast('已索引 '+r.chunks+' 个分块');loadKb();}catch(e){alert(e.message)}};
  document.getElementById('kb-clear').onclick=async()=>{if(!confirm('清空整个知识库？'))return;await jf('/api/kb/clear',{});toast('已清空');loadKb();};
  $('#kb-go').onclick=async()=>{const q=$('#kb-q').value;if(!q)return;const r=await jf('/api/kb/search',{q});$('#kb-out').innerHTML=(r.hits||[]).map(h=>'<div class="kv"><span class="k badge dim">'+esc(h.kind||'doc')+'</span><span>'+esc(h.text.slice(0,200))+'…</span><span class="small mut">'+h.score+'</span></div>').join('')||'<div class="small mut">无命中</div>';};
  const r=await jf('/api/kb/docs');
  document.getElementById('kb-count').textContent=r.docs.length+' 个文档 · '+r.chunks+' 个分块';
  document.getElementById('kb-docs').innerHTML=r.docs.map(d=>'<div class="row"><span class="nm mono">'+esc(d.doc_id)+'</span><span class="badge dim">'+esc(d.kind)+'</span><span class="small mut">'+d.chunks+' 块</span><span class="small mut">'+esc(d.sample.slice(0,40))+'…</span></div>').join('')||'<div class="small mut">暂无文档</div>';
}
/* ---------- 大模型配置 ---------- */
async function loadLlm(){document.getElementById('crumb').textContent='大模型配置';
  let h='<div class="card"><h3>添加内网模型后端</h3><div class="row"><input type="text" id="llm-name" placeholder="后端名（如 inner-gateway）"><input type="text" id="llm-url" placeholder="base_url（如 http://127.0.0.1:8080）"></div><div class="row"><input type="text" id="llm-model" placeholder="模型名（须与 /v1/models 一致）"><input type="text" id="llm-key" placeholder="api_key（可空）" style="max-width:200px"></div><div class="bar" style="margin-top:10px"><button id="llm-add">注册后端</button><button class="ghost" id="llm-test">测试连通性</button></div></div>';
  h+='<h2>已配置后端</h2><div id="llm-list"></div>';
  $('#llmpage').innerHTML=h;
  $('#llm-add').onclick=async()=>{try{const r=await jf('/api/llm',{name:$('#llm-name').value,base_url:$('#llm-url').value,model:$('#llm-model').value||'default',api_key:$('#llm-key').value||''});toast('已注册 '+r.name);loadLlm();}catch(e){alert(e.message)}};
  document.getElementById('llm-test').onclick=async()=>{try{const r=await jf('/api/llm/test',{});alert(r.result?('连通 OK: '+r.message):('未配置后端,使用 gateway:test'));}catch(e){alert('测试失败: '+e.message)}};
  const r=await jf('/api/llm');
  document.getElementById('llm-list').innerHTML=(r.backends||[]).map(b=>'<div class="row"><span class="nm">'+esc(b.alias)+'</span><code class="inline">'+esc(b.base_url)+'</code><span class="small mut">'+esc(b.model)+'</span>'+badge(b.ready)+'</div>').join('')||'<div class="small mut">暂无后端 — 添加或使用 gateway:test 验证现有配置</div>';
}
/* ---------- 技能库 ---------- */
async function loadSkills(){document.getElementById('crumb').textContent='技能库';
  let h='<div class="card"><h3>创建技能</h3><div class="row"><input type="text" id="sk-name" placeholder="名称（如 knowledge_base）"><input type="text" id="sk-desc" placeholder="描述"></div><div class="row"><input type="text" id="sk-trigger" placeholder="触发条件"><select id="sk-status" style="background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px"><option value="published">发布</option><option value="draft">草稿</option></select></div><div class="bar" style="margin-top:10px"><button id="sk-add">创建</button></div></div>';
  h+='<h2>技能条目</h2><div id="sk-list"></div>';
  $('#skillspage').innerHTML=h;
  $('#sk-add').onclick=async()=>{try{const r=await jf('/api/skills',{name:$('#sk-name').value,description:$('#sk-desc').value,trigger:$('#sk-trigger').value,status:$('#sk-status').value});toast('已创建 '+r.name);loadSkills();}catch(e){alert(e.message)}};
  const r=await jf('/api/skills');
  document.getElementById('sk-list').innerHTML=(r.skills||[]).map(s=>'<div class="row"><span class="nm">'+esc(s.name)+'</span><span class="small mut">'+esc(s.description)+'</span><span class="badge '+(s.status==='published'?'ok':'warn')+'">'+esc(s.status)+'</span><button class="mini ghost" data-n="'+esc(s.name)+'" data-s="'+ (s.status==='published'?'draft':'published') +'">切换</button></div>').join('')||'<div class="small mut">暂无技能</div>';
  document.querySelectorAll('#sk-list button').forEach(b=>b.onclick=async()=>{await jf('/api/skills/status',{name:b.dataset.n,status:b.dataset.s});loadSkills();});
}
/* ---------- MCP 工具库 ---------- */
async function loadMcp(){document.getElementById('crumb').textContent='MCP 工具库';
  let h='<div class="card"><h3>接入 MCP Server（stdio）</h3><div class="row"><input type="text" id="mcp-name" placeholder="server 名（如 demo）"><input type="text" id="mcp-cmd" placeholder="启动命令，空格分隔（如 python3 -m aimate.mcp.demo）"></div><div class="bar" style="margin-top:10px"><button id="mcp-add">连接</button></div><div class="small mut" style="margin-top:6px">工具经 <code class="inline">server__tool</code> 注册进数字员工工具集，可被模型调用。</div></div>';
  h+='<h2>已连接工具</h2><div id="mcp-list"></div>';
  $('#mcppage').innerHTML=h;
  $('#mcp-add').onclick=async()=>{try{const r=await jf('/api/mcp',{name:$('#mcp-name').value,cmd:$('#mcp-cmd').value.split(/\s+/)});toast('已连接 '+r.name+' · '+r.tools.length+' 工具');loadMcp();}catch(e){alert('连接失败: '+e.message)}};
  const r=await jf('/api/mcp');
  document.getElementById('mcp-list').innerHTML=(r.servers||[]).map(s=>'<div class="card"><h3>'+esc(s.name)+' '+badge(s.ready)+'</h3><div class="small mut mono">'+esc(s.cmd.join(' '))+'</div>'+(s.tools||[]).map(t=>'<div class="row"><button class="mini" data-t="'+esc(t)+'">调用</button><code class="inline">'+esc(t)+'</code></div>').join('')+'<div class="bar" style="margin-top:8px"><button class="mini danger" data-rm="'+esc(s.name)+'">移除</button></div></div>').join('')||'<div class="small mut">未连接 MCP server</div>';
  document.querySelectorAll('#mcp-list [data-t]').forEach(b=>b.onclick=async()=>{const a=prompt('JSON 参数:');if(a==null)return;try{const r=await jf('/api/mcp/call',{tool:b.dataset.t,args:JSON.parse(a||'{}')});alert(typeof r.result==='string'?r.result:JSON.stringify(r.result));}catch(e){alert(e.message)}});
  document.querySelectorAll('#mcp-list [data-rm]').forEach(b=>b.onclick=async()=>{await jf('/api/mcp/remove',{name:b.dataset.rm});toast('已移除');loadMcp();});
}
/* ---------- 审计 ---------- */
async function loadAudit(){document.getElementById('crumb').textContent='审计日志';
  $('#auditpage').innerHTML='<div id="audit"></div>';
  const r=await jf('/api/audit');
  document.getElementById('audit').innerHTML='<div class="card">'+(r.events||[]).slice(0,100).map(e=>'<div class="kv"><span class="k">'+(e.time?.slice(11,19)||'')+'</span><b>'+esc(e.action)+'</b><span class="mut">'+esc(e.actor||'')+'</span><span>'+esc(e.detail||'')+'</span></div>').join('')+'</div>'+'<div class="small mut">共 '+r.events.length+' 条</div>';
}
nav();loadChat();
"""

_PAGE = """<!DOCTYPE html><html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIMate 管控台</title><style>__CSS__</style></head>
<body>
<nav>
  <div class="logo">Ai</div>
  <button data-page="chat" class="on" title="对话">💬</button>
  <button data-page="kb" title="知识库">📚</button>
  <button data-page="llm" title="大模型配置">🧠</button>
  <button data-page="skills" title="技能库">🧩</button>
  <button data-page="mcp" title="MCP 工具库">🔌</button>
  <div class="bottom"><div class="dot"></div><button data-page="audit" title="审计">🛡</button></div>
</nav>
<main>
  <header><h1>AIMate</h1><span class="crumb" id="crumb">对话</span><div class="spacer"></div>
    <span class="chip ok" id="hdr-bk">内网</span><span class="chip" id="hdr-model">—</span></header>
  <div class="page on" id="chatpage"><div class="card" id="chat"></div></div>
  <div class="page" id="kbpage"></div>
  <div class="page" id="llmpage"></div>
  <div class="page" id="skillspage"></div>
  <div class="page" id="mcppage"></div>
  <div class="page" id="auditpage"></div>
</main>
<script>__JS__</script>
</body></html>"""


class ConsoleHandler(BaseHTTPRequestHandler):
    system: Any = None          # 装配好的 System（类级注入）
    agent_ids: list[str] = []   # 管控台可见的数字员工 id

    # ---- 工具 ----
    def _send(self, code: int, obj: Any, ctype: str = "application/json; charset=utf-8") -> None:
        if isinstance(obj, str):
            body = obj.encode("utf-8")
        else:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
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
            page = _PAGE.replace("__CSS__", _CSS).replace("__JS__", _JS)
            self._send(200, page, "text/html; charset=utf-8")
        elif path == "/api/info":
            self._info()
        elif path == "/api/agents":
            self._agents()
        elif path == "/api/audit":
            self._audit()
        elif path == "/api/kb/docs":
            self._kb_docs()
        elif path == "/api/llm":
            self._llm_list()
        elif path == "/api/skills":
            self._skills_list()
        elif path == "/api/mcp":
            self._mcp_list()
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/chat":
            self._chat()
        elif path == "/api/kb/search":
            self._kb()
        elif path == "/api/kb/index":
            self._kb_index()
        elif path == "/api/kb/clear":
            self._kb_clear()
        elif path == "/api/llm":
            self._llm_add()
        elif path == "/api/llm/test":
            self._llm_test()
        elif path == "/api/skills":
            self._skills_add()
        elif path == "/api/skills/status":
            self._skills_status()
        elif path == "/api/mcp":
            self._mcp_add()
        elif path == "/api/mcp/call":
            self._mcp_call()
        elif path == "/api/mcp/remove":
            self._mcp_remove()
        else:
            self._send(404, {"error": "not found"})

    # ---- 端点实现 ----
    def _info(self) -> None:
        s = self.system
        backends = self._llm_backends()
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
            "tokens": s.llm.estimate_tokens("aimate console") if s.llm is not None else 0,
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
        api = self.system.api
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
                                       "score": round(h.score, 3)} for h in hits]})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def _kb_docs(self) -> None:
        docs = self.system.list_kb_docs()
        chunks = len(self.system.rag.bm25.docs)
        self._send(200, {"docs": docs, "chunks": chunks})

    def _kb_index(self) -> None:
        body = self._body()
        doc_id = (body.get("doc_id") or "").strip()
        text = (body.get("text") or "").strip()
        if not doc_id or not text:
            self._send(400, {"error": "doc_id 与 text 必填"})
            return
        n = self.system.add_kb_doc(doc_id, text, body.get("kind", "doc"))
        self.system.audit.record("console", "tenant-demo", "kb.index", f"{doc_id}/{n}块")
        self._send(200, {"doc_id": doc_id, "chunks": n})

    def _kb_clear(self) -> None:
        n = self.system.clear_kb()
        self.system.audit.record("console", "tenant-demo", "kb.clear", f"清除{n}块")
        self._send(200, {"cleared": n})

    def _llm_list(self) -> None:
        self._send(200, {"backends": self._llm_backends(),
                         "default": getattr(self.system, "llm_default", None)})

    def _llm_backends(self) -> list[dict]:
        s = self.system
        backends: list[dict] = []
        names = set()
        for alias, b in (s.llm._backends or {}).items():
            backends.append({"alias": alias, "base_url": b.config.base_url,
                             "model": b.config.model, "ready": True})
            names.add(alias)
        for alias in (s.llm._aliases or {}):
            if alias not in names:
                backends.append({"alias": alias, "base_url": "", "model": "",
                                 "ready": True, "is_alias": True})
        return backends

    def _llm_add(self) -> None:
        body = self._body()
        name = (body.get("name") or "").strip()
        base_url = (body.get("base_url") or "").strip()
        if not name or not base_url:
            self._send(400, {"error": "name 与 base_url 必填"})
            return
        cfg = {"base_url": base_url, "model": body.get("model") or "default",
               "api_key": body.get("api_key", ""), "timeout": 300.0}
        try:
            self.system.llm.configure({name: cfg})
            self.system.audit.record("console", "tenant-demo", "llm.add", name)
            self._send(200, {"name": name, **cfg})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def _llm_test(self) -> None:
        s = self.system
        alias = s.llm_default
        backends = list((s.llm._backends or {}).keys())
        if not backends:
            self._send(200, {"result": False, "message": "未配置后端，请先注册或使用 gateway:test"})
            return
        try:
            resp = s.llm.chat(alias, [{"role": "user", "content": "ping"}])
            # 统一取模型名
            model = resp.get("model", alias)
            try:
                msg = resp["choices"][0]["message"]["content"]
            except Exception:  # noqa: BLE001
                msg = ""
            msg = (msg or "").strip()[:80]
            self._send(200, {"result": True, "message": f"模型 {model} OK：{msg or '(空)'}",
                             "model": model})
        except Exception as e:  # noqa: BLE001
            self._send(200, {"result": False, "message": f"{type(e).__name__}: {e}"},
                       ctype="application/json; charset=utf-8")

    def _skills_list(self) -> None:
        skills = self.system.skills.list("tenant-demo")
        self._send(200, {"skills": [{"name": s.name, "description": s.description,
                                     "trigger": s.trigger, "status": s.status.value,
                                     "owner": s.owner, "pinned": s.pinned}
                                    for s in skills]})

    def _skills_add(self) -> None:
        body = self._body()
        name = (body.get("name") or "").strip()
        if not name:
            self._send(400, {"error": "name 必填"})
            return
        status = SkillStatus(body.get("status", "published"))
        from aimate.skills.store import Skill
        s = Skill(name=name, tenant_id="tenant-demo",
                  description=body.get("description", ""),
                  trigger=body.get("trigger", ""), body=body.get("body", ""),
                  status=status, owner=body.get("owner", "console"))
        self.system.skills.create(s)
        self.system.audit.record("console", "tenant-demo", "skills.create", name)
        self._send(200, {"name": name, "status": status.value})

    def _skills_status(self) -> None:
        body = self._body()
        name = (body.get("name") or "").strip()
        status = SkillStatus(body.get("status", "published"))
        try:
            self.system.skills.set_status("tenant-demo", name, status)
            self.system.audit.record("console", "tenant-demo", "skills.status",
                                     f"{name}→{status.value}")
            self._send(200, {"name": name, "status": status.value})
        except KeyError:
            self._send(404, {"error": f"技能不存在: {name}"})

    def _mcp_list(self) -> None:
        servers = self.system.mcp.list_servers()
        self._send(200, {"servers": servers, "tool_count": len(self.system.mcp._schemas)})

    def _mcp_add(self) -> None:
        body = self._body()
        name = (body.get("name") or "").strip()
        cmd = body.get("cmd") or []
        if not name or not cmd:
            self._send(400, {"error": "name 与 cmd 必填"})
            return
        try:
            cli = self.system.mcp.add_server(name, list(cmd), timeout=5.0)
            tools = cli.list_tools()
            self.system.audit.record("console", "tenant-demo", "mcp.add",
                                     f"{name}/{len(tools)}工具")
            # 接入数字员工工具集
            try:
                for t in tools:
                    self.system.api.register_tool(
                        {"type": "function",
                         "function": {"name": t["name"],
                                      "description": t.get("description", ""),
                                      "parameters": t.get("inputSchema") or {
                                          "type": "object", "properties": {}}}})
            except Exception:  # noqa: BLE001
                pass  # 工具注册失败不阻塞 server 连接展示
            self._send(200, {"name": name, "tools": [f"{name}__{t['name']}" for t in tools]})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _mcp_call(self) -> None:
        body = self._body()
        tool = body.get("tool", "")
        args = body.get("args") or {}
        try:
            result = self.system.mcp.call_tool(tool, args)
            self.system.audit.record("console", "tenant-demo", "mcp.call", tool)
            self._send(200, {"tool": tool, "result": result})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _mcp_remove(self) -> None:
        body = self._body()
        name = body.get("name", "")
        try:
            self.system.mcp.remove_server(name)
            self.system.audit.record("console", "tenant-demo", "mcp.remove", name)
            self._send(200, {"removed": name})
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
        pass


def serve(host: str = "127.0.0.1", port: int = 8900, system: Any = None,
          agent_ids: list[str] | None = None) -> ThreadingHTTPServer:
    """起管控台 HTTP 服务，返回 server（调用方决定是否阻塞 serve_forever）。"""
    ConsoleHandler.system = system
    ConsoleHandler.agent_ids = agent_ids or []
    srv = ThreadingHTTPServer((host, port), ConsoleHandler)
    return srv
