"use client";

import type { Platform } from "./types";

export function PlatformBadge({ platform }: { platform: Platform | string }) {
  switch (platform) {
    case "youtube":
      return <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs font-semibold text-red-400">YouTube Live</span>;
    case "twitch":
      return <span className="rounded bg-purple-500/20 px-2 py-0.5 text-xs font-semibold text-purple-400">Twitch</span>;
    case "kick":
      return <span className="rounded bg-green-500/20 px-2 py-0.5 text-xs font-semibold text-green-400">Kick</span>;
    default:
      return null;
  }
}

export function StreamerStatusBadge({ isActive, isLive }: { isActive: boolean; isLive: boolean }) {
  if (!isActive) {
    return (
      <span className="flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-400 border border-amber-500/20">
        <span className="size-2 rounded-full bg-amber-400" />
        PAUSED
      </span>
    );
  }
  if (isLive) {
    return (
      <span className="flex items-center gap-1.5 rounded-full bg-red-500/20 px-2.5 py-1 text-xs font-bold text-red-500 animate-pulse">
        <span className="size-2 rounded-full bg-red-500" />
        LIVE NOW
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
      <span className="size-2 rounded-full bg-muted-foreground/40" />
      OFFLINE
    </span>
  );
}
