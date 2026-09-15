import './styles/global.css';
import './views/login.js';

import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { getToken } from './lib/api.js';

interface Me {
  username: string;
  name?: string;
  theme?: string;
}

const NAV: Array<{ page: string; icon: string; label: string }> = [
  { page: 'chat', icon: 'chat', label: '对话' },
  { page: 'workbench', icon: 'grid', label: '工作台' },
  { page: 'cron', icon: 'clock', label: '定时任务' },
  { page: 'market', icon: 'briefcase', label: '员工市场' },
  { page: 'skills', icon: 'puzzle', label: '技能库' },
  { page: 'mcp', icon: 'plug', label: '工具库' },
  { page: 'sessions', icon: 'history', label: '历史会话' },
  { page: 'kb', icon: 'book', label: '知识库' },
  { page: 'models', icon: 'cpu', label: '模型库' },
  { page: 'audit', icon: 'shield', label: '审计' },
];

const ICONS: Record<string, string> = {
  chat: 'M8 10h8M8 14h5m-9 6l4-4h9a2 2 0 002-2V6a2 2 0 00-2-2H4a2 2 0 00-2 2v10a2 2 0 002 2h3l-2 3z',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  clock: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
  briefcase: 'M4 7h16v12a2 2 0 01-2 2H6a2 2 0 01-2-2V7zm3 0V5a2 2 0 012-2h6a2 2 0 012 2v2M2 11h20',
  puzzle: 'M12 3v3M12 21v-3M3 12h3M21 12h-3M12 12l2-2M12 12l-2 2M12 12l2 2M12 12l-2-2',
  plug: 'M4 7h16v3a4 4 0 01-4 4H8a4 4 0 01-4-4V7zm6 10v3m4-3v3',
  history: 'M3 12a9 9 0 109-9 9 9 0 00-4.5 1.2M3 3v5h5M12 7v5l3 2',
  book: 'M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2V5zm0 16a2 2 0 002 2h13',
  cpu: 'M9 3v2M15 3v2M9 19v2M15 19v2M5 9H3M5 15H3M21 9h-2M21 15h-2M7 7h10v10H7z',
  shield: 'M12 3l8 3v6c0 4-3 7-8 9-5-2-8-5-8-9V6l8-3z',
};

@customElement('am-app')
export class AmApp extends LitElement {
  static styles = css`
    :host { display: contents; }
  `;

  @state() me: Me | null = null;
  @state() page = 'chat';

  connectedCallback() {
    super.connectedCallback();
    // 恢复主题
    const saved = localStorage.getItem('am_theme');
    if (saved) document.documentElement.classList.toggle('dark', saved === 'dark');
    this.#fetchMe();
  }

  async #fetchMe() {
    if (!getToken()) return;
    try {
      const r = await fetch('/api/me', { headers: { 'X-Auth-Token': getToken() } });
      if (r.ok) this.me = await r.json();
    } catch { /* ignore */ }
  }

  render() {
    if (!this.me) {
      return html`<am-login @login=${(e: Event) => {
        const d = (e as CustomEvent<Me>).detail;
        this.me = d as Me;
      }}></am-login>`;
    }
    return html`
      <div class="shell">
        <aside class="sidebar">
          <div class="brand"><span class="logo">A</span><span>AIMate</span></div>
          <nav>
            ${NAV.map(n => html`
              <button class="${'navitem' + (this.page === n.page ? ' on' : '')}"
                @click=${() => (this.page = n.page)} title=${n.label}>
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                  stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d=${ICONS[n.icon]} />
                </svg>
                <span>${n.label}</span>
              </button>
            `)}
          </nav>
          <div class="sidefoot">
            <button class="navitem" @click=${this.#logout} title="退出">
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                stroke-width="1.8" stroke-linecap="round"><path d="M15 12H3m0 0l4-4m-4 4l4 4m8-10h4v12h-4" /></svg>
              <span>退出</span>
            </button>
          </div>
        </aside>
        <main class="main">${this.#view()}</main>
      </div>
    `;
  }

  #view() {
    switch (this.page) {
      case 'chat': return html`<am-chat></am-chat>`;
      case 'workbench': return html`<am-workbench></am-workbench>`;
      case 'cron': return html`<am-cron></am-cron>`;
      case 'market': return html`<am-market></am-market>`;
      case 'skills': return html`<am-skills></am-skills>`;
      case 'mcp': return html`<am-mcp></am-mcp>`;
      case 'sessions': return html`<am-sessions></am-sessions>`;
      case 'kb': return html`<am-kb></am-kb>`;
      case 'models': return html`<am-models></am-models>`;
      case 'audit': return html`<am-audit></am-audit>`;
      default: return html`<am-chat></am-chat>`;
    }
  }

  async #logout() {
    localStorage.removeItem('am_token');
    this.me = null;
  }
}

// 组件注册（懒加载各视图）
import('./views/chat.js');
import('./views/workbench.js');
import('./views/cron.js');
import('./views/market.js');
import('./views/skills.js');
import('./views/mcp.js');
import('./views/sessions.js');
import('./views/kb.js');
import('./views/models.js');
import('./views/audit.js');

customElements.whenDefined('am-app').then(() => {
  const root = document.getElementById('app');
  if (root && !root.hasChildNodes()) root.appendChild(new AmApp());
});
