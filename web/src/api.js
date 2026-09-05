/** API 封装：全部走 /api（vite 代理或 FastAPI 同源） */

async function req(method, url, body) {
  const opt = { method, headers: {} }
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json'
    opt.body = JSON.stringify(body)
  }
  const res = await fetch(url, opt)
  if (!res.ok) {
    let detail = `${res.status}`
    try { detail = (await res.json()).detail || detail } catch { /* ignore */ }
    throw new Error(`接口错误 ${url}: ${detail}`)
  }
  return res.json()
}

export const api = {
  listTemplates: () => req('GET', '/api/templates'),
  refreshTemplates: () => req('POST', '/api/templates/refresh'),
  schema: (tid) => req('GET', `/api/templates/${encodeURIComponent(tid)}/schema`),
  run: (template_id, params, name = '') => req('POST', '/api/run', { template_id, params, name }),
  runBatch: (template_id, items) => req('POST', '/api/run-batch', { template_id, items }),
  getProject: () => req('GET', '/api/project'),
  putProject: (doc) => req('PUT', '/api/project', doc),
  saveProject: (path) => req('POST', '/api/project/save', { path }),
  loadProject: (path) => req('POST', '/api/project/load', { path }),
  hashCheck: () => req('GET', '/api/hash-check'),
  render: (md) => req('POST', '/api/render', { md }),
  exportHtml: (md, title, meta, inline_assets = false) =>
    req('POST', '/api/export/html', { md, title, meta, inline_assets }),
}
