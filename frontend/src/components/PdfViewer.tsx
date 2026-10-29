"use client";

import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

import type { Rect } from "@/lib/api";
import { TONE_CLASSES } from "@/lib/display";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export type Highlight = { id: string; rects: Rect[]; tone: keyof typeof TONE_CLASSES };

type Props = {
  url: string;
  pages: { number: number; width: number; height: number }[];
  highlights: Highlight[];
  activeId: string | null;
  onSelect: (id: string) => void;
};

/** Renders every page and overlays highlight boxes. Rects are PDF points with a top-left origin. */
export default function PdfViewer({ url, pages, highlights, activeId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.min(900, Math.floor(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Scroll the active highlight into view.
  useEffect(() => {
    if (!activeId || !width) return;
    const el = container.current?.querySelector(`[data-highlight="${activeId}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeId, width]);

  return (
    <div ref={container} className="w-full">
      <Document file={url} loading={<p className="p-6 text-sm text-neutral-500">Loading PDF…</p>}>
        {width > 0 &&
          pages.map((p) => {
            const scale = width / p.width;
            return (
              <div key={p.number} className="relative mx-auto mb-4 shadow-sm ring-1 ring-neutral-200 dark:ring-neutral-800" style={{ width }}>
                <Page pageNumber={p.number} width={width} renderTextLayer={false} renderAnnotationLayer={false} />
                {highlights.flatMap((h) =>
                  h.rects
                    .filter((r) => r.page === p.number)
                    .map((r, i) => {
                      const [x0, y0, x1, y1] = r.bbox;
                      const active = h.id === activeId;
                      return (
                        <button
                          key={`${h.id}-${i}`}
                          data-highlight={i === 0 ? h.id : undefined}
                          onClick={() => onSelect(h.id)}
                          aria-label="Show decision"
                          className={`absolute rounded-sm mix-blend-multiply dark:mix-blend-normal ${TONE_CLASSES[h.tone].box} ${active ? "ring-2" : ""}`}
                          style={{
                            left: x0 * scale - 2,
                            top: y0 * scale - 1,
                            width: (x1 - x0) * scale + 4,
                            height: (y1 - y0) * scale + 2,
                          }}
                        />
                      );
                    }),
                )}
                <span className="absolute bottom-1 right-2 text-[10px] text-neutral-400">{p.number}</span>
              </div>
            );
          })}
      </Document>
    </div>
  );
}
