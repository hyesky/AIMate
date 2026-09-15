import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-kb')
export class AmKb extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() tree:any[]=[]; @state() root='';
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/kb/tree');this.tree=d.tree||[];this.root=d.root||'';}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">知识库</h2>
      <div style="color:var(--text-secondary);font-size:13px;margin-bottom:14px">${this.root||''}</div>
      ${this.tree.length===0?html`<div class="empty">知识库为空</div>`:html`<div class="card" style="padding:14px">
        ${this.#renderTree(this.tree)}
      </div>`}
    </div>`;}
  #renderTree(nodes:any[]):any{
    return html`<div style="display:flex;flex-direction:column;gap:3px">
      ${nodes.map((n:any)=>html`<div style="padding:5px 8px;border-radius:6px;display:flex;gap:8px;font-size:14px">
        <span>${n.type==='d'?'📁':'📄'}</span><span>${n.name}</span>
        <span style="color:var(--text-tertiary);font-size:12px">${n.ext?'· '+n.ext:''}</span>
      </div>${n.children?this.#renderTree(n.children):''}`)}
    </div>`;
  }
}
