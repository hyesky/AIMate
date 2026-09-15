import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';
@customElement('am-mcp')
export class AmMcp extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() servers:any[]=[]; @state() tc=0; @state() name=''; @state() cmd='';
  connectedCallback(){super.connectedCallback();this.#load();}
  async #load(){ try{const d=await api('/api/mcp');this.servers=d.servers||[];this.tc=d.tool_count||0;}catch{} }
  async #add(){ const cmd=this.cmd.split(' ').filter(Boolean); if(!this.name||!cmd.length)return; try{await api('/api/mcp',{method:'POST',body:JSON.stringify({name:this.name,cmd})});this.name='';this.cmd='';await this.#load();}catch{} }
  render(){return html`
    <div class="page" style="width:100%">
      <h2 style="margin-top:0">工具库（MCP）</h2>
      <div style="color:var(--text-secondary);font-size:13px;margin-bottom:14px">已注册工具：<b style="color:var(--accent)">${this.tc}</b></div>
      <div class="card" style="padding:16px;margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap">
        <input style="flex:1;min-width:120px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="服务器名" .value=${this.name} @input=${(e:any)=>this.name=e.target.value}/>
        <input style="flex:1;min-width:180px;padding:8px 10px;border-radius:8px;border:1px solid var(--stroke);background:var(--bg-elevated);color:var(--text-primary);font-family:var(--font)" placeholder="启动命令 例 /usr/bin/env node /x/mcp.js" .value=${this.cmd} @input=${(e:any)=>this.cmd=e.target.value}/>
        <button class="btn primary" @click=${this.#add}>连接</button>
      </div>
      ${this.servers.length===0?html`<div class="empty">暂无 MCP 服务器</div>`:html`<div style="display:flex;flex-direction:column;gap:10px">
        ${this.servers.map((s:any)=>html`<div class="card" style="padding:14px 16px"><div style="font-weight:600">${s.name||s.id}</div><div style="color:var(--text-secondary);font-size:13px;margin-top:4px">${(s.cmd||[]).join(' ')}</div></div>`)}
      </div>`}
    </div>`;}
}
