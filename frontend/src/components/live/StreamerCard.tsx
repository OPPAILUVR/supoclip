"use client";

import { Video } from "lucide-react";
import { PlatformBadge, StreamerStatusBadge } from "./StreamerStatusBadge";
import { StreamerFormatButtons } from "./StreamerFormatButtons";
import { StreamerActionButtons } from "./StreamerActionButtons";
import type { ClipFormat, Streamer } from "./types";

interface StreamerCardProps {
  streamer: Streamer;
  selected: boolean;
  onSelect: (streamerId: string) => void;
  onSelectFormat: (streamerId: string, format: ClipFormat) => void;
  onToggle: (streamerId: string, currentActive: boolean) => void;
  onDelete: (streamerId: string) => void;
}

export function StreamerCard({
  streamer,
  selected,
  onSelect,
  onSelectFormat,
  onToggle,
  onDelete,
}: StreamerCardProps) {
  return (
    <div
      onClick={() => onSelect(streamer.id)}
      className={`cursor-pointer rounded-2xl border p-5 transition shadow-sm ${
        selected
          ? "border-red-500 bg-red-500/5 ring-1 ring-red-500"
          : "border-border bg-card hover:border-border/80"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-foreground">{streamer.name}</h3>
            <PlatformBadge platform={streamer.platform} />
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{streamer.channel_handle}</p>
        </div>

        <StreamerStatusBadge isActive={streamer.is_active} isLive={streamer.is_live} />
      </div>

      {streamer.is_live && streamer.current_stream_title && (
        <div className="mt-3 rounded-lg bg-background p-2.5 text-xs text-foreground line-clamp-1 border border-border">
          <span className="font-medium text-red-400">Streaming: </span>
          {streamer.current_stream_title}
        </div>
      )}

      <StreamerFormatButtons
        streamerId={streamer.id}
        currentFormat={streamer.clip_format || "40_60"}
        onSelectFormat={onSelectFormat}
      />

      <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Video className="size-3.5 text-red-400" />
            {streamer.clip_count} clips
          </span>
          <span>{streamer.buffer_minutes}m buffer</span>
        </div>

        <StreamerActionButtons
          streamerId={streamer.id}
          isActive={streamer.is_active}
          onToggle={onToggle}
          onDelete={onDelete}
        />
      </div>
    </div>
  );
}
