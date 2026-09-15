import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-market')
export class AmMarket extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() agents:any[]=[];
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/agents');this.agents=d.agents||[];}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">员工市场</h2>
      ${this.agents.length===0?html`<div class="empty">暂无已入职数字员工</div>`:html`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px">
        ${this.agents.map((a:any)=>html`<div class="card" style="padding:18px">
          <div style="font-weight:600;font-size:15px">${a.name||a.id}</div>
          <div style="color:var(--text-secondary);font-size:13px;margin-top:4px">${a.post||a.role||''}</div>
          <div style="margin-top:12px"><span style="padding:3px 10px;border-radius:999px;background:var(--accent-mix);color:var(--accent);font-size:12px">在职</span></div>
        </div>`)}
      </div>`}
    </div>`;}
}
