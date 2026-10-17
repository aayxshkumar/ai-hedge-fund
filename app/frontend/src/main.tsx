import React from 'react';
import ReactDOM from 'react-dom/client';

import App from './App';
import { NodeProvider } from './contexts/node-context';
import { ThemeProvider } from './providers/theme-provider';

import './index.css';

// Kite Connect may redirect straight back to the frontend (?request_token=...).
// When that happens inside the login popup, hand the token to the main window
// and close; the Settings page exchanges it. Outside a popup, just clean the URL
// so a stale token never lingers in the address bar.
(() => {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('request_token');
  if (!token) return;
  if (window.opener) {
    try { window.opener.postMessage({ type: 'kite-login-token', request_token: token }, window.location.origin); } catch { /* ignore */ }
    window.close();
  }
  window.history.replaceState({}, '', window.location.pathname);
})();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <NodeProvider>
        <App />
      </NodeProvider>
    </ThemeProvider>
  </React.StrictMode>
);
