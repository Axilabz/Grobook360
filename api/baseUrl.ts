// Single source of truth for the backend API base URL.
//
// - Set VITE_API_BASE_URL at BUILD time for any deployed frontend, e.g.
//   VITE_API_BASE_URL=https://api.example.com/api/v1
// - `npm run dev` falls back to the local backend on :8000.
// - A production build with no VITE_API_BASE_URL falls back to the same
//   origin ("/api/v1", i.e. a reverse proxy in front of both), never to
//   localhost — a deployed site must not call the visitor's own machine.

const configured: string | undefined = (import.meta as any).env?.VITE_API_BASE_URL;
const isDev: boolean = Boolean((import.meta as any).env?.DEV);

export const API_BASE_URL: string = (configured && configured.trim()) || (isDev ? 'http://localhost:8000/api/v1' : '/api/v1');
