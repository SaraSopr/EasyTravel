import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

const root = document.getElementById('root')
if (!root) throw new Error('Root element not found')

// NOTE: React.StrictMode is intentionally omitted. Its dev-only double-mount
// (mount → unmount → remount) leaves react-leaflet with a stale "ghost" map
// instance in the DOM, which shows up as a second, offset map underneath the
// real one. Drop-in StrictMode again only if react-leaflet fixes this.
createRoot(root).render(<App />)
