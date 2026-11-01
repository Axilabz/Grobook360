// Circular logo cropper: drag to reposition, slider to zoom, then "Save"
// exports the visible square as a 512x512 PNG File. No third-party crop
// library — just a <canvas>.
import React, { useEffect, useRef, useState } from 'react';
import { X, ZoomIn } from 'lucide-react';

const BOX = 288;      // on-screen crop box (px)
const OUTPUT = 512;   // exported image size (px)

interface LogoCropModalProps {
  file: File;
  onCancel: () => void;
  onConfirm: (cropped: File) => void | Promise<void>;
}

const LogoCropModal: React.FC<LogoCropModalProps> = ({ file, onCancel, onConfirm }) => {
  const [src, setSrc] = useState<string | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);              // 1 = image just covers the box
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [saving, setSaving] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const drag = useRef<{ px: number; py: number; ox: number; oy: number } | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const baseScale = natural ? BOX / Math.min(natural.w, natural.h) : 1;
  const scale = baseScale * zoom;

  const clamp = (x: number, y: number, s: number) => {
    if (!natural) return { x, y };
    const maxX = Math.max(0, (natural.w * s - BOX) / 2);
    const maxY = Math.max(0, (natural.h * s - BOX) / 2);
    return { x: Math.min(maxX, Math.max(-maxX, x)), y: Math.min(maxY, Math.max(-maxY, y)) };
  };

  const onZoom = (z: number) => {
    setZoom(z);
    setOffset((o) => clamp(o.x, o.y, baseScale * z));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { px: e.clientX, py: e.clientY, ox: offset.x, oy: offset.y };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    setOffset(clamp(drag.current.ox + e.clientX - drag.current.px, drag.current.oy + e.clientY - drag.current.py, scale));
  };
  const onPointerUp = () => { drag.current = null; };

  const handleSave = async () => {
    if (!natural || !imgRef.current) return;
    setSaving(true);
    try {
      const canvas = document.createElement('canvas');
      canvas.width = OUTPUT; canvas.height = OUTPUT;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Canvas unavailable');
      const k = OUTPUT / BOX;
      const w = natural.w * scale * k;
      const h = natural.h * scale * k;
      ctx.drawImage(imgRef.current, OUTPUT / 2 + offset.x * k - w / 2, OUTPUT / 2 + offset.y * k - h / 2, w, h);
      const blob: Blob | null = await new Promise((res) => canvas.toBlob(res, 'image/png'));
      if (!blob) throw new Error('Could not export image');
      await onConfirm(new File([blob], 'logo.png', { type: 'image/png' }));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div role="dialog" aria-label="Crop logo" className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-sm border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 dark:border-gray-700">
          <h3 className="text-[16px] font-semibold text-gray-800 dark:text-gray-100">Crop Logo</h3>
          <button onClick={onCancel} aria-label="Close" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-5 flex flex-col items-center gap-4">
          <div
            className="relative overflow-hidden bg-gray-900 touch-none cursor-grab active:cursor-grabbing select-none"
            style={{ width: BOX, height: BOX }}
            onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
          >
            {src && (
              <img
                ref={imgRef} src={src} alt="Logo to crop" draggable={false}
                onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
                className="absolute max-w-none"
                style={natural ? {
                  width: natural.w * scale, height: natural.h * scale,
                  left: BOX / 2 + offset.x - (natural.w * scale) / 2,
                  top: BOX / 2 + offset.y - (natural.h * scale) / 2,
                } : { visibility: 'hidden' }}
              />
            )}
            {/* Circular mask: dims everything outside the circle */}
            <div
              className="absolute inset-0 pointer-events-none rounded-full"
              style={{ boxShadow: '0 0 0 999px rgba(0,0,0,0.55)', border: '2px solid #fff' }}
            />
          </div>

          <div className="flex items-center gap-3 w-full">
            <ZoomIn size={16} className="text-gray-500 shrink-0" aria-hidden="true" />
            <input
              type="range" min={1} max={4} step={0.01} value={zoom}
              onChange={(e) => onZoom(Number(e.target.value))}
              aria-label="Zoom" className="flex-1"
            />
          </div>
          <p className="text-[12px] text-gray-500 dark:text-gray-400">Drag to reposition · use the slider to zoom</p>
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-gray-100 dark:border-gray-700">
          <button onClick={onCancel} disabled={saving} className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-[14px] text-gray-700 dark:text-gray-200">Cancel</button>
          <button onClick={handleSave} disabled={saving || !natural} className="px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 disabled:opacity-50 text-white text-[14px] font-semibold">
            {saving ? 'Uploading…' : 'Save Logo'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default LogoCropModal;
