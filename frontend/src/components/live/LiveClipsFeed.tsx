"use client";

import {
  Activity,
  ArrowUpDown,
  ExternalLink,
  Filter,
  Flame,
  RefreshCw,
  Sparkles,
  Users,
} from "lucide-react";
import type { LiveClip, ScoreThreshold, SortOrder, Streamer } from "./types";

interface LiveClipsFeedProps {
  clips: LiveClip[];
  clipsLoading: boolean;
  streamers: Streamer[];
  selectedStreamer: string;
  onSelectStreamer: (id: string) => void;
  sortOrder: SortOrder;
  onChangeSortOrder: (order: SortOrder) => void;
  minScoreFilter: ScoreThreshold;
  onChangeMinScoreFilter: (score: ScoreThreshold) => void;
  totalClipCount: number;
}

function StreamerClipPill({ name, platform }: { name?: string; platform?: string }) {
  if (!name) return null;
  let colorClass = "bg-red-500/80 text-white";
  if (platform === "twitch") colorClass = "bg-purple-600/90 text-white";
  if (platform === "kick") colorClass = "bg-emerald-600/90 text-white";

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold backdrop-blur-md shadow-sm capitalize ${colorClass}`}
    >
      {name}
    </span>
  );
}

export function LiveClipsFeed({
  clips,
  clipsLoading,
  streamers,
  selectedStreamer,
  onSelectStreamer,
  sortOrder,
  onChangeSortOrder,
  minScoreFilter,
  onChangeMinScoreFilter,
  totalClipCount,
}: LiveClipsFeedProps) {
  const hasActiveFilters =
    sortOrder !== "score-desc" || minScoreFilter !== "all" || selectedStreamer !== "all";

  const resetFilters = () => {
    onChangeSortOrder("score-desc");
    onChangeMinScoreFilter("all");
    onSelectStreamer("all");
  };

  return (
    <div className="mt-12">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <Sparkles className="size-5 text-amber-400" />
            <h2 className="text-xl font-bold text-foreground">Live Generated Clips</h2>
            <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
              {clips.length} {clips.length === 1 ? "clip" : "clips"}
            </span>
            {selectedStreamer !== "all" && (
              <span className="rounded-full bg-red-500/10 px-2.5 py-0.5 text-xs font-medium text-red-400 border border-red-500/20 capitalize">
                {streamers.find((s) => s.id === selectedStreamer)?.name || "Filtered"}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Standout moments cut and subtitled in real time directly from the live stream buffers.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-sm">
            <Users className="size-3.5 text-muted-foreground" />
            <span className="text-muted-foreground font-medium">Streamer:</span>
            <select
              value={selectedStreamer}
              onChange={(e) => onSelectStreamer(e.target.value)}
              className="bg-transparent font-semibold text-foreground outline-none cursor-pointer"
            >
              <option value="all">All Streamers ({totalClipCount})</option>
              {streamers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.clip_count})
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-sm">
            <ArrowUpDown className="size-3.5 text-muted-foreground" />
            <span className="text-muted-foreground font-medium">Sort:</span>
            <select
              value={sortOrder}
              onChange={(e) => onChangeSortOrder(e.target.value as SortOrder)}
              className="bg-transparent font-semibold text-foreground outline-none cursor-pointer"
            >
              <option value="score-desc">🔥 Higher Score on Top (100 → 0)</option>
              <option value="score-asc">📉 Lower Score on Top (0 → 100)</option>
              <option value="newest">🕒 Newest First</option>
              <option value="oldest">⏳ Oldest First</option>
            </select>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-sm">
            <Filter className="size-3.5 text-muted-foreground" />
            <span className="text-muted-foreground font-medium">Min Score:</span>
            <select
              value={minScoreFilter}
              onChange={(e) => onChangeMinScoreFilter(e.target.value as ScoreThreshold)}
              className="bg-transparent font-semibold text-foreground outline-none cursor-pointer"
            >
              <option value="all">All Scores</option>
              <option value="95">⚡ 95+ (Instant Viral)</option>
              <option value="90">🎯 90+ (Ultra High)</option>
              <option value="80">✨ 80+ (High Score)</option>
              <option value="70">📊 70+ (Standard)</option>
            </select>
          </div>

          {hasActiveFilters && (
            <button
              type="button"
              onClick={resetFilters}
              className="rounded-xl border border-border bg-card px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition shadow-sm"
              title="Reset all filters"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      {clipsLoading ? (
        <div className="flex h-48 items-center justify-center rounded-2xl border border-border bg-card">
          <RefreshCw className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : clips.length === 0 ? (
        <div className="flex h-48 flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card p-6 text-center">
          <Activity className="size-8 text-muted-foreground/40 mb-2" />
          <p className="text-sm font-medium text-foreground">No clips match your filter</p>
          <p className="text-xs text-muted-foreground mt-1 max-w-sm">
            Try lowering the minimum score filter or selecting another streamer to see generated clips.
          </p>
          {(minScoreFilter !== "all" || selectedStreamer !== "all") && (
            <button
              type="button"
              onClick={() => {
                onChangeMinScoreFilter("all");
                onSelectStreamer("all");
              }}
              className="mt-3 rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent transition"
            >
              Clear Filters
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {clips.map((clip) => (
            <div
              key={clip.id}
              className="group relative overflow-hidden rounded-2xl border border-border bg-card shadow-sm transition hover:shadow-md hover:border-border/80"
            >
              <div className="relative aspect-[9/16] bg-black">
                <video
                  src={clip.url}
                  controls
                  preload="metadata"
                  className="size-full object-cover"
                />

                {clip.streamer_name && (
                  <div className="absolute top-2.5 left-2.5">
                    <StreamerClipPill name={clip.streamer_name} platform={clip.streamer_platform} />
                  </div>
                )}

                <div className="absolute top-2.5 right-2.5">
                  {clip.virality_score >= 95 ? (
                    <div className="flex items-center gap-1 rounded-full bg-gradient-to-r from-amber-400 via-yellow-400 to-amber-500 px-2.5 py-0.5 text-xs font-black text-black shadow-lg animate-pulse ring-1 ring-amber-300">
                      <Flame className="size-3 fill-black" />
                      <span>{clip.virality_score} VIRAL</span>
                    </div>
                  ) : clip.virality_score >= 85 ? (
                    <div className="flex items-center gap-1 rounded-full bg-amber-500/90 px-2 py-0.5 text-xs font-bold text-black shadow">
                      <span>Score: {clip.virality_score}</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1 rounded-full bg-background/90 backdrop-blur-md border border-border px-2 py-0.5 text-xs font-semibold text-foreground shadow">
                      <span>Score: {clip.virality_score}</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="p-4">
                <h4 className="font-semibold text-foreground text-sm line-clamp-1">{clip.title}</h4>
                <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{clip.hook}</p>

                <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground border-t border-border pt-2.5">
                  <span>{clip.duration ? `${Math.round(clip.duration)}s` : "Clip"}</span>
                  <a
                    href={clip.url}
                    download={clip.filename}
                    className="flex items-center gap-1 font-medium text-red-400 hover:text-red-300 transition"
                  >
                    Download
                    <ExternalLink className="size-3" />
                  </a>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
