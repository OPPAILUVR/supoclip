"use client";

import { Trash2 } from "lucide-react";

interface StreamerActionButtonsProps {
  streamerId: string;
  isActive: boolean;
  onToggle: (streamerId: string, currentActive: boolean) => void;
  onDelete: (streamerId: string) => void;
}

/** Active/Paused toggle button & complete Delete button for a tracked streamer. */
export function StreamerActionButtons({
  streamerId,
  isActive,
  onToggle,
  onDelete,
}: StreamerActionButtonsProps) {
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        title={isActive ? "Click to pause auto-clipping" : "Click to resume auto-clipping"}
        onClick={(e) => {
          e.stopPropagation();
          onToggle(streamerId, isActive);
        }}
        className={`rounded px-2.5 py-1 text-xs font-semibold transition border ${
          isActive
            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20"
            : "bg-amber-500/10 text-amber-400 border-amber-500/20 hover:bg-amber-500/20"
        }`}
      >
        {isActive ? "● Active" : "⏸ Paused"}
      </button>
      <button
        type="button"
        title="Permanently delete streamer and all associated clips"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(streamerId);
        }}
        className="rounded p-1 text-muted-foreground hover:bg-red-500/10 hover:text-red-400 transition"
      >
        <Trash2 className="size-4" />
      </button>
    </div>
  );
}
