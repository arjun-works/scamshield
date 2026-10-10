// Tiny wrapper around fetch for the ScamShield backend.
// The base URL comes from VITE_API_URL (see .env.example).
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8080'

async function request(method, path, body) {
  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    // FastAPI puts the reason in "detail".
    const detail = await response.json().then((data) => data.detail).catch(() => null)
    const error = new Error(typeof detail === 'string' ? detail : `${method} ${path} failed: ${response.status}`)
    error.status = response.status
    throw error
  }
  return response.json()
}

export const apiGet = (path) => request('GET', path)
export const apiPost = (path, body = {}) => request('POST', path, body)
