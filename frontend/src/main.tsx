import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@cloudscape-design/global-styles/index.css'
import { applyMode, Mode } from '@cloudscape-design/global-styles'
import './index.css'
import App from './App.tsx'

// Apply Cloudscape dark mode
applyMode(Mode.Dark)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
