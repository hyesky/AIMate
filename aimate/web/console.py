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

_CSS = """\
/* ── AIMate console · Hermes-Desktop 设计语言 ──
   提取自 apps/desktop/src/styles.css + DESIGN.md 的真实 token（浅色）:
   - chrome 背景 #f8faff / 侧栏 #f3f7ff / 卡片 #ffffff
   - 唯一强调色 Nous 蓝 #0053fd
   - flat not boxed: 面板不套面板, 用留白 + 单根头发丝线(--stroke-tertiary=前景7%alpha)
   - 悬停/激活用极浅的 accent color-mix, 而非粗边框
   - 字体: SF Pro/Segoe UI 无衬线 + Menlo/Monaco/SF Mono 等宽
   - 克制圆角(radius scalar≈0.2), 输入框靠内阴影+细边, focus 时边框才显色 */
:root{
  --ui-base:#17171a;
  --ui-accent:#0053fd;                    /* Nous 蓝 — 唯一强调色 */
  --ui-warm:#cf806d;
  --ui-red:#cf2d56; --ui-orange:#db704b; --ui-yellow:#c08532;
  --ui-green:#1f8a65; --ui-cyan:#4c7f8c; --ui-purple:#9e94d5;
  /* 语义色板 */
  --ui-text-primary:color-mix(in srgb,var(--ui-base) 94%,transparent);
  --ui-text-secondary:color-mix(in srgb,var(--ui-base) 74%,transparent);
  --ui-text-tertiary:color-mix(in srgb,var(--ui-base) 54%,transparent);
  --ui-text-quaternary:color-mix(in srgb,var(--ui-base) 36%,transparent);
  --ui-stroke-secondary:color-mix(in srgb,var(--ui-base) 7%,transparent);
  --ui-stroke-tertiary:color-mix(in srgb,var(--ui-base) 5%,transparent);
  --ui-stroke-quaternary:color-mix(in srgb,var(--ui-base) 3%,transparent);
  --ui-bg-chrome:#f8faff;
  --ui-bg-sidebar:#f3f7ff;
  --ui-bg-card:#ffffff;
  --ui-row-hover:color-mix(in srgb,var(--ui-accent) 4%,transparent);
  --ui-row-active:color-mix(in srgb,var(--ui-accent) 8%,transparent);
  --ui-control-active:color-mix(in srgb,var(--ui-accent) 8%,transparent);
  --ui-bell:#fefffe;
  --shadow-nous:0 .125rem .25rem -.125rem rgba(0,0,0,.07),0 .5rem .75rem -.375rem rgba(0,0,0,.06),0 1.25rem 1.75rem -.875rem rgba(0,0,0,.06);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--ui-bg-chrome);color:var(--ui-text-primary);
  font:14px/1.6 'Segoe WPC','Segoe UI',-apple-system,BlinkMacSystemFont,'SF Pro Text',system-ui,sans-serif,'PingFang SC','Microsoft YaHei';
  display:flex;height:100vh;overflow:hidden;color-scheme:light}
/* 左侧导航 rail — Hermes profile/session rail 形态: 极窄、浅侧栏、无边框盒子 */
nav{width:60px;background:var(--ui-bg-sidebar);display:flex;flex-direction:column;align-items:center;padding:16px 0 12px;gap:2px;flex-shrink:0;
  border-right:1px solid var(--ui-stroke-tertiary)}
nav .logo{width:34px;height:34px;border-radius:8px;background:#ffffff;border:1px solid var(--ui-stroke-tertiary);
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;color:var(--ui-accent);margin-bottom:14px}
nav button{width:40px;height:40px;border:0;background:transparent;color:var(--ui-text-tertiary);border-radius:8px;cursor:pointer;
  font-size:18px;display:flex;align-items:center;justify-content:center;transition:background .1s,color .1s}
nav button svg{width:18px;height:18px;fill:currentColor;display:block}
nav button:hover{background:var(--ui-row-hover);color:var(--ui-text-primary)}
nav button.on{background:var(--ui-row-active);color:var(--ui-accent)}
nav .bottom{margin-top:auto;display:flex;flex-direction:column;align-items:center;gap:2px}
nav .dot{width:8px;height:8px;border-radius:50%;background:var(--ui-green);box-shadow:0 0 0 3px color-mix(in srgb,var(--ui-green) 18%,transparent);margin-bottom:6px}
/* 主区 */
main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
/* 顶部标题栏 — Hermes titlebar: 平直、无粗边、只一根头发丝 */
header{display:flex;align-items:center;gap:12px;padding:10px 22px;border-bottom:1px solid var(--ui-stroke-tertiary);background:var(--ui-bg-chrome)}
header h1{font-size:15px;letter-spacing:.3px;font-weight:650}
header .crumb{color:var(--ui-text-tertiary);font-size:12px}
header .spacer{flex:1}
.chip{font-size:11px;padding:2px 11px;border-radius:999px;border:1px solid var(--ui-stroke-tertiary);color:var(--ui-text-secondary);background:#fff}
.chip.ok{color:var(--ui-green);border-color:color-mix(in srgb,var(--ui-green) 30%,transparent);background:color-mix(in srgb,var(--ui-green) 6%,#fff)}
.chip.warn{color:var(--ui-orange);border-color:color-mix(in srgb,var(--ui-orange) 30%,transparent);background:color-mix(in srgb,var(--ui-orange) 6%,#fff)}
/* 页面 */
.page{flex:1;overflow:auto;padding:22px 28px;display:none}
.page.on{display:block}
h2{font-size:13px;font-weight:650;color:var(--ui-text-secondary);margin-bottom:4px}
.pgsub{color:var(--ui-text-tertiary);font-size:12px;margin-bottom:16px}
.bar{display:flex;gap:10px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
/* flat not boxed: 面板=白卡片只一根头发丝, 面板内不再套有边框的盒子 */
.card{background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);border-radius:10px;padding:16px 18px;margin-bottom:14px}
.card h3{font-size:13px;font-weight:650;color:var(--ui-accent);margin-bottom:10px}
.row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--ui-stroke-quaternary);flex-wrap:wrap}
.row:last-child{border:0}
.row .nm{font-weight:600;flex:1;color:var(--ui-text-primary)}
.row .id{color:var(--ui-text-tertiary);font-size:11px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
/* 输入控件 — Hermes controlVariants: 透明底、细边、内阴影, focus 边框显色 */
input,textarea,select{background:var(--ui-bg-card);border:1px solid color-mix(in srgb,var(--ui-accent) 7%,transparent);
  color:var(--ui-text-primary);border-radius:6px;padding:8px 11px;outline:none;font-family:inherit;font-size:13px;
  box-shadow:inset 0 1px 1px rgba(0,0,0,.08)}
input:focus,textarea:focus,select:focus{border-color:var(--ui-accent);box-shadow:0 0 0 1px var(--ui-accent) inset}
textarea{resize:vertical}
input[type=text],input:not([type]){min-width:180px;flex:1}
/* 按钮 — 一个 Button 组件, variant 驱动 */
button{background:var(--ui-accent);border:0;color:#fcfcfc;border-radius:6px;padding:7px 14px;cursor:pointer;font-weight:600;font-size:13px;font-family:inherit;transition:filter .1s}
button:hover{filter:brightness(1.08)}
button:disabled{opacity:.45;cursor:default}
button.ghost{background:transparent;border:1px solid var(--ui-stroke-secondary);color:var(--ui-text-primary)}
button.ghost:hover{background:var(--ui-row-hover);filter:none}
button.danger{background:color-mix(in srgb,var(--ui-red) 9%,#fff);color:var(--ui-red);border:1px solid color-mix(in srgb,var(--ui-red) 26%,transparent)}
button.danger:hover{background:color-mix(in srgb,var(--ui-red) 15%,#fff);filter:none}
button.mini{padding:3px 10px;font-size:12px}
.mono{font-family:Menlo,Monaco,'SF Mono',ui-monospace,monospace;font-size:12px}
.badge{display:inline-block;padding:1px 9px;border-radius:999px;font-size:11px;background:color-mix(in srgb,var(--ui-base) 5%,transparent);color:var(--ui-text-secondary)}
.badge.ok{background:color-mix(in srgb,var(--ui-green) 10%,transparent);color:var(--ui-green)}
.badge.down{background:color-mix(in srgb,var(--ui-red) 9%,transparent);color:var(--ui-red)}
.badge.warn{background:color-mix(in srgb,var(--ui-orange) 10%,transparent);color:var(--ui-orange)}
.badge.dim{background:color-mix(in srgb,var(--ui-base) 5%,transparent);color:var(--ui-text-tertiary)}
.ok{color:var(--ui-green)}.err{color:var(--ui-red)}.mut{color:var(--ui-text-tertiary)}.small{font-size:12px;color:var(--ui-text-tertiary)}
.kv{display:flex;gap:8px;padding:4px 0;font-size:12px;align-items:baseline}
.kv .k{color:var(--ui-text-tertiary);min-width:56px;flex-shrink:0}
.agent{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--ui-stroke-tertiary);border-radius:10px;margin-bottom:8px;cursor:pointer;background:#fff}
.agent:hover{background:var(--ui-row-hover)}
.agent.active{border-color:var(--ui-accent);box-shadow:0 0 0 1px var(--ui-accent) inset}
.agent .avatar{width:34px;height:34px;border-radius:8px;background:var(--ui-bg-sidebar);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
#chatbox{display:flex;flex-direction:column;height:calc(100vh - 54px)}
#log{flex:1;overflow:auto;padding:6px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:82%;padding:9px 14px;border-radius:12px;white-space:pre-wrap;word-break:break-word;line-height:1.55}
.msg.u{align-self:flex-end;background:color-mix(in srgb,var(--ui-accent) 66%,#fff);color:#fff;border-bottom-right-radius:4px}
.msg.a{align-self:flex-start;background:color-mix(in srgb,var(--ui-base) 5%,#fff);border:1px solid var(--ui-stroke-quaternary);border-bottom-left-radius:4px}
.msg .who{font-size:11px;color:var(--ui-text-tertiary);margin-bottom:4px}
.msg.u .who{color:rgba(255,255,255,.78)}
#inputrow{display:flex;gap:8px;margin-top:12px}
#audit{font-family:Menlo,Monaco,'SF Mono',ui-monospace,monospace;font-size:11px}
.stat{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--ui-stroke-quaternary)}
.stat:last-child{border:0}.stat b{color:var(--ui-text-primary)}
code.inline{background:color-mix(in srgb,var(--ui-base) 5%,transparent);padding:1px 6px;border-radius:5px;font-size:12px;font-family:Menlo,Monaco,'SF Mono',ui-monospace,monospace}
"""

_JS = r"""
let cur=null;
const $=s=>document.querySelector(s);
function esc(s){const d=document.createElement('div');d.textContent=s??'';return d.innerHTML;}
function badge(b){return b?'<span class="badge ok">在线</span>':'<span class="badge down">离线</span>';}
function toast(m){const e=document.createElement('div');e.textContent=m;e.style.cssText='position:fixed;bottom:20px;right:20px;background:#ffffff;border:1px solid var(--ui-stroke-secondary);box-shadow:var(--shadow-nous);padding:10px 18px;border-radius:10px;z-index:99';document.body.appendChild(e);setTimeout(()=>e.remove(),2500);}
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
  let h='<div class="card"><h3>创建技能</h3><div class="row"><input type="text" id="sk-name" placeholder="名称（如 knowledge_base）"><input type="text" id="sk-desc" placeholder="描述"></div><div class="row"><input type="text" id="sk-trigger" placeholder="触发条件"><select id="sk-status" style="background:var(--ui-bg-card);color:var(--ui-text-primary);border:1px solid color-mix(in srgb,var(--ui-accent) 7%,transparent);border-radius:6px;padding:8px"><option value="published">发布</option><option value="draft">草稿</option></select></div><div class="bar" style="margin-top:10px"><button id="sk-add">创建</button></div></div>';
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
  <button data-page="chat" class="on" title="对话"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M14.56 7.44049C14.28 7.16049 13.9 7.00049 13.5 7.00049H13V4.00049C13 2.90049 12.1 2.00049 11 2.00049H3C1.9 2.00049 1 2.90049 1 4.00049V9.00049C1 10.1005 1.9 11.0005 3 11.0005V12.0005C3 12.8205 3.93 13.2905 4.59 12.8105L7 11.0505V11.5005C7 11.9005 7.16 12.2805 7.44 12.5605C7.72 12.8405 8.1 13.0005 8.5 13.0005H10.29L12.15 14.8505C12.19 14.9005 12.25 14.9405 12.31 14.9605C12.37 14.9905 12.43 15.0005 12.5 15.0005C12.57 15.0005 12.63 14.9905 12.69 14.9605C12.78 14.9205 12.86 14.8605 12.92 14.7805C12.97 14.7005 13 14.6005 13 14.5005V13.0005H13.5C13.9 13.0005 14.28 12.8405 14.56 12.5605C14.84 12.2805 15 11.9005 15 11.5005V8.50049C15 8.10049 14.84 7.72049 14.56 7.44049ZM6.75 10.0005L4 12.0005V10.0005H3C2.45 10.0005 2 9.55049 2 9.00049V4.00049C2 3.45049 2.45 3.00049 3 3.00049H11C11.55 3.00049 12 3.45049 12 4.00049V7.00049H8.5C8.1 7.00049 7.72 7.16049 7.44 7.44049C7.16 7.72049 7 8.10049 7 8.50049V10.0005H6.75ZM14 11.5005C14 11.6305 13.95 11.7605 13.85 11.8505C13.76 11.9505 13.63 12.0005 13.5 12.0005H12.5C12.37 12.0005 12.24 12.0505 12.15 12.1505C12.05 12.2405 12 12.3705 12 12.5005V13.2905L10.85 12.1505C10.81 12.1005 10.75 12.0605 10.69 12.0405C10.63 12.0105 10.57 12.0005 10.5 12.0005H8.5C8.37 12.0005 8.24 11.9505 8.15 11.8505C8.05 11.7605 8 11.6305 8 11.5005V8.50049C8 8.37049 8.05 8.24049 8.15 8.15049C8.24 8.05049 8.37 8.00049 8.5 8.00049H13.5C13.63 8.00049 13.76 8.05049 13.85 8.15049C13.95 8.24049 14 8.37049 14 8.50049V11.5005Z"/></svg></button>
  <button data-page="kb" title="知识库"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1 3.24941C1 2.55938 1.55917 2 2.24895 2H2.74852C3.4383 2 3.99747 2.55938 3.99747 3.24941V12.745C3.99747 13.435 3.4383 13.9944 2.74852 13.9944H2.24895C1.55917 13.9944 1 13.435 1 12.745V3.24941ZM2.24895 2.99953C2.11099 2.99953 1.99916 3.11141 1.99916 3.24941V12.745C1.99916 12.883 2.11099 12.9948 2.24895 12.9948H2.74852C2.88648 12.9948 2.99831 12.883 2.99831 12.745V3.24941C2.99831 3.11141 2.88648 2.99953 2.74852 2.99953H2.24895ZM4.99663 3.24941C4.99663 2.55938 5.5558 2 6.24557 2H6.74515C7.43492 2 7.9941 2.55938 7.9941 3.24941V12.745C7.9941 13.435 7.43492 13.9944 6.74515 13.9944H6.24557C5.5558 13.9944 4.99663 13.435 4.99663 12.745V3.24941ZM6.24557 2.99953C6.10762 2.99953 5.99578 3.11141 5.99578 3.24941V12.745C5.99578 12.883 6.10762 12.9948 6.24557 12.9948H6.74515C6.88311 12.9948 6.99494 12.883 6.99494 12.745V3.24941C6.99494 3.11141 6.88311 2.99953 6.74515 2.99953H6.24557ZM11.9723 4.77682C11.7231 4.15733 11.0311 3.84331 10.4011 4.06385L9.81888 4.26764C9.14658 4.50297 8.80684 5.25222 9.07268 5.91326L12.0098 13.2166C12.2589 13.8361 12.9509 14.1502 13.581 13.9296L14.1632 13.7258C14.8355 13.4904 15.1752 12.7412 14.9093 12.0802L11.9723 4.77682ZM10.7311 5.00729C10.8571 4.96318 10.9955 5.02598 11.0453 5.14988L13.9824 12.4532C14.0356 12.5854 13.9676 12.7353 13.8332 12.7823L13.251 12.9862C13.1249 13.0303 12.9865 12.9675 12.9367 12.8436L9.99964 5.5402C9.94647 5.40799 10.0144 5.25815 10.1489 5.21108L10.7311 5.00729Z"/></svg></button>
  <button data-page="llm" title="大模型配置"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M12 0.998993C12.276 0.998993 12.5 1.22299 12.5 1.49899C12.5 1.77499 12.276 1.99899 12 1.99899H11.004V6.68299C11.004 7.26299 11.148 7.83299 11.423 8.34299L13.819 12.789C14.358 13.788 13.634 15.001 12.499 15.001H3.50101C2.36501 15.001 1.64301 13.788 2.18101 12.789L4.57501 8.34499C4.85001 7.83499 4.99401 7.26399 4.99401 6.68499V1.99899H4.00001C3.72401 1.99899 3.50001 1.77499 3.50001 1.49899C3.50001 1.22299 3.72401 0.998993 4.00001 0.998993H12ZM5.99401 1.99899V6.68599C5.99401 7.43099 5.80901 8.16399 5.45601 8.81999L4.82101 9.99899H11.18L10.543 8.81699C10.19 8.16099 10.005 7.42799 10.005 6.68199V1.99899H5.99401ZM11.718 10.999H4.28201L3.06201 13.263C2.88201 13.597 3.12401 14 3.50201 14H12.499C12.877 14 13.119 13.596 12.939 13.263L11.718 10.999Z"/></svg></button>
  <button data-page="skills" title="技能库"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11.9999 3C10.1399 3 8.56988 4.27 8.12988 6H9.17988C9.58988 4.84 10.6999 4 11.9999 4C13.6499 4 14.9999 5.35 14.9999 7C14.9999 8.3 14.1599 9.41 12.9999 9.82V10.87C14.7299 10.43 15.9999 8.86 15.9999 7C15.9999 4.79 14.2099 3 11.9999 3Z"/><path d="M10.5 15H5.5C4.673 15 4 14.327 4 13.5V8.5C4 7.673 4.673 7 5.5 7H10.5C11.327 7 12 7.673 12 8.5V13.5C12 14.327 11.327 15 10.5 15ZM5.5 8C5.224 8 5 8.225 5 8.5V13.5C5 13.775 5.224 14 5.5 14H10.5C10.776 14 11 13.775 11 13.5V8.5C11 8.225 10.776 8 10.5 8H5.5Z"/><path d="M4.42973 2.25008C4.24973 1.94008 3.74973 1.94008 3.56973 2.25008L0.0997266 8.25008C0.00972656 8.40008 0.00972656 8.60008 0.0997266 8.75008C0.189727 8.90008 0.359727 9.00008 0.539727 9.00008H2.99973V8.50008C2.99973 8.33008 3.01973 8.16008 3.04973 8.00008H1.39973L3.99973 3.50008L5.44973 6.00008H6.59973L4.42973 2.25008Z"/></svg></button>
  <button data-page="mcp" title="MCP 工具库"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.723 4H10V1.5C10 1.224 9.776 1 9.5 1C9.224 1 9 1.224 9 1.5V4H7V1.5C7 1.224 6.776 1 6.5 1C6.224 1 6 1.224 6 1.5V4H5.277C4.573 4 4 4.573 4 5.278V8C4 10.036 5.529 11.722 7.5 11.969V14.5C7.5 14.776 7.724 15 8 15C8.276 15 8.5 14.776 8.5 14.5V11.969C10.471 11.722 12 10.037 12 8V5.278C12 4.573 11.427 4 10.723 4ZM11 8C11 9.654 9.654 11 8 11C6.346 11 5 9.654 5 8V5.278C5 5.125 5.124 5 5.277 5H10.722C10.875 5 10.999 5.125 10.999 5.278V8H11Z"/></svg></button>
  <div class="bottom"><div class="dot"></div><button data-page="audit" title="审计"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9.25 7.25C9.25 7.76258 8.94148 8.2031 8.5 8.39599V9.50358C8.5 9.77973 8.27614 10.0036 8 10.0036C7.72386 10.0036 7.5 9.77973 7.5 9.50358V8.39599C7.05852 8.2031 6.75 7.76258 6.75 7.25C6.75 6.55964 7.30964 6 8 6C8.69036 6 9.25 6.55964 9.25 7.25ZM7.14309 2.04175C6.78097 2.2883 6.21583 2.61563 5.42482 2.91681C4.6399 3.21566 3.90375 3.36204 3.36353 3.43333C3.09405 3.46889 2.87509 3.48554 2.72547 3.49331C2.6507 3.49719 2.5934 3.49885 2.55593 3.49954L2.50489 3.50003C2.37157 3.49872 2.24323 3.55072 2.14842 3.64449C2.05344 3.73841 2 3.86643 2 4V6.75508C2 9.40779 3.4013 11.8632 5.68525 13.2124L7.74707 14.4305C7.90399 14.5232 8.09891 14.5232 8.2558 14.4304L10.3162 13.2126C12.5993 11.8632 14 9.40823 14 6.7561V4C14 3.86598 13.9462 3.73757 13.8507 3.64358C13.7552 3.54964 13.626 3.49794 13.4921 3.50007L13.4421 3.49981C13.4048 3.49928 13.3478 3.49787 13.2735 3.49426C13.1246 3.48705 12.9066 3.47109 12.6384 3.43602C12.1006 3.36573 11.3679 3.21959 10.5869 2.91771C9.79733 2.61248 9.22913 2.28442 8.86335 2.03774C8.68039 1.91435 8.54795 1.81124 8.46371 1.74141C8.4256 1.70981 8.38768 1.6777 8.35191 1.64343C8.2576 1.55073 8.13037 1.49913 7.99807 1.50001C7.86585 1.50089 7.73916 1.55434 7.64611 1.64819L7.53744 1.74536C7.45475 1.81517 7.32423 1.91842 7.14309 2.04175ZM3 6.75508V4.47725C3.14066 4.46608 3.30705 4.44945 3.49436 4.42473C4.09055 4.34605 4.90577 4.18447 5.78065 3.85136C6.64943 3.52057 7.28362 3.15585 7.70588 2.86835C7.82102 2.78996 7.92034 2.71735 8.00434 2.65277C8.08878 2.71677 8.18861 2.78886 8.30421 2.86682C8.72757 3.15233 9.362 3.51631 10.2264 3.85045C11.0994 4.18794 11.9134 4.34976 12.5088 4.42759C12.6947 4.45189 12.86 4.46809 13 4.47888V6.7561C13 9.05461 11.7861 11.1822 9.80736 12.3518L8.00133 13.4192L6.19388 12.3515C4.21446 11.1821 3 9.0541 3 6.75508Z"/></svg></button></div>
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
