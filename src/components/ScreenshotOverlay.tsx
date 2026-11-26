import { useEffect, useRef, useState } from "react";
import { api } from "../lib/tauri";
import type { ScreenshotSourcePayload } from "../lib/types";

interface DragBox {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
}

export function ScreenshotOverlay() {
  const [payload, setPayload] = useState<ScreenshotSourcePayload | null>(null);
  const [drag, setDrag] = useState<DragBox | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    api.getPendingScreenshot().then(setPayload).catch(() => {
      api.completeWindowsScreenshot(null);
    });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        api.completeWindowsScreenshot(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!payload) {
    return <div className="h-screen w-screen bg-black/40" />;
  }

  const rect = drag
    ? {
        x: Math.min(drag.startX, drag.curX),
        y: Math.min(drag.startY, drag.curY),
        w: Math.abs(drag.curX - drag.startX),
        h: Math.abs(drag.curY - drag.startY),
      }
    : null;

  const commitCrop = () => {
    if (!rect || rect.w < 4 || rect.h < 4 || !imgRef.current) {
      setDrag(null);
      return;
    }
    const scaleX = payload.width / imgRef.current.clientWidth;
    const scaleY = payload.height / imgRef.current.clientHeight;
    api.completeWindowsScreenshot({
      x: Math.round(rect.x * scaleX),
      y: Math.round(rect.y * scaleY),
      width: Math.max(1, Math.round(rect.w * scaleX)),
      height: Math.max(1, Math.round(rect.h * scaleY)),
    });
  };

  return (
    <div
      className="relative h-screen w-screen cursor-crosshair overflow-hidden select-none"
      onMouseDown={(e) => {
        if (e.button === 2) {
          api.completeWindowsScreenshot(null);
          return;
        }
        if (e.button === 0) {
          setDrag({
            startX: e.clientX,
            startY: e.clientY,
            curX: e.clientX,
            curY: e.clientY,
          });
        }
      }}
      onMouseMove={(e) => {
        if (drag) {
          setDrag({ ...drag, curX: e.clientX, curY: e.clientY });
        }
      }}
      onMouseUp={() => commitCrop()}
      onContextMenu={(e) => {
        e.preventDefault();
        api.completeWindowsScreenshot(null);
      }}
    >
      <img
        ref={imgRef}
        src={`data:image/png;base64,${payload.image_base64}`}
        alt=""
        draggable={false}
        className="h-full w-full object-fill"
      />
      <div className="pointer-events-none absolute inset-0 bg-black/40" />

      {rect && rect.w > 0 && rect.h > 0 && (
        <div
          className="pointer-events-none absolute border-2 border-[#89b4fa] bg-transparent"
          style={{
            left: rect.x,
            top: rect.y,
            width: rect.w,
            height: rect.h,
            boxShadow: "0 0 0 9999px rgba(0, 0, 0, 0.35)",
          }}
        >
          <div className="absolute -top-6 left-0 rounded bg-[#181825]/90 px-1.5 py-0.5 font-mono text-[11px] text-[#cdd6f4]">
            {Math.round(rect.w)} × {Math.round(rect.h)}
          </div>
        </div>
      )}

      <div className="pointer-events-none fixed bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-[#181825]/85 px-4 py-1.5 text-xs text-[#cdd6f4]">
        拖拽框选区域 · Esc 或右键取消
      </div>
    </div>
  );
}
