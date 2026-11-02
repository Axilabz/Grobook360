import React, { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';

interface LoadingStateProps {
  label?: string;
  /** Smaller logo card, no dots/label — for selectors, inline lists, overlays. */
  compact?: boolean;
  /** Kept for call-site compatibility; full-size loaders are now always a centred overlay. */
  bare?: boolean;
}

// Branded loader: the logo (white lettering) on a brand-blue card with a
// pulse + light sweep, and three bouncing dots. Used by every screen/list
// that shows <LoadingState />. Motion is disabled for reduced-motion users.
const LOADER_CSS = `
@keyframes gbPulse { 0%,100% { transform: scale(1); opacity: .9; } 50% { transform: scale(1.07); opacity: 1; } }
@keyframes gbSweep { 0% { transform: translateX(-120%) skewX(-18deg); } 100% { transform: translateX(320%) skewX(-18deg); } }
@keyframes gbDot { 0%,80%,100% { transform: translateY(0); opacity: .35; } 40% { transform: translateY(-6px); opacity: 1; } }
.gb-logo { animation: gbPulse 1.6s ease-in-out infinite; }
.gb-sweep { animation: gbSweep 1.8s ease-in-out infinite; }
.gb-dot { animation: gbDot 1.2s ease-in-out infinite; }
@keyframes gbFade { from { opacity: 0; } to { opacity: 1; } }
.gb-fade { animation: gbFade .15s ease-out; }
@media (prefers-reduced-motion: reduce) { .gb-logo, .gb-sweep, .gb-dot { animation: none; } }
`;

const Card: React.FC<{ compact: boolean; label: string }> = ({ compact, label }) => (
  <div className={`flex flex-col items-center justify-center text-gray-500 dark:text-gray-400 ${compact ? 'gap-2' : 'gap-4'}`}>
    <div className={`relative overflow-hidden bg-[#0066ff] shadow-lg shadow-blue-500/30 ${compact ? 'rounded-xl px-4 py-2.5' : 'rounded-2xl px-7 py-5'}`}>
      <img src="/logo.png" alt="GroBook 360" className={`gb-logo block w-auto ${compact ? 'h-4' : 'h-6 md:h-7'}`} draggable={false} />
      <span aria-hidden="true" className="gb-sweep pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-white/25" />
    </div>
    {!compact && (
      <>
        <div className="flex items-center gap-1.5" aria-hidden="true">
          <span className="gb-dot h-2 w-2 rounded-full bg-[#0066ff]" style={{ animationDelay: '0s' }} />
          <span className="gb-dot h-2 w-2 rounded-full bg-[#0066ff]" style={{ animationDelay: '0.15s' }} />
          <span className="gb-dot h-2 w-2 rounded-full bg-[#0066ff]" style={{ animationDelay: '0.3s' }} />
        </div>
        {label && <p className="text-sm font-medium">{label}</p>}
      </>
    )}
  </div>
);

// ---------------------------------------------------------------------------
// Full-size loaders do NOT render themselves. Each <LoadingState /> registers
// with one shared store and a single <LoadingHost /> (mounted once in
// index.tsx) draws the overlay. That is what prevents the "loading ->
// flash of unblurred page -> loading again" glitch when one loader hands over
// to the next (e.g. lazy screen chunk -> that screen's own data load):
//   * the overlay appears only after SHOW_DELAY_MS (quick loads never flash),
//   * but if another loader was visible a moment ago it re-appears at once,
//   * and it stays HIDE_GRACE_MS after the last loader ends, bridging hand-offs.
// ---------------------------------------------------------------------------
const SHOW_DELAY_MS = 120;
const HIDE_GRACE_MS = 220;
const RECENT_MS = 450;

const active = new Map<string, string>();
const listeners = new Set<() => void>();
let snapshot = { count: 0, label: 'Loading…' };

function publish(): void {
  const labels = Array.from(active.values());
  snapshot = { count: active.size, label: labels.length ? labels[labels.length - 1] : snapshot.label };
  listeners.forEach((l) => l());
}
function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
const getSnapshot = () => snapshot;

export const LoadingHost: React.FC = () => {
  const { count, label } = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const [shown, setShown] = useState(false);
  const [hiddenAt, setHiddenAt] = useState(0);

  useEffect(() => {
    if (count > 0) {
      if (shown) return;
      const delay = Date.now() - hiddenAt < RECENT_MS ? 0 : SHOW_DELAY_MS;
      const t = setTimeout(() => setShown(true), delay);
      return () => clearTimeout(t);
    }
    if (!shown) return;
    const t = setTimeout(() => {
      setShown(false);
      setHiddenAt(Date.now());
    }, HIDE_GRACE_MS);
    return () => clearTimeout(t);
  }, [count, shown, hiddenAt]);

  if (!shown || typeof document === 'undefined') return null;
  return createPortal(
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="gb-fade fixed inset-0 z-[200] flex items-center justify-center bg-white/45 backdrop-blur-md dark:bg-gray-950/55"
    >
      <style>{LOADER_CSS}</style>
      <Card compact={false} label={label} />
    </div>,
    document.body,
  );
};

// compact  -> small inline loader (dropdown lists, selectors).
// otherwise -> registers with the shared overlay above (renders nothing itself).
const LoadingState: React.FC<LoadingStateProps> = ({ label = 'Loading…', compact = false }) => {
  const id = useId();
  useEffect(() => {
    if (compact) return;
    active.set(id, label);
    publish();
    return () => {
      active.delete(id);
      publish();
    };
  }, [id, label, compact]);

  if (compact) {
    return (
      <div role="status" aria-live="polite" className="flex justify-center py-2">
        <style>{LOADER_CSS}</style>
        <Card compact label={label} />
      </div>
    );
  }
  return null;
};

export default LoadingState;
