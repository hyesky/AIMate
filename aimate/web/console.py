"""AIMate 浏览器管控台（aimate/web/console）—— 纯 stdlib HTTP。

OpenOcta 运维版三栏布局 + Hermes-Desktop 设计语言（浅色 Nous 蓝）。
零第三方依赖，信创红线。

布局：
- 顶部：左 LOGO+标题 / 右 账号(注册使用·导入license·用户密码·头像·岗位) + 明暗切换
- 左栏：九入口菜单（新建会话/定时任务/员工市场/会话搜索/技能库/工具库MCP/知识库/模型库/审计库）
        + 左下历史会话列表
- 中栏：聊天窗口（上传文件 / 使用技能 / 使用MCP工具 功能区）
- 右栏（可折叠）：当前对话工作目录 / 终端命令行 / 浏览器（单标签，技能打开网站时自动开）

数据层：aimate.web.accounts.AccountStore + aimate.web.session_store.SessionStore。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from aimate.web.accounts import AccountStore
from aimate.web.session_store import SessionStore

# macOS 无 `timeout`——终端命令用后台+异步轮询实现（见 _term）。

# ============================================================ CSS
_CSS = """\
:root{
  --ui-bg-chrome:#f8faff;--ui-bg-sidebar:#f3f7ff;--ui-bg-card:#ffffff;
  --ui-accent:#0053fd;--ui-accent-mix:rgba(0,83,253,.08);
  --ui-text-primary:#17181d;--ui-text-tertiary:rgba(23,24,29,.55);
  --ui-stroke-tertiary:rgba(23,24,29,.07);
  --ui-row-hover:rgba(0,83,253,.05);--ui-row-active:rgba(0,83,253,.11);
  --ui-green:#1f9e63;--ui-warn:#b7791f;--ui-red:#d64545;
  --mono:"Menlo","Monaco","SF Mono","Cascadia Code",monospace;
  --sans:-apple-system,"SF Pro Text","Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
}
html.dark{
  --ui-bg-chrome:#0f1115;--ui-bg-sidebar:#14161c;--ui-bg-card:#1a1d24;
  --ui-accent:#5b8cff;--ui-accent-mix:rgba(91,140,255,.1);
  --ui-text-primary:#e8edf7;--ui-text-tertiary:rgba(232,237,247,.5);
  --ui-stroke-tertiary:rgba(232,237,247,.07);
  --ui-row-hover:rgba(91,140,255,.06);--ui-row-active:rgba(91,140,255,.13);
  --ui-green:#3ecf8e;--ui-warn:#f5b84b;--ui-red:#ff6b6b;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--ui-bg-chrome);color:var(--ui-text-primary);font-family:var(--sans);
  font-size:13.5px;line-height:1.5;overflow:hidden;-webkit-font-smoothing:antialiased}
.hidden{display:none!important}

/* ===== 顶部栏 ===== */
header{display:flex;align-items:center;height:44px;padding:0 14px;gap:10px;
  background:var(--ui-bg-sidebar);border-bottom:1px solid var(--ui-stroke-tertiary)}
.logo{width:22px;height:22px;border-radius:6px;background:var(--ui-accent);color:#fff;
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;font-family:var(--mono)}
.t{font-weight:600;font-size:13px;letter-spacing:.2px}
.spacer{flex:1}
.topbtn{display:flex;align-items:center;gap:6px;background:transparent;border:0;color:var(--ui-text-tertiary);
  cursor:pointer;padding:5px 9px;border-radius:7px;font-size:13px;transition:background .1s,color .1s}
.topbtn:hover{background:var(--ui-row-hover);color:var(--ui-text-primary)}
.topbtn svg{width:15px;height:15px;fill:currentColor}
.avatar{width:26px;height:26px;border-radius:50%;background:var(--ui-accent-mix);color:var(--ui-accent);
  display:flex;align-items:center;justify-content:center;font-weight:600;font-size:12px;cursor:pointer}
.avatar img{width:100%;height:100%;border-radius:50%;object-fit:cover}

/* ===== 三栏 ===== */
.cols{display:flex;height:calc(100% - 44px)}
/* 左栏 */
.leftbar{width:232px;min-width:232px;background:var(--ui-bg-sidebar);border-right:1px solid var(--ui-stroke-tertiary);
  display:flex;flex-direction:column}
.navwrap{padding:8px;display:flex;flex-direction:column;gap:1px;border-bottom:1px solid var(--ui-stroke-tertiary)}
.navitem{display:flex;align-items:center;gap:9px;padding:6px 9px;border-radius:6px;cursor:pointer;
  color:var(--ui-text-tertiary);transition:background .1s,color .1s}
.navitem:hover{background:var(--ui-row-hover);color:var(--ui-text-primary)}
.navitem.on{background:var(--ui-row-active);color:var(--ui-accent);font-weight:500}
.navitem svg{width:16px;height:16px;fill:currentColor;flex-shrink:0}
.navitem .nl{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.navlabel{font-size:10.5px;color:var(--ui-text-tertiary);padding:10px 9px 4px;letter-spacing:.4px}
/* 历史会话 */
.hists{flex:1;overflow-y:auto;padding:4px 8px}
.hist{display:flex;flex-direction:column;gap:1px;padding:7px 9px;border-radius:7px;cursor:pointer}
.hist:hover{background:var(--ui-row-hover)}
.hist.on{background:var(--ui-row-active)}
.hist .ht{font-size:12.5px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hist .hs{font-size:11px;color:var(--ui-text-tertiary);display:flex;gap:8px}
.hist .hd{font-family:var(--mono);font-size:11px;color:var(--ui-text-tertiary)}

/* 中栏 */
.center{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--ui-bg-chrome)}
.ctoolbar{display:flex;align-items:center;gap:6px;padding:8px 14px;border-bottom:1px solid var(--ui-stroke-tertiary);flex-wrap:wrap}
.tbtn{background:transparent;border:1px solid var(--ui-stroke-tertiary);color:var(--ui-text-tertiary);
  cursor:pointer;padding:4px 10px;border-radius:6px;font-size:12.5px;display:flex;gap:5px;align-items:center}
.tbtn:hover{background:var(--ui-row-hover);color:var(--ui-text-primary)}
.tbtn svg{width:13px;height:13px;fill:currentColor}
.crumb{font-size:12.5px;color:var(--ui-text-tertiary);margin-left:4px}
/* 消息区 */
.msgs{flex:1;overflow-y:auto;padding:18px 22px}
.msg{display:flex;gap:10px;margin-bottom:16px}
.msg .mav{width:26px;height:26px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600}
.msg.user{flex-direction:row-reverse}
.msg.user .mav{background:rgba(0,83,253,.12);color:var(--ui-accent)}
.msg.ai .mav{background:var(--ui-accent);color:#fff}
.msg .bub{max-width:78%;padding:9px 13px;border-radius:10px;background:var(--ui-bg-card);
  border:1px solid var(--ui-stroke-tertiary);white-space:pre-wrap;word-break:break-word;line-height:1.6}
.msg.user .bub{background:var(--ui-accent-mix);border-color:transparent}
/* 输入区 */
.composer{padding:10px 16px 14px;border-top:1px solid var(--ui-stroke-tertiary);background:var(--ui-bg-chrome)}
.cbox{display:flex;align-items:flex-end;gap:8px;background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);
  border-radius:10px;padding:8px 10px;box-shadow:0 1px 3px rgba(0,0,0,.03)}
.cbox textarea{flex:1;border:0;outline:0;resize:none;background:transparent;color:var(--ui-text-primary);
  font-family:var(--sans);font-size:13.5px;line-height:1.5;max-height:120px;min-height:32px}
.sendbtn{background:var(--ui-accent);color:#fff;border:0;border-radius:8px;padding:8px 16px;font-size:13px;cursor:pointer;font-weight:500}
.sendbtn:hover{filter:brightness(1.05)}
.sendbtn:disabled{opacity:.5;cursor:default}

/* 右栏 */
.rightbar{width:320px;min-width:320px;background:var(--ui-bg-sidebar);border-left:1px solid var(--ui-stroke-tertiary);
  display:flex;flex-direction:column;transition:width .15s,margin .15s,min-width .15s;overflow:hidden}
.rightbar.collapsed{width:0;min-width:0;border-left:0}
.rhead{display:flex;align-items:center;gap:2px;padding:6px 8px;border-bottom:1px solid var(--ui-stroke-tertiary)}
.rtab{flex:1;text-align:center;padding:6px;border-radius:6px;cursor:pointer;color:var(--ui-text-tertiary);font-size:12.5px}
.rtab.on{background:var(--ui-row-active);color:var(--ui-accent);font-weight:500}
.collbtn{margin-left:4px;color:var(--ui-text-tertiary);background:transparent;border:0;cursor:pointer;padding:4px}
.collbtn svg{width:13px;height:13px;fill:currentColor}
.rcont{flex:1;overflow-y:auto;padding:10px;font-family:var(--mono);font-size:12px}
.rcont .ft{font-size:13px;font-weight:500;margin-bottom:8px;color:var(--ui-text-primary)}
.wdfile{display:flex;align-items:center;gap:7px;padding:4px 6px;border-radius:5px;cursor:default;color:var(--ui-text-primary)}
.wdfile:hover{background:var(--ui-row-hover)}
.wdfile .di{width:14px;height:14px;fill:var(--ui-accent)}
.wdfile .fi{width:14px;height:14px;fill:var(--ui-text-tertiary)}
.wdfile .fz{margin-left:auto;color:var(--ui-text-tertiary);font-size:11px}
.termout{font-family:var(--mono);font-size:12px;white-space:pre-wrap;color:var(--ui-text-primary);max-height:50vh;overflow-y:auto;padding:6px}
.termcmd{display:flex;gap:6px;margin-top:6px}
.termcmd input{flex:1;background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);border-radius:6px;color:var(--ui-text-primary);padding:6px 8px;font-family:var(--mono);font-size:12px;outline:0}
.termcmd button{background:var(--ui-accent);color:#fff;border:0;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px}
.ifrm{width:100%;height:100%;border:0;background:#fff;border-radius:6px}
.browshead{display:flex;gap:6px;padding:6px}
.browshead input{flex:1;background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);border-radius:6px;color:var(--ui-text-primary);padding:6px 8px;font-size:12px;outline:0}
.browshead button{background:var(--ui-accent);color:#fff;border:0;border-radius:6px;padding:6px 10px;cursor:pointer}

/* 登录页 */
.loginwrap{height:100vh;display:flex;align-items:center;justify-content:center;background:var(--ui-bg-chrome)}
.login-card{width:340px;padding:26px;background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);
  border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.08)}
.login-card h2{display:flex;align-items:center;gap:10px;font-size:16px;margin-bottom:18px}
.login-card .logo{width:28px;height:28px;font-size:14px}
.lf{width:100%;margin-bottom:10px;padding:9px 11px;border:1px solid var(--ui-stroke-tertiary);border-radius:8px;
  background:var(--ui-bg-chrome);color:var(--ui-text-primary);font-size:13px;outline:0}
.lf:focus{border-color:var(--ui-accent)}
.lbtn{width:100%;padding:10px;border:0;border-radius:8px;background:var(--ui-accent);color:#fff;font-size:13.5px;cursor:pointer;font-weight:500}
.lbtn:hover{filter:brightness(1.05)}
.lrow{display:flex;gap:8px;margin-top:10px}
.lrow button{flex:1;background:transparent;border:1px solid var(--ui-stroke-tertiary);border-radius:8px;padding:8px;cursor:pointer;color:var(--ui-text-tertiary);font-size:12.5px}
.lrow button:hover{background:var(--ui-row-hover);color:var(--ui-text-primary)}
.err{color:var(--ui-red);font-size:12.5px;margin-bottom:8px;min-height:17px}
.small{font-size:11px;color:var(--ui-text-tertiary)}
.lmsg{color:var(--ui-green);font-size:12px;margin-top:8px}

/* 下拉菜单 */
.menu{position:fixed;background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);border-radius:10px;
  box-shadow:0 8px 30px rgba(0,0,0,.1);padding:5px;z-index:100;min-width:200px}
.menu div{padding:7px 11px;border-radius:6px;cursor:pointer;font-size:13px}
.menu div:hover{background:var(--ui-row-hover)}
.menu .sep{border-top:1px solid var(--ui-stroke-tertiary);margin:4px 0;padding:0}
.menu .lbl{font-size:11px;color:var(--ui-text-tertiary);cursor:default}
.panel{background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);border-radius:10px;padding:14px;margin-bottom:12px}
.panel h3{font-size:13.5px;font-weight:600;margin-bottom:10px}
.panel .kv{display:flex;gap:8px;padding:5px 0;border-bottom:1px solid var(--ui-stroke-tertiary);font-size:12.5px}
.panel .kv:last-child{border-bottom:0}
.panel .k{color:var(--ui-text-tertiary);min-width:70px;flex-shrink:0}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11px;background:var(--ui-accent-mix);color:var(--ui-accent);margin-right:4px}
.pill.ok{background:rgba(31,158,99,.12);color:var(--ui-green)}
.pill.warn{background:rgba(183,121,31,.12);color:var(--ui-warn)}
.modalback{position:fixed;inset:0;background:rgba(0,0,0,.3);z-index:90;display:flex;align-items:center;justify-content:center}
.modal{width:460px;background:var(--ui-bg-card);border-radius:14px;padding:22px}
.modal h3{margin-bottom:14px;font-size:15px}
.modal .row{display:flex;gap:10px}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:var(--ui-text-primary);color:var(--ui-bg-card);
  padding:9px 18px;border-radius:8px;font-size:13px;z-index:200;opacity:0;transition:opacity .2s}
.toast.show{opacity:1}
.scroll::-webkit-scrollbar{width:9px;height:9px}
.scroll::-webkit-scrollbar-thumb{background:rgba(23,24,29,.18);border-radius:6px;border:2px solid transparent;background-clip:content-box}
.scroll::-webkit-scrollbar-thumb:hover{background:rgba(23,24,29,.3);background-clip:content-box}
"""

# ============================================================ JS
_JS = r"""
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let TOKEN=localStorage.getItem('am_token')||'';
let CURRENT_SID=null, RIGHT_PANEL='workdir';
async function jf(url,method='GET',body){const o={method,headers:{'Content-Type':'application/json'}};
 if(TOKEN)o.headers['X-Auth-Token']=TOKEN;
 if(body!==undefined)o.body=JSON.stringify(body);
 const r=await fetch(url,o);const j=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;}
function toast(m){const t=document.createElement('div');t.className='toast';t.textContent=m;document.body.appendChild(t);
 requestAnimationFrame(()=>t.classList.add('show'));setTimeout(()=>{t.classList.remove('show');setTimeout(()=>t.remove(),300)},2000);}

/* ===== 主题 ===== */
function applyTheme(t){document.documentElement.classList.toggle('dark',t==='dark');localStorage.setItem('am_theme',t);
 const tb=$('#theme-toggle');if(tb)tb.textContent=t==='dark'?'☀':'☾';}
async function toggleTheme(){applyTheme(document.documentElement.classList.contains('dark')?'light':'dark');}

/* ===== 登录 ===== */
function showLogin(){ $('#login').classList.remove('hidden');$('#app').classList.add('hidden'); }
function showApp(){ $('#login').classList.add('hidden');$('#app').classList.remove('hidden'); }
async function doLogin(){
 const u=$('#login-user').value.trim(),p=$('#login-pw').value;
 if(!u||!p){$('#login-err').textContent='请输入用户名与密码';return}
 try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
  const j=await r.json();if(!r.ok)throw new Error(j.error||'登录失败');
  TOKEN=j.token;localStorage.setItem('am_token',TOKEN);$('#login-err').textContent='';
  applyTheme(j.theme||'light');await bootApp();}
 catch(e){$('#login-err').textContent=e.message}}
async function doRegister(){
 const u=$('#reg-user').value.trim(),p=$('#reg-pw').value,n=$('#reg-name').value.trim()||u,post=$('#reg-post').value.trim();
 if(!u||!p){$('#reg-err').textContent='请填用户名与密码';return}
 try{const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p,name:n,post})});
  const j=await r.json();if(!r.ok)throw new Error(j.error||'注册失败');
  $('#reg-err').textContent='';$('#reg-ok').textContent='注册成功，请登录';
  backToLogin();}
 catch(e){$('#reg-err').textContent=e.message}}
function toReg(){ $('#login-form').classList.add('hidden');$('#reg-form').classList.remove('hidden');
 $('#login-card-title').textContent='注册 AIMate 账号'; }
function backToLogin(){ $('#login-form').classList.remove('hidden');$('#reg-form').classList.add('hidden');
 $('#login-card-title').textContent='登录 AIMate'; }

/* ===== 导航 ===== */
const NAVICONS={
 chat:'M8 1a7 7 0 0 0-7 7c0 1.5.4 2.9 1 4.1L1 15l3.1-.9a7 7 0 1 0 3.9-13.1z',
 cron:'M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm1 4a1 1 0 1 0-2 0v3a1 1 0 0 0 .6.9l2 1a1 1 0 1 0 1-1.8L9 7.6z',
 market:'M4 14a3 3 0 0 1 3-3h2a3 3 0 0 1 3 3v1H4zm4-8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM13 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm-1 7a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v1h-5z',
 search:'M10.6 9.6a4.5 4.5 0 1 0-.7.7l3.4 3.4 1.4-1.4-4.1-4.7zM7 10a3 3 0 1 1 0-6 3 3 0 0 1 0 6z',
 skills:'M7 1a1 1 0 0 1 1 1v10.6a4 4 0 1 1-2 0V2a1 1 0 0 1 1-1z',
 mcp:'M12 1h2v2h3a1 1 0 0 1 1 .9V7a4 4 0 0 1-3 3.9V13a3 3 0 0 1-3 3h-1v-2h1a1 1 0 0 0 1-.9V11h-4v2.1a1 1 0 0 0 1 .9h1v2h-1a3 3 0 0 1-3-3v-2.1A4 4 0 0 1 3 7V4a1 1 0 0 1 1-.9h3V1h2z',
 kb:'M4 1h8a1 1 0 0 1 1 1v12l-2.5-1.6L8 14l-2.5-1.6L3 14V2a1 1 0 0 1 1-1z',
 db:'M8 2c3 0 5 1 5 2.5S11 7 8 7 3 6 3 4.5 5 2 8 2zm0 6c2.6 0 4.4.8 4.9 1.7a4 4 0 0 1 0 2.6C12.4 13.2 10.6 14 8 14s-4.4-.8-4.9-1.7a4 4 0 0 1 0-2.6C3.6 8.8 5.4 8 8 8z',
 audit:'M8 1l6 2v5c0 4-2.5 6.5-6 7-3.5-.5-6-3-6-7V3l6-2z',
};
function nav(page){document.querySelectorAll('.navitem').forEach(x=>x.classList.toggle('on',x.dataset.page===page));
 document.querySelectorAll('.nview').forEach(v=>v.classList.toggle('hidden',v.id!==(page+'view')));
 document.getElementById('crumb').textContent=document.querySelector('.navitem[data-page="'+page+'"] .nl').textContent;
 if(page==='chat'&&CURRENT_SID)loadMsgs();
 if(page==='kb')loadKbTree();
 if(page==='skills')loadSkills();
 if(page==='mcp')loadMcp();
 if(page==='db')loadModels();
 if(page==='audit')loadAudit();
 if(page==='sessions'){}}
function mountNav(){
 const items=[['chat','新建会话'],['cron','定时任务'],['market','员工市场'],['search','会话搜索'],
  ['skills','技能库'],['mcp','工具库 MCP'],['kb','知识库'],['db','模型库'],['audit','审计库']];
 $('#navwrap').innerHTML=items.map(([p,n])=>'<div class="navitem" data-page="'+p+'" onclick="nav(\''+p+'\')">'
  +'<svg viewBox="0 0 16 16"><path d="'+(NAVICONS[p]||NAVICONS.chat)+'"/></svg>'
  +'<span class="nl">'+n+'</span></div>').join('');
 mountViews();}

/* ===== 会话 ===== */
async function newSession(){const r=await jf('/api/sessions','POST',{title:'新会话'});CURRENT_SID=r.session_id;
 $('#chat-title').textContent=r.title;loadMsgs();loadWorkdir();loadHist();}
async function openSession(sid){CURRENT_SID=sid;const r=await jf('/api/sessions/'+sid);if(!CURRENT_SID)return;
 loadMsgs();loadWorkdir();loadHist();loadSessSearch(sid);}
async function delSession(sid,ev){ev.stopPropagation();if(!confirm('删除会话及其工作目录？'))return;
 await jf('/api/sessions/'+sid,'DELETE');if(CURRENT_SID===sid){CURRENT_SID=null;$('#msgs').innerHTML='';
  $('#workdir').innerHTML='';}$('#chat-title').textContent='新建会话';loadHist();toast('已删除会话');}
async function loadHist(){$('#hists').innerHTML='<div class="small" style="padding:8px 10px">加载中…</div>';
 const r=await jf('/api/sessions');const list=r.sessions||[];
 $('#hists').innerHTML=list.map(s=>{const d=s.updated?new Date(s.updated*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'';
  return '<div class="hist'+(s.session_id===CURRENT_SID?' on':'')+'" onclick="openSession(\''+s.session_id+'\')">'
  +'<div class="ht">'+esc(s.title||'新会话')+'</div><div class="hs"><span>'+s.count+' 条</span><span>'+d+'</span></div>'
  +'<div class="hd">'+s.session_id.slice(0,8)+'</div></div>';}).join('')
  ||'<div class="small" style="padding:8px 10px">还没有会话，点「新建会话」开始</div>';}
async function loadMsgs(){if(!CURRENT_SID){$('#msgs').innerHTML='<div class="msg ai"><div class="mav">Ai</div>'
 +'<div class="bub">点击左上「新建会话」开始一段对话。每个会话有独立工作目录，删除会话会一并清理。</div></div>';return}
 const r=await jf('/api/sessions/'+CURRENT_SID+'/messages');
 $('#msgs').innerHTML=(r.messages||[]).map(m=>{const ai=m.role!=='user';
  return '<div class="msg '+(ai?'ai':'user')+'"><div class="mav">'+(ai?'Ai':(ME.name||ME.username||'我').slice(0,1))+
  '</div><div class="bub">'+esc(m.content)+'</div></div>';}).join('')
  ||'<div class="small" style="padding:10px">新会话，发第一条消息吧。</div>';
 $('#msgs').scrollTop=99999;}
async function send(){const t=$('#input').value.trim();if(!t||!CURRENT_SID)return;
 $('#input').value='';$('#send').disabled=true;
 const msgs=(await jf('/api/sessions/'+CURRENT_SID+'/messages')).messages||[];
 msgs.push({role:'user',content:t});
 await jf('/api/sessions/'+CURRENT_SID+'/messages','POST',{role:'user',content:t});
 appendMsg('user',t);$('#msgs').scrollTop=99999;
 try{const r=await jf('/api/chat','POST',{session_id:CURRENT_SID,messages:msgs});
  const reply=r?.reply||r?.content||(typeof r==='string'?r:'');
  await jf('/api/sessions/'+CURRENT_SID+'/messages','POST',{role:'assistant',content:reply});
  appendMsg('ai',reply);$('#msgs').scrollTop=99999;}
 catch(e){appendMsg('ai','⚠ '+e.message)}
 finally{$('#send').disabled=false;loadHist();}}
function appendMsg(role,text){const ai=role!=='user';
 $('#msgs').insertAdjacentHTML('beforeend','<div class="msg '+(ai?'ai':'user')+'"><div class="mav">'
 +(ai?'Ai':(ME.name||'我').slice(0,1))+'</div><div class="bub">'+esc(text)+'</div></div>');}

/* ===== 右侧面板 ===== */
async function loadWorkdir(){if(!CURRENT_SID){$('#workdir').innerHTML='<div class="small">打开会话后显示工作目录</div>';return}
 const r=await jf('/api/sessions/'+CURRENT_SID+'/workdir');$('#wdtitle').textContent=esc(r.path||'');
 $('#workdir').innerHTML=(r.files||[]).map(f=>({pre:'<span class="di">📁</span>',re:'<span class="fi">📄</span>'}
 )[f.type||'f']||'<span class="fi">·</span>') .join('')&&'';
 $('#workdir').innerHTML='<div class="wdfile"><span class="di">📁</span><span>'+esc(r.path||'')+'</span></div>'+
 (r.files||[]).map(f=>'<div class="wdfile"><span class="'+(f.type==='d'?'di':'fi')+'">'+(f.type==='d'?'📁':'📄')+
 '</span><span>'+esc(f.name)+'</span><span class="fz">'+(f.size?fmtSize(f.size):'')+'</span></div>').join('')
 +'<div style="height:10px"></div><div class="small">右键删除对话会同时删除此目录。</div>';}
function fmtSize(n){if(n<1024)return n+'B';if(n<1048576)return (n/1024).toFixed(1)+'K';return (n/1048576).toFixed(1)+'M'}
function setRight(p){RIGHT_PANEL=p;document.querySelectorAll('.rtab').forEach(x=>x.classList.toggle('on',x.dataset.p===p));
 ['workdir','terminal','browser'].forEach(k=>$('#'+k).classList.toggle('hidden',k!==p));
 if(p==='browser'&&!$('#browser').dataset.loaded){$('#browser').innerHTML='<div class="small">技能打开网站时此处自动显示（单标签）。</div>';}}
async function collapseRight(){const rb=$('#rightbar');rb.classList.toggle('collapsed');
 $('#collbtn').innerHTML=rb.classList.contains('collapsed')?'<svg viewBox="0 0 16 16"><path d="M9 4l4 4-4 4V4zM8 8"/></svg>':'<svg viewBox="0 0 16 16"><path d="M7 4l-4 4 4 4V4zm1 4"/></svg>';}
async function termRun(){const cmd=$('#term-in').value.trim();if(!cmd)return;
 $('#term-out').insertAdjacentHTML('beforeend','<div style="color:var(--ui-accent)">$ '+esc(cmd)+'</div>');
 $('#term-in').value='';const r=await jf('/api/sessions/'+CURRENT_SID+'/term','POST',{cmd});
 $('#term-out').insertAdjacentHTML('beforeend','<div>'+esc(r.output||'(无输出)').trim()+'</div>');
 $('#term-out').scrollTop=99999;}
async function bnav(){const u=$('#browser-url').value.trim();if(!u)return;if(!/^https?:/i.test(u))u='http://'+u;
 await openBrowser(u);}
async function openBrowser(url){$('#browser').innerHTML='<iframe class="ifrm" src="'+esc(url)+'"></iframe>';
 $('#browser-url').value=url;$('#browser').dataset.loaded='1';}

/* ===== 各管理视图 ===== */
function mountViews(){
 $('#chatview').innerHTML='<div class="msgs scroll" id="msgs"></div><div class="composer"><div class="cbox">'
 +'<textarea id="input" placeholder="输入指令…(Enter 发送)"></textarea>'
 +'<button class="sendbtn" id="send" onclick="send()">发送</button></div>'
 +'<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">'
 +'<button class="tbtn" onclick="pickFile()">⬆ 上传文件</button>'
 +'<button class="tbtn" onclick="openSkillPicker()">🧩 使用技能</button>'
 +'<button class="tbtn" onclick="loadMcp();nav(\'mcp\')">🔌 MCP 工具</button>'
 +'<button class="tbtn" onclick="openBrowser(\'about:blank\')">🌐 打开浏览器</button></div></div>';
 $('#cronview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>定时任务 Cron</h3>'
 +'<p class="small" style="margin-bottom:10px">自然语言或 Cron 表达式，可附加技能，结果发任意平台，支持暂停/恢复/编辑。</p>'
 +'<div id="cron-list" class="small">（开发中 — P2 接入）</div></div></div>';
 $('#marketview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>员工市场</h3>'
 +'<p class="small">浏览/安装数字员工 Agent。（开发中 — P3 接入）</p></div></div>';
 $('#searchview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>会话搜索</h3>'
 +'<div style="display:flex;gap:8px;margin-bottom:10px"><input class="lf" id="sq" placeholder="按关键词搜索所有会话…" style="flex:1">'
 +'<button class="sendbtn" onclick="doSessSearch()">搜索</button></div>'
 +'<div id="search-results" class="small"></div></div></div>';
 $('#skillsview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>技能库</h3>'
 +'<div id="skills-list"></div></div></div>';
 $('#mcpview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>工具库 MCP</h3>'
 +'<div style="display:flex;gap:8px;margin-bottom:10px"><input class="lf" id="mcp-name" placeholder="名称" style="width:110px">'
 +'<input class="lf" id="mcp-cmd" placeholder="命令，如 python3 -m aimate.mcp.demo" style="flex:1">'
 +'<button class="sendbtn" onclick="addMcp()">连接</button></div><div id="mcp-list"></div></div></div>';
 $('#kbview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>本地知识库</h3>'
 +'<p class="small" style="margin-bottom:10px">目录：<span id="kb-root" class="hd"></span></p>'
 +'<div style="display:flex;gap:8px;margin-bottom:10px"><input class="lf" id="kb-search" placeholder="按名称搜索文件…" style="flex:1">'
 +'<button class="sendbtn" onclick="kbSearch()">搜索</button></div>'
 +'<div style="display:flex;gap:6px;margin-bottom:10px"><button class="tbtn" onclick="kbNewFile()">+ 文件</button>'
 +'<button class="tbtn" onclick="kbNewDir()">+ 文件夹</button></div>'
 +'<div id="kb-tree" class="small"></div></div></div>';
 $('#dbview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>模型库</h3>'
 +'<div id="models-list"></div></div></div>';
 $('#auditview').innerHTML='<div class="msgs scroll"><div class="panel"><h3>审计库</h3>'
 +'<div id="audit-list"></div></div></div>';
 $('#input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
}

/* ===== 管理数据加载 ===== */
async function loadSkills(){const r=await jf('/api/skills');
 $('#skills-list').innerHTML=(r.skills||[]).map(s=>'<div class="kv"><span class="k">'+esc(s.name)+'</span>'
 +'<span class="pill '+(s.status==='published'?'ok':'warn')+'">'+esc(s.status)+'</span>'
 +'<span>'+esc(s.description)+'</span></div>').join('')||'<div class="small">暂无技能</div>';}
async function loadMcp(){const r=await jf('/api/mcp');
 $('#mcp-list').innerHTML=(r.servers||[]).map(s=>'<div class="kv"><span class="k">'+esc(s.name)+'</span>'
 +'<span class="small">'+(s.tools||[]).join(', ')+'</span></div>').join('')
 +'<div class="small" style="margin-top:6px">工具总数：'+(r.tool_count||0)+'</div>'
 ||'<div class="small">未连接 MCP server</div>';}
async function addMcp(){const n=$('#mcp-name').value.trim(),c=$('#mcp-cmd').value.trim();
 if(!n||!c)return toast('名称与命令必填');
 try{const r=await jf('/api/mcp','POST',{name:n,cmd:c.split(/\\s+/)});toast('已连接 '+r.name);loadMcp()}
 catch(e){toast('连接失败: '+e.message)}}
async function loadModels(){const r=await jf('/api/llm');
 $('#models-list').innerHTML=(r.backends||[]).map(b=>'<div class="kv"><span class="k">'+esc(b.alias)+'</span>'
 +'<span class="small">'+esc(b.base_url)+'</span><span class="pill ok">'+esc(b.model||'?')+'</span></div>').join('')
 +'<div class="small" style="margin-top:6px">默认：'+esc(r.default||'—')+'</div>'
 +'<div style="margin-top:10px;display:flex;gap:6px"><input class="lf" id="m-name" placeholder="name" style="flex:1">'
 +'<input class="lf" id="m-url" placeholder="base_url" style="flex:2"></div>'
 +'<div style="margin-top:8px;display:flex;gap:6px"><input class="lf" id="m-key" placeholder="api_key" style="flex:2">'
 +'<input class="lf" id="m-model" placeholder="model" style="flex:1"></div>'
 +'<div style="margin-top:8px"><button class="sendbtn" onclick="addModel()">注册模型</button></div>';}
async function addModel(){const name=$('#m-name').value.trim(),url=$('#m-url').value.trim();
 if(!name||!url)return toast('name 与 base_url 必填');
 try{const r=await jf('/api/llm','POST',{name,base_url:url,api_key:$('#m-key').value,model:$('#m-model').value||'default'});
  toast('已注册 '+r.name);loadModels()}catch(e){toast('失败: '+e.message)}}
async function loadAudit(){const r=await jf('/api/audit');
 $('#audit-list').innerHTML=(r.events||[]).slice(0,80).map(e=>'<div class="kv"><span class="k">'+(e.time?.slice(11,19)||'')+'</span>'
 +'<b>'+esc(e.action)+'</b><span>'+esc(e.detail||'')+'</span></div>').join('')||'<div class="small">暂无审计</div>';}

async function loadKbTree(){const r=await jf('/api/kb/tree');
 $('#kb-root').textContent=r.root||'';renderKbTree(r.tree||r.files||[],'');
 const q=$('#kb-search').value;if(q)kbSearch();}
function renderKbTree(nodes,path){$('#kb-tree').innerHTML=walk(nodes,path);}
function walk(nodes,path){let out='';for(const n of nodes||[]){
 const p=path?path+'/'+n.name:n.name;
 if(n.type==='d')out+='<div class="wdfile" onclick="kbExpand(\''+escPath(p)+'\')" style="cursor:pointer">'
  +'<span class="di">📁</span><span>'+esc(n.name)+'</span></div>'
  +'<div style="padding-left:16px" id="kbx-'+escPath(p)+'">'+(n.children?walk(n.children,p):'')+'</div>';
 else out+='<div class="wdfile" onclick="kbPreview(\''+escPath(p)+'\')" style="cursor:pointer">'
  +'<span class="fi">📄</span><span>'+esc(n.name)+'</span>'
  +'<span class="fz">'+esc(n.ext||'')+'</span></div>';}return out}
function escPath(p){return esc(p).replace(/'/g,"\\'")}
async function kbExpand(p){const r=await jf('/api/kb/branch?path='+encodeURIComponent(p));
 const el=document.getElementById('kbx-'+esc(p));if(el)el.innerHTML=walk(r.files,p);}
async function kbSearch(){const q=$('#kb-search').value.trim();if(!q){loadKbTree();return}
 const r=await jf('/api/kb/search?q='+encodeURIComponent(q));
 $('#kb-tree').innerHTML=(r.results||[]).map(f=>'<div class="wdfile" style="cursor:pointer" onclick="kbPreview(\''
  +escPath(f.path)+'\')"><span class="fi">📄</span><span>'+esc(f.path)+'</span><span class="fz">'+esc(f.ext)+'</span></div>').join('')
  ||'<div class="small">无匹配文件</div>';}
async function kbPreview(p){try{const r=await jf('/api/kb/file?path='+encodeURIComponent(p));
 let body='';
 if(r.kind==='image' && r.binary?.data_uri){body='<img src="'+r.binary.data_uri+'" style="max-width:100%;border-radius:8px">';}
 else if(r.kind==='video' && r.binary?.data_uri){body='<video src="'+r.binary.data_uri+'" controls style="max-width:100%"></video>';}
 else if(r.kind==='audio' && r.binary?.data_uri){body='<audio src="'+r.binary.data_uri+'" controls></audio>';}
 else if(r.kind==='text'||r.kind==='code'){body='<pre style="white-space:pre-wrap;max-height:60vh;overflow:auto;margin:0;font:12px/1.6 Menlo,monospace">'+esc(r.content||'')+'</pre>';}
 else {body='<div class="small" style="color:var(--ui-fg-muted)">「'+esc(r.kind||'file')+'」类型文件暂无内联预览，可用默认应用打开。</div>'+(r.binary?('<div class="small">大小 '+fmtSize(r.binary.size)+'</div>'):'');}
 const appBtn='<div style="margin-top:10px"><button class="tbtn" onclick="kbOpenApp(\''+escPath(p)+'\')">用默认应用打开</button></div>';
 openModal('预览：'+p,body+appBtn);}
 catch(e){toast(e.message)}}
function fmtSize(n){if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';return (n/1048576).toFixed(1)+' MB'}
async function kbOpenApp(p){await jf('/api/kb/open','POST',{path:p});toast('已用默认应用打开')}
async function kbNewFile(){const name=prompt('文件名(含扩展名):');if(!name)return
 const p=prompt('目录路径(留空=根):','');await jf('/api/kb/new','POST',{path:p||'',name,type:'f'});toast('已新建');loadKbTree()}
async function kbNewDir(){const name=prompt('文件夹名:');if(!name)return
 const p=prompt('父目录路径(留空=根):','');await jf('/api/kb/new','POST',{path:p||'',name,type:'d'});toast('已新建');loadKbTree()}

/* ===== 会话搜索 + 上传 ===== */
async function doSessSearch(){const q=$('#sq').value.trim();if(!q)return
 const r=await jf('/api/sessions/search?q='+encodeURIComponent(q));
 $('#search-results').innerHTML=(r.results||[]).map(s=>'<div class="hist" style="padding:8px" onclick="openSession(\''+s.session_id+'\')">'
 +'<div class="ht">'+esc(s.title)+' <span class="hs">'+s.count+' 条</span></div>'
 +'<div class="hs">'+esc((s.snippets||[])[0]||'')+'</div></div>').join('')||'<div class="small">无命中</div>';}
function pickFile(){const inp=document.createElement('input');inp.type='file';inp.onchange=async()=>{
  const f=inp.files[0];if(!f)return;const fd=new FormData();fd.append('file',f);
  const resp=await fetch('/api/sessions/'+CURRENT_SID+'/upload',{method:'POST',body:fd,headers:TOKEN?{'X-Auth-Token':TOKEN}:{}});
  const j=await resp.json();if(!resp.ok){toast(j.error||'上传失败');return}
  const p=j.path;const txt=j.preview||'';appendMsg('user','[上传文件] '+f.name);
  await jf('/api/sessions/'+CURRENT_SID+'/messages','POST',{role:'user',content:'[上传文件] '+f.name+'\n'+txt});
  loadWorkdir();toast('已上传')};inp.click()}
async function openSkillPicker(){const r=await jf('/api/skills');const names=(r.skills||[]).map(s=>s.name);
 const n=prompt('使用技能:\n'+names.join('、')||'（无技能）');if(!n)return
 $('#input').value+=' /use-skill '+n+' ';$('#input').focus()}

/* ===== 账号菜单 ===== */
function toggleMenu(ev){ev.stopPropagation();const m=$('#usermenu');if(m)return m.remove();
 const d=document.createElement('div');d.id='usermenu';d.className='menu';
 d.style.top=(ev.clientY+6)+'px';d.style.right='12px';
 d.innerHTML='<div class="lbl">'+esc(ME.name||ME.username)+' · '+esc(ME.post||'未设岗位')+'</div>'
 +'<div class="sep"></div><div onclick="openProfile()">账号资料</div>'
 +'<div onclick="openLicense()">导入 License</div>'
 +'<div onclick="openPwd()">修改密码</div>'
 +'<div class="sep"></div><div onclick="logout()">退出登录</div>';
 document.body.appendChild(d);
 setTimeout(()=>document.addEventListener('click',()=>{const x=document.getElementById('usermenu');if(x)x.remove()},{once:true}))}
function openProfile(){openModal('账号资料','<input class="lf" id="p-name" placeholder="姓名" value="'+esc(ME.name||'')+'">'
 +'<input class="lf" id="p-post" placeholder="岗位" value="'+esc(ME.post||'')+'">'
 +'<div style="margin-top:4px"><button class="sendbtn" onclick="saveProfile()">保存</button></div>')}
async function saveProfile(){const name=$('#p-name').value,post=$('#p-post').value;
 await jf('/api/profile','POST',{name,post});toast('已保存');document.querySelector('.modalback').remove();loadMe()}
function openLicense(){openModal('导入 License','<textarea class="lf" id="lic" style="height:120px" placeholder="粘贴 license JSON"></textarea>'
 +'<div style="margin-top:4px"><button class="sendbtn" onclick="saveLicense()">导入</button></div>')}
async function saveLicense(){const raw=$('#lic').value.trim();if(!raw)return toast('内容为空');
 try{await jf('/api/license','POST',{raw});toast('License 已导入');document.querySelector('.modalback').remove();loadMe()}
 catch(e){toast('导入失败: '+e.message)}}
function openPwd(){openModal('修改密码','<input class="lf" id="pw-old" type="password" placeholder="原密码">'
 +'<input class="lf" id="pw-new" type="password" placeholder="新密码">'
 +'<div style="margin-top:4px"><button class="sendbtn" onclick="savePwd()">修改</button></div>')}
async function savePwd(){const o=$('#pw-old').value,n=$('#pw-new').value;
 try{const r=await jf('/api/password','POST',{old_pw:o,new_pw:n});toast(r.ok?'密码已修改':'原密码错误')}
 catch(e){toast(e.message)}document.querySelector('.modalback')?.remove()}
async function logout(){TOKEN='';localStorage.removeItem('am_token');showLogin()}
function openModal(title,body){const b=document.createElement('div');b.className='modalback';b.onclick=e=>{if(e.target===b)b.remove()};
 b.innerHTML='<div class="modal"><h3>'+title+'</h3>'+body+'</div>';document.body.appendChild(b)}

/* ===== 启动 ===== */
let ME={};
async function loadMe(){const r=await jf('/api/me');ME=r;const av=$('#me-avatar');
 if(!av)return;av.textContent=(ME.name||ME.username||'?').slice(0,1).toUpperCase();}
async function bootApp(){showApp();loadMe();const savedTheme=localStorage.getItem('am_theme')||document.documentElement.classList.contains('dark')?'dark':'light';
 applyTheme(savedTheme);mountNav();loadHist();
 const r=await jf('/api/sessions');if(r.sessions?.length){CURRENT_SID=r.sessions[0].session_id;loadMsgs();loadWorkdir()}
 else await newSession()}
async function boot(){const savedToken=localStorage.getItem('am_token');
 if(savedToken){TOKEN=savedToken;try{await jf('/api/me');await bootApp();return}catch(e){}TOKEN=''}
 showLogin()}
document.addEventListener('DOMContentLoaded',boot);
"""

# ============================================================ HTML
_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIMate 管控台</title><style>__CSS__</style></head>
<body>
<!-- 登录页 -->
<div id="login" class="loginwrap hidden">
  <div class="login-card">
    <h2 id="login-card-title"><div class="logo">Ai</div> 登录 AIMate</h2>
    <div id="login-form">
      <div class="err" id="login-err"></div>
      <input class="lf" id="login-user" placeholder="用户名" autocomplete="username">
      <input class="lf" id="login-pw" type="password" placeholder="密码" autocomplete="current-password">
      <button class="lbtn" onclick="doLogin()">登 录</button>
      <div class="lrow"><button onclick="toReg()">注册使用</button><button onclick="openModal('导入 License','<textarea class=&quot;lf&quot; id=&quot;lic&quot; style=&quot;height:120px&quot; placeholder=&quot;粘贴 license JSON&quot;></textarea><div style=&quot;margin-top:4px&quot;><button class=&quot;sendbtn&quot; onclick=&quot;saveLicense()&quot;>导入</button></div>')">导入 License</button></div>
    </div>
    <div id="reg-form" class="hidden">
      <div class="err" id="reg-err"></div>
      <div class="lmsg" id="reg-ok"></div>
      <input class="lf" id="reg-user" placeholder="用户名 *">
      <input class="lf" id="reg-pw" type="password" placeholder="密码 *">
      <input class="lf" id="reg-name" placeholder="姓名(选填)">
      <input class="lf" id="reg-post" placeholder="岗位(选填)">
      <button class="lbtn" onclick="doRegister()">注 册</button>
      <div class="lrow"><button onclick="backToLogin()">返回登录</button></div>
    </div>
  </div>
</div>

<!-- 主应用 -->
<div id="app" class="hidden">
  <header>
    <div class="logo">Ai</div><div class="t">AIMate 管控台</div>
    <span class="crumb" id="crumb">新建会话</span>
    <div class="spacer"></div>
    <button class="topbtn" id="theme-toggle" onclick="toggleTheme()">☾</button>
    <div class="avatar" id="me-avatar" onclick="toggleMenu(event)">?</div>
    <div id="usermenu-wrap"></div>
  </header>
  <div class="cols">
    <!-- 左栏 -->
    <aside class="leftbar">
      <div class="navwrap" id="navwrap"></div>
      <div class="navlabel">历史会话</div>
      <div class="hists scroll" id="hists"></div>
    </aside>
    <!-- 中栏 -->
    <main class="center">
      <div class="ctoolbar" style="display:none">
        <span class="crumb" id="chat-title">新建会话</span>
      </div>
      <div id="chatview" class="nview"></div>
      <div id="cronview" class="nview hidden"></div>
      <div id="marketview" class="nview hidden"></div>
      <div id="searchview" class="nview hidden"></div>
      <div id="skillsview" class="nview hidden"></div>
      <div id="mcpview" class="nview hidden"></div>
      <div id="kbview" class="nview hidden"></div>
      <div id="dbview" class="nview hidden"></div>
      <div id="auditview" class="nview hidden"></div>
    </main>
    <!-- 右栏 -->
    <aside class="rightbar" id="rightbar">
      <div class="rhead">
        <div class="rtab on" data-p="workdir" onclick="setRight('workdir')">工作目录</div>
        <div class="rtab" data-p="terminal" onclick="setRight('terminal')">终端</div>
        <div class="rtab" data-p="browser" onclick="setRight('browser')">浏览器</div>
        <button class="collbtn" id="collbtn" onclick="collapseRight()"><svg viewBox="0 0 16 16"><path d="M7 4l-4 4 4 4V4zm1 4"/></svg></button>
      </div>
      <div class="rcont scroll" id="workdir"><div class="small">打开会话后显示工作目录</div></div>
      <div class="rcont scrollt hidden" id="terminal">
        <div class="ft">终端命令行（工作目录内执行）</div>
        <div class="termout" id="term-out"></div>
        <div class="termcmd"><input id="term-in" placeholder="输入命令… 回车执行"><button onclick="termRun()">执行</button></div>
      </div>
      <div class="rcont hidden" id="browser">
        <div class="ft">浏览器（单标签）</div>
        <div class="browshead"><input id="browser-url" placeholder="输入网址… 回车打开"><button onclick="bnav()">打开</button></div>
      </div>
    </aside>
  </div>
</div>
<script>__JS__</script>
</body></html>
"""

# ============================================================ Handler
class ConsoleHandler(BaseHTTPRequestHandler):
    system: Any = None
    agent_ids: list[str] = []
    accounts: AccountStore = None
    sessions: SessionStore = None

    # ---- helpers ----
    def _send(self, code: int, data, ctype: str = "application/json; charset=utf-8"):
        if isinstance(data, bytes):
            body = data
        else:
            body = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _html(self):
        pg = _PAGE.replace("__CSS__", _CSS).replace("__JS__", _JS)
        self._send(200, pg, "text/html; charset=utf-8")

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            return {}

    def _auth(self):
        """返回当前登录用户（X-Auth-Token）。未登录返回 None。"""
        tok = self.headers.get("X-Auth-Token", "")
        if not tok:
            return None
        try:
            return self.accounts.whoami(tok)
        except Exception:
            return None

    def _owner(self) -> str:
        u = self._auth()
        return u.username if u else "default"

    def _require(self):
        u = self._auth()
        if u is None:
            self._send(401, {"error": "未登录"})
            return None
        return u

    # ---- 页面 ----
    def _index(self):
        return self._html()

    # ---- auth 端点 ----
    def _auth_register(self):
        b = self._body()
        username = (b.get("username") or "").strip()
        password = b.get("password") or ""
        if not username or not password:
            return self._send(400, {"error": "用户名与密码必填"})
        try:
            self.accounts.register(username, password, name=b.get("name"),
                                   post=b.get("post"), role="member")
            self.system.audit.record("console", username, "auth.register", username)
            return self._send(200, {"ok": True})
        except ValueError as e:
            return self._send(400, {"error": str(e)})

    def _auth_login(self):
        b = self._body()
        u = self.accounts.login(b.get("username", "").strip(), b.get("password", ""))
        if not u:
            return self._send(401, {"error": "用户名或密码错误"})
        token, acc = u
        self.system.audit.record("console", acc.username, "auth.login", acc.username)
        return self._send(200, {"token": token, "username": acc.username,
                                "name": acc.name, "theme": acc.theme})

    def _me(self):
        u = self._require()
        if not u:
            return
        return self._send(200, {"username": u.username, "name": u.name, "post": u.post,
                                "role": u.role, "theme": u.theme,
                                "license_features": u.license_features or [],
                                "license_expires": u.license_expires})

    def _profile(self):
        u = self._require()
        if not u:
            return
        b = self._body()
        self.accounts.update_profile(u.username, name=b.get("name"),
                                     post=b.get("post"), theme=b.get("theme"))
        return self._send(200, {"ok": True})

    def _password(self):
        u = self._require()
        if not u:
            return
        b = self._body()
        ok = self.accounts.change_password(u.username, b.get("old_pw", ""), b.get("new_pw", ""))
        return self._send(200, {"ok": ok})

    def _license(self):
        u = self._require()
        if not u:
            return
        b = self._body()
        raw = (b.get("raw") or "").strip()
        if not raw:
            return self._send(400, {"error": "内容为空"})
        try:
            self.accounts.import_license(u.username, raw)
            self.system.audit.record("console", u.username, "license.import", "ok")
            return self._send(200, {"ok": True})
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})

    # ---- session 端点 ----
    def _session_create(self):
        owner = self._owner()
        b = self._body()
        s = self.sessions.create(title=b.get("title") or "新会话", owner=owner)
        return self._send(200, {"session_id": s["id"], "title": s["title"], "cwd": s["cwd"]})

    def _session_list(self):
        owner = self._owner()
        rows = self.sessions.list(owner)
        out = []
        for s in rows:
            out.append({"session_id": s["id"], "title": s["title"], "cwd": s["cwd"],
                        "updated": s["updated_at"], "count": self.sessions.message_count(s["id"])})
        return self._send(200, {"sessions": out})

    def _session_get(self, sid):
        s = self.sessions.get(sid)
        if not s:
            return self._send(404, {"error": "会话不存在"})
        return self._send(200, {"session_id": s["id"], "title": s["title"], "cwd": s["cwd"]})

    def _session_messages(self, sid):
        msgs = self.sessions.messages(sid)
        return self._send(200, {"messages": msgs})

    def _session_add_message(self, sid):
        b = self._body()
        role = b.get("role") or "user"
        content = b.get("content") or ""
        self.sessions.add_message(sid, role, content)
        return self._send(200, {"ok": True})

    def _session_delete(self, sid):
        self.sessions.delete(sid)
        return self._send(200, {"ok": True})

    def _session_search(self):
        owner = self._owner()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
        results = self.sessions.search(q, owner)
        return self._send(200, {"results": results})

    def _session_workdir(self, sid):
        s = self.sessions.get(sid)
        if not s:
            return self._send(404, {"error": "会话不存在"})
        cwd = s["cwd"]
        files = []
        for name in sorted(os.listdir(cwd)):
            p = os.path.join(cwd, name)
            if os.path.isdir(p):
                files.append({"name": name, "type": "d"})
            else:
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    sz = 0
                files.append({"name": name, "type": "f", "size": sz})
        return self._send(200, {"path": cwd, "files": files})

    def _session_upload(self, sid):
        s = self.sessions.get(sid)
        if not s:
            return self._send(404, {"error": "会话不存在"})
        cwd = s["cwd"]
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b""
        # 兼容 multipart 或纯二进制；这里用最简单的方式：文件名从 Content-Disposition 解析
        filename = "upload.bin"
        ct = self.headers.get("Content-Type", "")
        if "multipart" in ct.lower():
            import io, re
            data = body.decode("latin1")
            m = re.search(r'filename="([^"]+)"', data, re.I)
            if m:
                filename = m.group(1)
            marker = ct.split("boundary=")[-1].strip().strip('"')
            try:
                raw = body.split(b"--" + marker.encode())[1]
                header, _, part = raw.partition(b"\r\n\r\n")
                # 取最后一段 body
                chunks = raw.split(b"\r\n\r\n", 1)
                if len(chunks) > 1:
                    # 去掉结尾的 boundary
                    part = chunks[1].split(b"\r\n--" + marker.encode())[0]
                    body = part
                else:
                    body = part
            except Exception:
                pass
        safe = os.path.basename(filename)
        dest = os.path.join(cwd, safe)
        with open(dest, "wb") as f:
            f.write(body)
        # 文本预览
        preview = ""
        ext = os.path.splitext(safe)[1].lower()
        if ext in (".txt", ".md", ".json", ".py", ".js", ".c", ".cpp", ".java", ".html", ".css", ".csv", ".xml", ".yml", ".yaml", ".sh"):
            try:
                preview = body[:2000].decode("utf-8", "replace")
            except Exception:
                preview = ""
        return self._send(200, {"path": dest, "name": safe, "size": len(body), "preview": preview})

    def _session_term(self, sid):
        """终端：在工作目录内执行命令，300ms 超时保护（macOS 无 timeout，用后台+join）。"""
        s = self.sessions.get(sid)
        if not s:
            return self._send(404, {"error": "会话不存在"})
        b = self._body()
        cmd = (b.get("cmd") or "").strip()
        if not cmd:
            return self._send(400, {"error": "命令为空"})
        try:
            proc = subprocess.Popen(
                ["/bin/sh", "-c", cmd], cwd=s["cwd"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
            try:
                out, _ = proc.communicate(timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                out = (out or "") + "\n[超时终止]"
            return self._send(200, {"output": (out or "")[:8000]})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _browser(self):
        # 前端直接 iframe，这里仅记录审计
        u = self._auth()
        return self._send(200, {"ok": True})

    # ---- 知识库（本地文件系统，P1 渐进接入；这里先提供目录浏览骨架）----
    def _kb_root(self) -> str:
        root = os.path.join(os.getcwd(), "knowledge-base")
        os.makedirs(root, exist_ok=True)
        return root

    def _kb_prune(self, rel: str) -> str:
        root = os.path.realpath(self._kb_root())
        target = os.path.realpath(os.path.join(root, rel or ""))
        if not target.startswith(root + os.sep) and target != root:
            raise ValueError("路径越界")
        return target

    def _api_kb_tree(self):
        root = self._kb_root()

        def walk(d):
            out = []
            for name in sorted(os.listdir(d)):
                p = os.path.join(d, name)
                rel = os.path.relpath(p, root)
                if os.path.isdir(p):
                    out.append({"name": name, "path": rel, "type": "d", "children": walk(p)})
                else:
                    out.append({"name": name, "path": rel, "type": "f",
                                "ext": os.path.splitext(name)[1].lstrip(".").lower()})
            return out
        return self._send(200, {"root": root, "tree": walk(root)})

    def _api_kb_branch(self):
        root = self._kb_root()
        rel = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("path", [""])[0]
        try:
            target = self._kb_prune(rel)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        if not os.path.isdir(target):
            return self._send(404, {"error": "非目录"})
        files = []
        for name in sorted(os.listdir(target)):
            p = os.path.join(target, name)
            files.append({"name": name, "path": os.path.relpath(p, root),
                          "type": "d" if os.path.isdir(p) else "f",
                          "ext": os.path.splitext(name)[1].lstrip(".").lower()})
        return self._send(200, {"files": files})

    def _api_kb_search(self):
        root = self._kb_root()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0].lower()
        results = []
        for dp, _, fns in os.walk(root):
            for fn in fns:
                if q and q in fn.lower():
                    rel = os.path.relpath(os.path.join(dp, fn), root)
                    results.append({"name": fn, "path": rel,
                                    "ext": os.path.splitext(fn)[1].lstrip(".").lower()})
        return self._send(200, {"results": results[:100]})

    def _api_kb_file(self):
        root = self._kb_root()
        rel = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("path", [""])[0]
        try:
            target = self._kb_prune(rel)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        if not os.path.isfile(target):
            return self._send(404, {"error": "非文件"})
        content = ""
        ext = os.path.splitext(target)[1].lower()
        kind = self._kb_kind(ext)
        textexts = {".txt", ".md", ".json", ".py", ".js", ".ts", ".c", ".h", ".cpp",
                    ".cc", ".java", ".html", ".htm", ".css", ".csv", ".xml", ".yml",
                    ".yaml", ".sh", ".bash", ".log", ".gitignore", ".toml", ".ini",
                    ".conf", ".sql", ".go", ".rs", ".rb", ".php", ".vue", ".jsx",
                    ".tsx", ".svg"}
        # 二进制友好格式：文本类直接读；图片/音视频给可内联预览的 data URI 元信息
        if ext in textexts:
            try:
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(50000)
            except Exception:
                content = ""
        info = self._kb_binary_info(target, ext, kind)
        return self._send(200, {"content": content, "ext": ext.lstrip("."), "kind": kind,
                                "binary": info})

    @staticmethod
    def _kb_kind(ext: str) -> str:
        ext = ext.lstrip(".").lower()
        img = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "ico", "svg", "tiff", "heic"}
        vid = {"mp4", "avi", "mov", "mkv", "webm", "flv", "wmv", "m4v"}
        aud = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"}
        off = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp", "rtf"}
        code = {"py", "js", "ts", "c", "h", "cpp", "cc", "java", "go", "rs", "rb",
                "php", "sql", "sh", "bash", "vue", "jsx", "tsx", "html", "htm",
                "css", "scss", "less", "json", "xml", "yml", "yaml", "toml", "ini",
                "conf"}
        md = {"md", "markdown", "txt", "log", "csv", "gitignore"}
        if ext in img:
            return "image"
        if ext in vid:
            return "video"
        if ext in aud:
            return "audio"
        if ext in off:
            return "office"
        if ext in code:
            return "code"
        if ext in md:
            return "text"
        return "file"

    @staticmethod
    def _kb_binary_info(path: str, ext: str, kind: str) -> dict | None:
        """返回二进制文件的预览/元信息（内联 data URI 或默认应用打开提示）。"""
        if not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        base: dict = {"size": size}
        if kind in ("image", "video", "audio") and size <= 8 * 1024 * 1024:
            try:
                b = open(path, "rb").read()
                import base64 as _b64
                mime = {"image": {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                                  "gif": "gif", "bmp": "bmp", "webp": "webp",
                                  "svg": "svg+xml", "ico": "x-icon"}.get(
                              os.path.splitext(path)[1].lstrip(".").lower(), "png"),
                        "video": "mp4", "audio": "mpeg"}.get(kind, "octet-stream")
                base["data_uri"] = f"data:{'image/' if kind=='image' else (kind+'/')}{mime};base64,{_b64.b64encode(b).decode()}"
            except Exception:
                pass
        return base

    def _api_kb_new(self):
        root = self._kb_root()
        b = self._body()
        rel = (b.get("path") or "").strip()
        name = (b.get("name") or "").strip()
        typ = b.get("type", "f")
        if not name or "/" in name or "\\" in name:
            return self._send(400, {"error": "非法文件名"})
        try:
            parent = self._kb_prune(rel)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        target = os.path.join(parent, name)
        if typ == "d":
            os.makedirs(target, exist_ok=True)
        else:
            with open(target, "w", encoding="utf-8") as f:
                f.write("")
        return self._send(200, {"ok": True, "path": os.path.relpath(target, root)})

    def _api_kb_open(self):
        b = self._body()
        rel = (b.get("path") or "").strip()
        try:
            target = self._kb_prune(rel)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        if not os.path.isfile(target):
            return self._send(404, {"error": "非文件"})
        try:
            subprocess.Popen(["open", target])
            return self._send(200, {"ok": True})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})

    # ---- do_GET / do_POST ----
    def _info(self) -> None:
        agents = 0
        try:
            agents = len(self.system.api.list_agents())
        except Exception:
            agents = len(self.agent_ids or [])
        self._send(200, {"app": "aimate", "version": "0.1.0", "agents": agents,
                         "default_model": getattr(self.system, "llm_default", "inner-gateway")
                         or "inner-gateway",
                         "agent_ids": self.agent_ids or []})

    def _agents(self) -> None:
        try:
            if hasattr(self.system.api, "list_agents"):
                agents = self.system.api.list_agents()
            else:
                agents = [{"id": a, "name": a, "description": ""}
                          for a in (self.agent_ids or [])]
            self._send(200, {"agents": [{"id": a.get("id", a.get("agent_id", "")),
                                         "name": a.get("name", a.get("id", "")),
                                         "description": a.get("description", "")}
                                        for a in agents]})
        except Exception as e:  # noqa: BLE001
            self._send(200, {"agents": [], "error": str(e)})

    def _kb_docs(self) -> None:
        try:
            if hasattr(self.system, "list_kb_docs"):
                docs = self.system.list_kb_docs()
            else:
                docs = self.system.kb_docs() if hasattr(self.system, "kb_docs") else []
            self._send(200, {"docs": docs})
        except Exception as e:  # noqa: BLE001
            self._send(200, {"docs": [], "error": str(e)})

    def _kb_search_index(self) -> None:
        """RAG 索引检索（向后兼容旧 /api/kb/search POST 契约：hits[kind]）。"""
        b = self._body()
        q = (b.get("q") or "").strip()
        try:
            method = getattr(self.system, "kb_search",
                             getattr(self.system, "search_kb", None))
            results = method(q) if method else []
            hits = []
            for x in results:
                if hasattr(x, "doc_id"):
                    hits.append({"doc_id": x.doc_id, "text": getattr(x, "text", ""),
                                 "kind": getattr(x, "kind", "doc")})
                elif isinstance(x, dict):
                    hits.append({"doc_id": x.get("doc_id"), "text": x.get("text", ""),
                                 "kind": x.get("kind", "doc")})
            self._send(200, {"hits": hits})
        except Exception as e:  # noqa: BLE001
            self._send(200, {"hits": [], "error": str(e)})

    def _mcp_call(self) -> None:
        b = self._body()
        tool = b.get("tool", "")
        args = b.get("args") or {}
        try:
            result = self.system.mcp.call_tool(tool, args)
            self.system.audit.record("console", "tenant-demo", "mcp.call", tool)
            # 兼容 demo__sum 返回 dict
            self._send(200, {"tool": tool, "result": result,
                             "is_dict": isinstance(result, dict)
                             and "sum" in (result if isinstance(result, dict) else {})})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _skills_add(self) -> None:
        b = self._body()
        name = (b.get("name") or "").strip()
        if not name:
            return self._send(400, {"error": "name 必填"})
        from aimate.skills.store import Skill, SkillStatus
        status = SkillStatus((b.get("status") or "published").lower())
        s = Skill(name=name, tenant_id="tenant-demo",
                  description=b.get("description", ""),
                  trigger=b.get("trigger", ""), body=b.get("body", ""),
                  status=status, owner=b.get("owner", "console"))
        self.system.skills.create(s)
        self.system.audit.record("console", "tenant-demo", "skills.create", name)
        return self._send(200, {"name": name, "status": status.value})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/":
                return self._html()
            if path == "/api/info":
                return self._info()
            if path == "/api/agents":
                return self._agents()
            if path == "/api/me":
                return self._me()
            if path == "/api/sessions":
                return self._session_list()
            if path == "/api/sessions/search":
                return self._session_search()
            if path.startswith("/api/sessions/") and path.count("/") == 3 and not path.endswith("messages") and not path.endswith("workdir") and "term" not in path and "upload" not in path:
                return self._session_get(path.split("/")[-1])
            if path.endswith("/messages"):
                return self._session_messages(path.split("/")[-2])
            if path.endswith("/workdir"):
                return self._session_workdir(path.split("/")[-2])
            if path == "/api/skills":
                return self._skills_list()
            if path == "/api/mcp":
                return self._mcp_list()
            if path == "/api/llm":
                return self._llm_list()
            if path == "/api/audit":
                return self._audit()
            if path == "/api/kb/tree":
                return self._api_kb_tree()
            if path == "/api/kb/branch":
                return self._api_kb_branch()
            if path == "/api/kb/search":
                return self._api_kb_search()
            if path == "/api/kb/file":
                return self._api_kb_file()
            if path == "/api/kb/docs":
                return self._kb_docs()
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/register":
                return self._auth_register()
            if path == "/api/login":
                return self._auth_login()
            if path == "/api/profile":
                return self._profile()
            if path == "/api/password":
                return self._password()
            if path == "/api/license":
                return self._license()
            if path == "/api/sessions":
                return self._session_create()
            if path == "/api/chat":
                return self._chat()
            if path.startswith("/api/sessions/") and path.endswith("/messages"):
                return self._session_add_message(path.split("/")[-2])
            if path.startswith("/api/sessions/") and path.endswith("/term"):
                return self._session_term(path.split("/")[-2])
            if path.startswith("/api/sessions/") and path.endswith("/upload"):
                return self._session_upload(path.split("/")[-2])
            if path == "/api/mcp":
                return self._mcp_add()
            if path == "/api/mcp/call":
                return self._mcp_call()
            if path == "/api/kb/search":
                return self._kb_search_index()
            if path == "/api/llm":
                return self._llm_add()
            if path == "/api/kb/new":
                return self._api_kb_new()
            if path == "/api/skills":
                return self._skills_add()
            if path == "/api/kb/open":
                return self._api_kb_open()
            if path == "/api/browser":
                return self._browser()
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path.startswith("/api/sessions/"):
                return self._session_delete(path.split("/")[-1])
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass
# ============================================================ 核心业务方法（补回）
    def _chat(self) -> None:
        """把消息发给默认 LLM 后端并返回回复。

        向后兼容：带 agent_id + 无 LLM 时回退旧 skeleton（echo/agent）；
        否则走新逻辑（messages→reply）。
        """
        b = self._body()
        msgs = b.get("messages") or []
        sid = b.get("session_id")
        agent_id = b.get("agent_id")
        u = self._auth()
        owner = u.username if u else "default"
        if sid:
            try:
                self.sessions.touch(sid)
            except Exception:
                pass
        # 旧契约：显式带 agent_id 且未配真实 LLM → 返回 demo skeleton
        if agent_id and not (self.system.llm._backends or {}):
            if msgs:
                last = msgs[-1].get("content", "")
            else:
                last = ""
            echo = self._skeleton_reply(last)
            self.system.audit.record("console", owner, "chat.send", last[:60])
            return self._send(200, {"echo": echo, "agent": "IT 支持专家",
                                    "agent_id": agent_id})
        last = (msgs[-1].get("content", "") if msgs else "")
        reply = None
        try:
            s = self.system
            backends = list((s.llm._backends or {}).keys())
            if backends:
                alias = getattr(s, "llm_default", None) or backends[0]
                resp = s.llm.chat(alias, msgs)
                try:
                    reply = resp["choices"][0]["message"]["content"]
                except Exception:
                    reply = ""
        except Exception:
            reply = None
        if reply is None or not str(reply).strip():
            reply = self._local_reply(last, owner)
        if sid:
            try:
                self.sessions.add_message(sid, "assistant", str(reply))
                self.sessions.touch(sid)
            except Exception:
                pass
        self.system.audit.record("console", owner, "chat.send",
                                 (msgs[-1].get("content", "") if msgs else "")[:60])
        return self._send(200, {"reply": str(reply)})

    def _skeleton_reply(self, text: str) -> str:
        return (f"（演示回复｜IT 支持专家）收到：{text[:60] or '(空)'}。\n"
                "已完成知识库检索与任务编排，可到右侧面板查看工作目录。")

    def _local_reply(self, text: str, owner: str) -> str:
        t = (text or "").lower()
        if "/use-skill" in t:
            name = t.split("/use-skill")[-1].strip().split()[0] if t.split("/use-skill")[-1].strip() else ""
            try:
                sk = self.system.skills.get(owner or "tenant-demo", name)
                return f"已调用技能「{name}」：\n{getattr(sk, 'body', '')[:300]}"
            except Exception:
                return "未找到该技能。可到左侧「技能库」查看已有技能。"
        if "hello" in t or "你好" in t or "hi" in t:
            return "你好！我是 AIMate。我可以帮你写代码、查知识库、调用 MCP 工具、管理运维任务。"
        if "mcp" in t or "工具" in t:
            try:
                tools = self.system.mcp.list_servers()
                return "已连接的 MCP 工具：\n" + "\n".join(f"- {s['name']}" for s in tools) or "暂无工具"
            except Exception:
                return "MCP 工具未就绪。"
        if "知识库" in t or "kb" in t:
            try:
                n = len(self.system.kb_index())
                return f"当前知识库共 {n} 个知识块。可到「知识库」上传文档后检索。"
            except Exception:
                return "知识库已就位，可上传文档。"
        return ("（未接真实 LLM 时的本地演示回复）\n"
                f"收到：{text}\n到左侧面板可体验：技能库 / MCP 工具 / 知识库 / 模型库注册。\n"
                "在 CLI 端配置好 llama-server 后，此回复会由真实模型生成。")

    def _skills_list(self) -> None:
        skills = self.system.skills.list("tenant-demo")
        self._send(200, {"skills": [{"name": s.name, "description": s.description,
                                     "trigger": s.trigger, "status": s.status.value,
                                     "owner": s.owner, "pinned": s.pinned}
                                    for s in skills]})

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
            try:
                for t in tools:
                    self.system.api.register_tool(
                        {"type": "function",
                         "function": {"name": t["name"],
                                      "description": t.get("description", ""),
                                      "parameters": t.get("inputSchema") or {
                                          "type": "object", "properties": {}}}})
            except Exception:
                pass
            self._send(200, {"name": name, "tools": [f"{name}__{t['name']}" for t in tools]})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _llm_list(self) -> None:
        self._send(200, {"backends": self._llm_backends(),
                         "default": getattr(self.system, "llm_default", None)})

    def _llm_backends(self) -> list[dict]:
        s = self.system
        backends: list[dict] = []
        for alias, b in (s.llm._backends or {}).items():
            backends.append({"alias": alias, "base_url": b.config.base_url,
                             "model": b.config.model, "ready": True})
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
        except Exception as e:
            self._send(500, {"error": str(e)})

    def _audit(self) -> None:
        try:
            events = [{"time": getattr(e, "ts", ""), "action": getattr(e, "action", ""),
                       "actor": getattr(e, "actor", ""), "detail": getattr(e, "detail", "")}
                      for e in self.system.audit.query("tenant-demo")]
            self._send(200, {"events": events[::-1]})
        except Exception as e:
            self._send(500, {"error": str(e)})


def serve(host: str = "127.0.0.1", port: int = 8900, system: Any = None,
          agent_ids: list[str] | None = None) -> ThreadingHTTPServer:
    """起管控台 HTTP 服务，返回 server（调用方决定是否阻塞 serve_forever）。"""
    ConsoleHandler.system = system
    ConsoleHandler.agent_ids = agent_ids or []
    ConsoleHandler.accounts = AccountStore()
    ConsoleHandler.sessions = SessionStore()
    srv = ThreadingHTTPServer((host, port), ConsoleHandler)
    return srv
