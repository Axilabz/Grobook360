// Vite resolves image imports (png/jpg/svg/etc.) to a URL string at build
// time — this project has no vite-env.d.ts to declare that for TypeScript,
// so static image imports (e.g. leaflet's marker icon assets in
// shared/CustomerLocationMap.tsx) fail type-checking without this.
declare module '*.png' {
  const src: string;
  export default src;
}
declare module '*.jpg' {
  const src: string;
  export default src;
}
declare module '*.svg' {
  const src: string;
  export default src;
}
