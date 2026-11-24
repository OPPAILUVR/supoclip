"use client";

import type { ClipFormat } from "./types";

interface StreamerFormatButtonsProps {
  streamerId: string;
  currentFormat?: ClipFormat;
  onSelectFormat: (streamerId: string, format: ClipFormat) => void;
}

/** Per-streamer layout switcher buttons: 40/60 Split vs Top-Down Blur ("crop"). */
export function StreamerFormatButtons({
  streamerId,
  currentFormat = "40_60",
  onSelectFormat,
}: StreamerFormatButtonsProps) {
  return (
    <div className="mt-3 flex items-center justify-between rounded-lg bg-background/80 px-2.5 py-1.5 border border-border">
      <span className="text-[11px] font-medium text-muted-foreground">Clip Format:</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onSelectFormat(streamerId, "40_60");
          }}
          className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
            currentFormat === "40_60"
              ? "bg-red-500/20 text-red-400 border border-red-500/30"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          40/60 Split
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onSelectFormat(streamerId, "crop");
          }}
          className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
            currentFormat === "crop"
              ? "bg-red-500/20 text-red-400 border border-red-500/30"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Top-Down Blur
        </button>
      </div>
    </div>
  );
}
