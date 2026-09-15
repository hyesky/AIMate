import { html, css, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { setToken } from '../lib/api.js';

@customElement('am-login')
export class AmLogin extends LitElement {
  static styles = css`
    :host {
      display: flex; align-items: center; justify-content: center;
      height: 100vh; background: var(--bg-chrome);
    }
    .box {
      width: 360px; padding: 32px; border-radius: var(--radius-xl);
      background: var(--bg-card); border: 1px solid var(--stroke);
      box-shadow: var(--shadow-md);
    }
    .brand { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; font-weight: 700; font-size: 18px; }
    .logo { width: 36px; height: 36px; border-radius: 10px; background: var(--accent); color: #fff;
      display: flex; align-items: center; justify-content: center; font-size: 20px; }
    .field { margin-bottom: 14px; }
    .field label { display: block; font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; }
    .field input {
      width: 100%; padding: 10px 12px; font-size: 14px; border-radius: var(--radius-sm);
      border: 1px solid var(--stroke); background: var(--bg-elevated); color: var(--text-primary);
      font-family: var(--font); outline: none;
    }
    .field input:focus { border-color: var(--accent); }
    .err { color: #e12828; font-size: 13px; margin-bottom: 10px; min-height: 18px; }
    .row { display: flex; gap: 8px; }
    .row .btn { flex: 1; }
    .link { background: none; border: 0; color: var(--accent); cursor: pointer; font-size: 13px; margin-top: 12px; font-family: var(--font); }
  `;

  @state() mode: 'login' | 'register' = 'login';
  @state() err = '';

  render() {
    return html`
      <div class="box">
        <div class="brand"><span class="logo">A</span><span>AIMate 管控台</span></div>
        <div class="field"><label>用户名</label><input .value=${this.user} @input=${this.#onUser} autocomplete="username" /></div>
        <div class="field"><label>密码</label><input type="password" .value=${this.pass} @input=${this.#onPass} @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.#submit()} autocomplete="current-password" /></div>
        ${this.mode === 'register' ? html`
          <div class="field"><label>姓名（选填）</label><input .value=${this.name_} @input=${this.#onName} /></div>
          <div class="field"><label>岗位（选填）</label><input .value=${this.post} @input=${this.#onPost} /></div>
        ` : ''}
        <div class="err">${this.err}</div>
        <div class="row">
          <button class="btn primary" @click=${this.#submit}>${this.mode === 'login' ? '登 录' : '注 册'}</button>
        </div>
        <button class="link" @click=${this.#toggle}>${this.mode === 'login' ? '注册使用' : '返回登录'}</button>
      </div>
    `;
  }

  @state() user = '';
  @state() pass = '';
  @state() name_ = '';
  @state() post = '';

  #onUser(e: Event) { this.user = (e.target as HTMLInputElement).value; }
  #onPass(e: Event) { this.pass = (e.target as HTMLInputElement).value; }
  #onName(e: Event) { this.name_ = (e.target as HTMLInputElement).value; }
  #onPost(e: Event) { this.post = (e.target as HTMLInputElement).value; }
  #toggle() { this.mode = this.mode === 'login' ? 'register' : 'login'; this.err = ''; }

  async #submit() {
    this.err = '';
    try {
      if (this.mode === 'login') {
        const r = await fetch('/api/login', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: this.user, password: this.pass }),
        });
        const d = await r.json();
        if (!r.ok) { this.err = d.error || '登录失败'; return; }
        setToken(d.token);
        this.dispatchEvent(new CustomEvent('login', { detail: { username: d.username, name: d.name, theme: d.theme } }));
      } else {
        const r = await fetch('/api/register', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: this.user, password: this.pass, name: this.name_, post: this.post }),
        });
        const d = await r.json();
        if (!r.ok) { this.err = d.error || '注册失败'; return; }
        this.mode = 'login'; this.err = '注册成功，请登录';
      }
    } catch {
      this.err = '网络错误';
    }
  }
}
