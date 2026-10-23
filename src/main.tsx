import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles.css'

createRoot(document.getElementById('root')!).render(<App />)

// Service worker enables install-to-home-screen and an offline app shell.
// Registered in production only so it never interferes with Vite dev/HMR.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // Installation still works without the service worker; offline
      // support is a progressive enhancement, not a hard requirement.
    })
  })
}
