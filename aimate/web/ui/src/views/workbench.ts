import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api } from '../lib/api.js';

@customElement('am-workbench')
export class AmWorkbench extends LitElement {
  static styles = css`:host{display:flex;flex:1;min-width:0}`;
  @state() data: any = {};
  connectedCallback() { super.connectedCallback(); this.#load(); }
  async #load() {
    try { this.data = await api('/api/agents').catch(() => ({})); } catch { /* ignore */ }
    this.requestUpdate();
  }
  render() {
    const items = this.data.data || this.data.agents || [];
    return html`
      <div class="page" style="width:100%">
        <h2 style="margin-top:0">工作台</h2>
        ${(Array.isArray(items) ? items : []).length === 0
          ? html`<div class="empty">暂无数字员工</div>`
          : html`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px">
              ${(Array.isArray(items) ? items : []).map((a: any) => html`
                <div class="card" style="padding:18px">
                  <div style="font-weight:600;font-size:15px">${a.name || a.id || '员工'}</div>
                  <div style="color:var(--text-secondary);font-size:13px;margin-top:6px">${a.post || a.role || ''}</div>
                  <div style="margin-top:12px">
                    <span style="padding:3px 10px;border-radius:999px;background:${(a.status ?? 'ok') === 'ok' ? 'var(--accent-mix)' : 'var(--row-hover)'};color:${(a.status ?? 'ok') === 'ok' ? 'var(--accent)' : 'var(--text-secondary)'};font-size:12px">${a.status ?? 'ok'}</span>
                  </div>
                </div>
              `)}
            </div>`}
      </div>
    `;
  }
}
