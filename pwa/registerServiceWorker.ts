// Installability + service-worker registration foundation (PROMPT-001 S15).
//
// Registering a real, cache-first service worker in DEV mode is a footgun:
// once installed for http://localhost:3000, it keeps serving whatever
// index.html/CSS/JS it cached at install time, regardless of what the dev
// server now returns on disk — every subsequent source edit silently stops
// reaching the browser until that specific SW is manually unregistered.
// (This is exactly what happened in this codebase: a stale SW kept an old
// index.html's scrollbar CSS alive through several source-level fixes.)
// Real offline-shell verification belongs in `npm run build` + `npm run
// preview`, never in `npm run dev`.
export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) {
    return;
  }

  if (!(import.meta as any).env?.PROD) {
    // Actively undo any SW a previous session may have installed for this
    // origin (e.g. from an earlier `vite preview` run on the same port) so
    // dev-mode navigation always hits the live dev server.
    navigator.serviceWorker.getRegistrations().then((registrations) => {
      registrations.forEach((registration) => registration.unregister());
    });
    return;
  }

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((error) => {
      // Registration failure must not break the app; log for diagnostics only.
      console.error('Service worker registration failed', error);
    });
  });
}
