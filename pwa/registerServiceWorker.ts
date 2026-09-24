// Installability + service-worker registration foundation (PROMPT-001 S15).

export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) {
    return;
  }
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((error) => {
      // Registration failure must not break the app; log for diagnostics only.
      console.error('Service worker registration failed', error);
    });
  });
}
