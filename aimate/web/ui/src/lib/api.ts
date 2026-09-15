// 共享 API 封装：统一注入 X-Auth-Token（与旧前端 localStorage 键兼容）
const TOKEN_KEY = 'am_token';

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(t: string) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> || {}),
  };
  const tok = getToken();
  if (tok) headers['X-Auth-Token'] = tok;
  const r = await fetch(path, { ...init, headers });
  const isJson = (r.headers.get('content-type') || '').includes('json');
  const data = isJson ? await r.json() : null;
  if (!r.ok) {
    const msg = data?.error || r.statusText || '请求失败';
    const err: any = new Error(msg);
    err.status = r.status;
    err.data = data;
    throw err;
  }
  return data as T;
}

// 带认证的流式 POST（SSE/文本流）。返回 Response 供调用方逐块读。
export async function apiStream(path: string, init: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> || {}),
  };
  const tok = getToken();
  if (tok) headers['X-Auth-Token'] = tok;
  return fetch(path, { ...init, headers });
}
