import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-sessions')
export class AmSessions extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() sessions:any[]=[]; @state() q='';
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/sessions');this.sessions=d.sessions||[];}catch{} }
  async #search(){ const q=this.q.trim(); if(!q){this.#load();return;} try{const d=await api('/api/sessions/search?q='+encodeURIComponent(q)); this.sessions=(d.results||[]).map((r:any)=>({session_id:r.id,title:r.title,updated:r.updated}));}catch{} if(q!==this.q)return; }
  async #del(id:any){ try{await api('/api/sessions/'+id,{method:'DELETE'});await this.#load();}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">历史会话</h2>
      <input style="width:100%;padding:9px 12px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font);margin-bottom:16px" placeholder="搜索会话…" .value=${this.q} @input=${(e:any)=>this.q=e.target.value} @keydown=${(e:any)=>e.key==='Enter'&&this.#search()}/>
      ${this.sessions.length===0?html`<div class="empty">暂无会话</div>`:html`<div style="display:flex;flex-direction:column;gap:10px">
        ${this.sessions.map((s:any)=>html`<div class="card" style="padding:14px 16px;display:flex;align-items:center;gap:12px">
          <div style="flex:1"><div style="font-weight:600">${s.title}</div><div style="color:var(--text-secondary);font-size:13px">${s.updated||''} · ${s.count||0} 条</div></div>
          <button class="btn" @click=${()=>this.#del(s.session_id)}>删除</button>
        </div>`)}
      </div>`}
    </div>`;}
}
