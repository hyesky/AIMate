import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-audit')
export class AmAudit extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() events:any[]=[];
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/audit');this.events=d.events||[];}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">审计日志</h2>
      ${this.events.length===0?html`<div class="empty">暂无审计事件</div>`:html`<div style="display:flex;flex-direction:column;gap:8px">
        ${this.events.map((e:any)=>html`<div class="card" style="padding:12px 14px;display:flex;gap:14px;align-items:center">
          <span style="color:var(--text-tertiary);font-size:12px;font-family:monospace;white-space:nowrap">${e.time||''}</span>
          <span style="padding:2px 10px;border-radius:999px;background:var(--accent-mix);color:var(--accent);font-size:12px;white-space:nowrap">${e.action||''}</span>
          <span style="color:var(--text-primary);font-size:13px">${e.detail||''}</span>
        </div>`)}
      </div>`}
    </div>`;}
}
