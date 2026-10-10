import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes } from 'react-router-dom'
import { apiGet } from './api.js'
import Customer from './pages/Customer.jsx'
import Analyst from './pages/Analyst.jsx'

// Small badge showing whether the backend is reachable (polls /health).
function BackendStatus() {
  const [status, setStatus] = useState('checking')

  useEffect(() => {
    const check = () =>
      apiGet('/health')
        .then(() => setStatus('online'))
        .catch(() => setStatus('offline'))
    check()
    const timer = setInterval(check, 10000)
    return () => clearInterval(timer)
  }, [])

  const color =
    status === 'online' ? 'bg-green-500' : status === 'offline' ? 'bg-red-500' : 'bg-gray-400'
  return (
    <span className="flex items-center gap-2 text-sm text-slate-600">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${color}`} />
      <span className="sr-only sm:not-sr-only">API {status}</span>
    </span>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="flex h-14 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4">
        <span className="font-semibold">ScamShield</span>
        <nav aria-label="Demo views" className="flex items-center gap-4 text-sm">
          <Link to="/customer" className="py-2 hover:underline">Customer<span className="hidden sm:inline"> app</span></Link>
          <Link to="/analyst" className="py-2 hover:underline">Analyst<span className="hidden sm:inline"> console</span></Link>
          <BackendStatus />
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Navigate to="/customer" replace />} />
        <Route path="/customer" element={<Customer />} />
        <Route path="/analyst" element={<Analyst />} />
      </Routes>
    </div>
  )
}
