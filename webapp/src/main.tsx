import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { AgentPage } from './components/AgentPage'
import './styles/global.css'

// A private agent link (?agent=<token>) opens that person's own agent instead of the shared app.
const agentToken = new URLSearchParams(window.location.search).get('agent')

createRoot(document.getElementById('root')!).render(
  <StrictMode>{agentToken ? <AgentPage token={agentToken} /> : <App />}</StrictMode>,
)

// Offline shell + installability, production builds only (no stale caches while developing).
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}))
}
