import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-models')
export class AmModels extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() backends:any[]=[]; @state() name=''; @state() base=''; @state() model='';
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/llm');this.backends=d.backends||[];}catch{} }
  async #add(){ if(!this.name||!this.base)return; try{await api('/api/llm',{method:'POST',body:JSON.stringify({name:this.name,base_url:this.base,model:this.model||''})});this.name='';this.base='';this.model='';await this.#load();}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">模型库</h2>
      <div class="card" style="padding:16px;margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap">
        <input style="flex:1;min-width:110px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="别名" .value=${this.name} @input=${(e:any)=>this.name=e.target.value}/>
        <input style="flex:1;min-width:180px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="Base URL" .value=${this.base} @input=${(e:any)=>this.base=e.target.value}/>
        <input style="flex:1;min-width:140px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="模型名（选填）" .value=${this.model} @input=${(e:any)=>this.model=e.target.value}/>
        <button class="btn primary" @click=${this.#add}>添加</button>
      </div>
      ${this.backends.length===0?html`<div class="empty">暂无模型</div>`:html`<div style="display:flex;flex-direction:column;gap:10px">
        ${this.backends.map((b:any)=>html`<div class="card" style="padding:14px 16px"><div style="font-weight:600">${b.alias}</div><div style="color:var(--text-secondary);font-size:13px;margin-top:4px">${b.base_url}${b.model?' · '+b.model:''}</div></div>`)}
      </div>`}
    </div>`;}
}
