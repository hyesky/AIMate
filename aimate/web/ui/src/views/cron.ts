import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-cron')
export class AmCron extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() jobs: any[] = [];
  @state() name=''; @state() expr=''; @state() action='';
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/cron');this.jobs=d.jobs||[];}catch{} }
  async #act(op:any,id?:any){ try{await api('/api/cron',{method:'POST',body:JSON.stringify({op,id,...(op==='add'?{name:this.name,expr:this.expr,action:this.action}:{})})});this.name='';this.expr='';this.action='';await this.#load();}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">定时任务</h2>
      <div class="card" style="padding:16px;margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap">
        <input style="flex:1;min-width:120px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="任务名" .value=${this.name} @input=${(e:any)=>this.name=e.target.value}/>
        <input style="flex:1;min-width:120px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="cron 表达式 如 0 9 * * *" .value=${this.expr} @input=${(e:any)=>this.expr=e.target.value}/>
        <input style="flex:1;min-width:150px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="动作" .value=${this.action} @input=${(e:any)=>this.action=e.target.value}/>
        <button class="btn primary" @click=${()=>this.#act('add')}>添加</button>
      </div>
      ${this.jobs.length===0?html`<div class="empty">暂无定时任务</div>`:html`<div style="display:flex;flex-direction:column;gap:10px">
        ${this.jobs.map(j=>html`<div class="card" style="padding:14px 16px;display:flex;align-items:center;gap:12px">
          <div style="flex:1"><div style="font-weight:600">${j.name||j.id}</div><div style="color:var(--text-secondary);font-size:13px">${j.expr} · 上次 ${j.last_run||'—'} · 下次 ${j.next_run||'—'}</div></div>
          <span style="padding:3px 10px;border-radius:999px;font-size:12px;background:${j.state==='enabled'?'var(--accent-mix)':'var(--row-hover)'};color:${j.state==='enabled'?'var(--accent)':'var(--text-secondary)'}">${j.state}</span>
          <button class="btn" @click=${()=>this.#act(j.state==='enabled'?'disable':'enable',j.id)}>${j.state==='enabled'?'停用':'启用'}</button>
          <button class="btn" @click=${()=>this.#act('delete',j.id)}>删除</button>
        </div>`)}
      </div>`}
    </div>`;}
}
