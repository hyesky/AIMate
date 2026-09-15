import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-skills')
export class AmSkills extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() skills:any[]=[];
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/skills');this.skills=d.skills||[];}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">技能库 <span style="font-size:13px;color:var(--text-secondary)">${this.skills.length} 项</span></h2>
      ${this.skills.length===0?html`<div class="empty">暂无技能</div>`:html`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px">
        ${this.skills.map((s:any)=>html`<div class="card" style="padding:16px">
          <div style="display:flex;align-items:center;gap:8px"><span style="font-weight:600;font-size:15px">${s.name}</span><span style="padding:2px 8px;border-radius:999px;background:${s.pinned?'var(--accent-mix)':'var(--row-hover)'};color:${s.pinned?'var(--accent)':'var(--text-secondary)'};font-size:11px">${s.pinned?'已固定':(s.status||'')}</span></div>
          <div style="color:var(--text-secondary);font-size:13px;margin-top:6px;line-height:1.5">${s.description||''}</div>
          <div style="color:var(--text-tertiary);font-size:12px;margin-top:8px">trigger: ${s.trigger||'—'}</div>
        </div>`)}
      </div>`}
    </div>`;}
}
