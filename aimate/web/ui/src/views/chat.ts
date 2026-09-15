import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { api, apiStream } from '../lib/api.js';

interface Session { session_id: string; title: string; cwd: string; updated: string; count: number; }
interface Message { role: string; content: string; ts?: string; }
interface Progress { running: boolean; phase?: string; tool?: string; step?: number; total?: number; error?: string; }

@customElement('am-chat')
export class AmChat extends LitElement {
  static styles = css`
    :host { display: flex; flex: 1; min-width: 0; background: var(--bg-chrome); }
    .col {
      display: flex; flex-direction: column; gap: 14px;
      width: 250px; flex-shrink: 0; border-right: 1px solid var(--stroke);
      background: var(--bg-sidebar); padding: 12px; overflow-y: auto;
    }
    .col h4 { margin: 0 4px 4px; font-size: 12px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .04em; }
    .srow {
      padding: 9px 10px; border-radius: var(--radius-sm); cursor: pointer;
      font-size: 13px; color: var(--text-secondary); border: 0; background: none;
      text-align: left; font-family: var(--font); display: block; width: 100%;
    }
    .srow:hover { background: var(--row-hover); color: var(--text-primary); }
    .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .msgs { flex: 1; overflow-y: auto; padding: 24px 40px; display: flex; flex-direction: column; gap: 20px; }
    .msg { display: flex; gap: 12px; max-width: 820px; }
    .msg.user { align-self: flex-end; flex-direction: row-reverse; }
    .avatar {
      width: 30px; height: 30px; border-radius: 50%; color: #fff;
      display: flex; align-items: center; justify-content: center; font-size: 13px;
      flex-shrink: 0; font-weight: 600;
    }
    .msg.user .avatar { background: var(--accent); }
    .msg.assistant .avatar { background: #3b8b5c; }
    .bub {
      padding: 10px 14px; border-radius: var(--radius-lg); font-size: 14px; line-height: 1.6;
      white-space: pre-wrap; word-break: break-word;
      background: var(--bg-card); border: 1px solid var(--stroke); box-shadow: var(--shadow-sm);
    }
    .msg.user .bub { background: var(--accent); color: #fff; border-color: transparent; border-top-right-radius: var(--radius-sm); }
    .msg.assistant .bub { border-top-left-radius: var(--radius-sm); }
    .composer { padding: 12px 24px 20px; border-top: 1px solid var(--stroke); background: var(--bg-chrome); }
    .cbox {
      max-width: 820px; margin: 0 auto; display: flex; align-items: flex-end; gap: 8px;
      background: var(--bg-card); border: 1px solid var(--stroke); border-radius: var(--radius-xl);
      padding: 8px 12px; box-shadow: var(--shadow-sm);
    }
    .cbox:focus-within { border-color: var(--accent); }
    textarea {
      flex: 1; border: 0; background: none; resize: none; font-family: var(--font);
      font-size: 14px; line-height: 1.5; color: var(--text-primary); outline: none; padding: 6px 2px;
      max-height: 140px;
    }
    .send {
      width: 34px; height: 34px; border-radius: 50%; border: 0; background: var(--accent);
      color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
      transition: filter .12s;
    }
    .send:hover { filter: brightness(1.08); }
    .send:disabled { opacity: .5; cursor: default; }
    .status {
      font-size: 12px; color: var(--text-secondary); padding-bottom: 8px; display: flex;
      align-items: center; gap: 8px;
    }
    .spinner {
      width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--stroke);
      border-top-color: var(--accent); animation: spin .7s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .right {
      width: 260px; flex-shrink: 0; border-left: 1px solid var(--stroke);
      background: var(--bg-sidebar); padding: 14px; overflow-y: auto;
    }
    .right h4 { margin: 0 0 8px; font-size: 12px; color: var(--text-secondary); text-transform: uppercase; }
    .frow { font-size: 13px; color: var(--text-primary); padding: 5px 8px; border-radius: var(--radius-sm); font-family: var(--font-mono, monospace); }
  `;

  @state() sessions: Session[] = [];
  @state() active: string | null = null;
  @state() msgs: Message[] = [];
  @state() input = '';
  @state() busying = false;
  @state() running = false;
  @state() files: any[] = [];
  @state() loadedSid: string | null = null;

  connectedCallback() {
    super.connectedCallback();
    this.#loadSessions();
  }

  async #loadSessions() {
    try {
      const d = await api<{ sessions: Session[] }>('/api/sessions');
      this.sessions = d.sessions || [];
      if (this.sessions.length && !this.active) this.#open(this.sessions[0].session_id);
    } catch { /* require login */ }
  }

  async #open(sid: string) {
    this.active = sid;
    this.loadedSid = sid;
    const [m, w] = await Promise.all([
      api<{ messages: Message[] }>(`/api/sessions/${sid}/messages`).catch(() => ({ messages: [] })),
      api<any>(`/api/sessions/${sid}/workdir`).catch(() => ({ files: [] })),
    ]);
    this.msgs = m.messages || [];
    this.files = w.files || [];
  }

  async #newSession() {
    try {
      const d = await api<{ session_id: string }>('/api/sessions', {
        method: 'POST', body: JSON.stringify({ title: '新会话' }),
      });
      await this.#loadSessions();
      if (d.session_id) this.#open(d.session_id);
    } catch { /* ignore */ }
  }

  #onInput(e: Event) { this.input = (e.target as HTMLTextAreaElement).value; }

  #sendKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.#send(); }
  }

  async #send() {
    const text = this.input.trim();
    if (!text || this.busying) return;
    this.input = '';
    let sid = this.active;
    if (!sid) {
      const d = await api<{ session_id: string }>('/api/sessions', { method: 'POST', body: JSON.stringify({ title: text.slice(0, 20) }) });
      sid = d.session_id;
      await this.#loadSessions();
      this.active = sid;
      this.loadedSid = sid;
    }
    this.msgs = [...this.msgs, { role: 'user', content: text }, { role: 'assistant', content: '' }];
    this.busying = true;
    this.running = true;
    this.requestUpdate();
    // 滚动到底
    await this.#scroll();
    try {
      // 拉进度
      const poll = setInterval(async () => {
        try {
          const p = await api<Progress>(`/api/chat/status?sid=${sid}`);
          await this.#setProgress(p);
          if (!p.running) clearInterval(poll);
        } catch { clearInterval(poll); }
      }, 900);
      const r = await apiStream('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ messages: [{ role: 'user', content: text }], session_id: sid, agent_id: '' }),
      });
      const j = await r.json();
      this.msgs = this.msgs.map(m => m.content === '' ? { ...m, role: 'assistant', content: j.reply || j.echo || (j.error || '') } : m);
      if (j.progress) await this.#setProgress(j.progress);
    } catch (e: any) {
      this.msgs = this.msgs.map(m => m.content === '' ? { ...m, content: '出错了：' + (e.message || '') } : m);
    }
    this.busying = false;
    this.running = false;
    await this.#refreshWorkdir(sid);
    await this.#scroll();
  }

  async #setProgress(p: Progress) {
    // 更新最后一条 (running indicator via status bar) ——简单起见仅存档
    this.statusText = p.running ? `任务运行中 · ${p.phase || ''}${p.tool ? ' · ' + p.tool : ''}` : '';
    this.requestUpdate();
  }
  @state() statusText = '';

  async #refreshWorkdir(sid: string) {
    if (sid !== this.active) return;
    const w = await api<any>(`/api/sessions/${sid}/workdir`).catch(() => ({ files: this.files }));
    this.files = w.files || this.files;
  }

  #scroll() {
    const el = this.shadowRoot!.querySelector('.msgs');
    return new Promise<void>((resolve) => requestAnimationFrame(() => {
      if (el) el.scrollTop = el.scrollHeight;
      resolve();
    }));
  }

  render() {
    return html`
      <div class="col">
        <h4>会话</h4>
        <button class="srow" style="color:var(--accent);font-weight:600" @click=${this.#newSession}>＋ 新建会话</button>
        ${this.sessions.map(s => html`
          <button class="srow" style=${this.active === s.session_id ? 'background:var(--accent-mix);color:var(--accent);font-weight:600' : ''}
            @click=${() => this.#open(s.session_id)} title=${s.title}>
            ${s.title}
          </button>
        `)}
      </div>
      <div class="main">
        <div class="msgs">
          ${this.msgs.length === 0 ? html`<div class="empty">开始与 AIMate 对话</div>` : ''}
          ${this.msgs.map(m => html`
            <div class="msg ${m.role}">
              <div class="avatar">${m.role === 'assistant' ? 'A' : 'ME'}</div>
              <div class="bub">${m.content || (this.busying && m.role === 'assistant' ? '…' : '')}</div>
            </div>
          `)}
        </div>
        <div class="composer">
          ${this.statusText ? html`<div class="status"><span class="spinner"></span>${this.statusText}</div>` : ''}
          <div class="cbox">
            <textarea .value=${this.input} @input=${this.#onInput} @keydown=${this.#sendKey}
              placeholder="发送消息给 AIMate…（Shift+Enter 换行）" rows="1"></textarea>
            <button class="send" @click=${this.#send} ?disabled=${this.busying || !this.input.trim()}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
            </button>
          </div>
        </div>
      </div>
      <div class="right">
        <h4>工作目录</h4>
        ${this.files.length === 0 ? html`<div class="empty" style="padding:20px">暂无文件</div>` : this.files.map((f: any) => html`<div class="frow">${f.type === 'd' ? '📁' : '📄'} ${f.name}</div>`)}
      </div>
    `;
  }
}
