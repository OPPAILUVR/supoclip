"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { AppShell } from "@/components/app/app-shell";
import {
  Radio,
  Plus,
  Trash2,
  RefreshCw,
  Video,
  Sparkles,
  ExternalLink,
  Activity,
  Tv,
  ArrowUpDown,
  Filter,
  Flame,
  Users,
} from "lucide-react";

interface Streamer {
  id: string;
  name: string;
  platform: "youtube" | "twitch" | "kick";
  channel_url: string;
  channel_handle: string;
  is_live: boolean;
  current_stream_title?: string;
  current_task_id?: string;
  is_active: boolean;
  buffer_minutes: number;
  min_virality_score: number;
  clip_count: number;
  clip_format?: "40_60" | "crop";
  last_checked_at?: string;
  last_live_at?: string;
}

interface LiveClip {
  id: string;
  task_id: string;
  title: string;
  filename: string;
  url: string;
  virality_score: number;
  hook: string;
  duration: number;
  created_at?: string;
  streamer_name?: string;
  streamer_platform?: string;
}

type SortOrder = "score-desc" | "score-asc" | "newest" | "oldest";
type ScoreThreshold = "all" | "95" | "90" | "80" | "70";

export default function LiveStreamPage() {
  const [streamers, setStreamers] = useState<Streamer[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedStreamer, setSelectedStreamer] = useState<string>("all");
  const [sortOrder, setSortOrder] = useState<SortOrder>("score-desc");
  const [minScoreFilter, setMinScoreFilter] = useState<ScoreThreshold>("all");
  const [clips, setClips] = useState<LiveClip[]>([]);
  const [clipsLoading, setClipsLoading] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<"youtube" | "twitch" | "kick">("youtube");
  const [identifier, setIdentifier] = useState("");
  const [bufferMinutes, setBufferMinutes] = useState(10);
  const [minVirality, setMinVirality] = useState(75);
  const [clipFormat, setClipFormat] = useState<"40_60" | "crop">("40_60");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStreamers = useCallback(async () => {
    try {
      const res = await fetch("/api/live-streamers");
      if (res.ok) {
        const data = await res.json();
        setStreamers(data);
      }
    } catch (e) {
      console.error("Failed to load streamers:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadClips = useCallback(async (streamerId: string, showSpinner = false) => {
    if (showSpinner) setClipsLoading(true);
    try {
      const res = await fetch(`/api/live-streamers/${streamerId}/clips`);
      if (res.ok) {
        const data = await res.json();
        setClips(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      console.error("Failed to load clips:", e);
    } finally {
      if (showSpinner) setClipsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStreamers();
    const interval = setInterval(loadStreamers, 10000);
    return () => clearInterval(interval);
  }, [loadStreamers]);

  useEffect(() => {
    loadClips(selectedStreamer, true);
    const interval = setInterval(() => {
      loadClips(selectedStreamer, false);
    }, 6000);
    return () => clearInterval(interval);
  }, [selectedStreamer, loadClips]);

  const totalClipCount = useMemo(() => {
    return streamers.reduce((acc, s) => acc + (s.clip_count || 0), 0);
  }, [streamers]);

  const processedClips = useMemo(() => {
    let result = [...clips];

    // Filter by score threshold
    if (minScoreFilter !== "all") {
      const threshold = parseInt(minScoreFilter, 10);
      result = result.filter((c) => (c.virality_score || 0) >= threshold);
    }

    // Sort clips score-wise or date-wise
    result.sort((a, b) => {
      if (sortOrder === "score-desc") {
        return (b.virality_score || 0) - (a.virality_score || 0);
      }
      if (sortOrder === "score-asc") {
        return (a.virality_score || 0) - (b.virality_score || 0);
      }
      if (sortOrder === "oldest") {
        return new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
      }
      // default: newest first
      return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    });

    return result;
  }, [clips, sortOrder, minScoreFilter]);

  const handleAddStreamer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !identifier.trim()) return;

    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/live-streamers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          platform,
          identifier: identifier.trim(),
          buffer_minutes: bufferMinutes,
          min_virality_score: minVirality,
          clip_format: clipFormat,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to add streamer");
      }

      setName("");
      setIdentifier("");
      setClipFormat("40_60");
      await loadStreamers();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add streamer");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateFormat = async (streamerId: string, format: "40_60" | "crop") => {
    // Optimistic UI update
    setStreamers((prev) =>
      prev.map((s) => (s.id === streamerId ? { ...s, clip_format: format } : s))
    );
    try {
      const res = await fetch(`/api/live-streamers/${streamerId}/format`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip_format: format }),
      });
      if (!res.ok) {
        console.error("Failed to update format upstream:", await res.text());
        await loadStreamers();
      }
    } catch (e) {
      console.error("Failed to update format:", e);
      await loadStreamers();
    }
  };

  const handleToggle = async (streamerId: string, currentStatus: boolean) => {
    try {
      await fetch(`/api/live-streamers/${streamerId}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !currentStatus }),
      });
      await loadStreamers();
    } catch (e) {
      console.error("Failed to toggle:", e);
    }
  };

  const handleDelete = async (streamerId: string) => {
    if (!confirm("Are you sure you want to remove this streamer?")) return;
    try {
      await fetch(`/api/live-streamers/${streamerId}`, { method: "DELETE" });
      if (selectedStreamer === streamerId) {
        setSelectedStreamer("all");
      }
      await loadStreamers();
    } catch (e) {
      console.error("Failed to delete:", e);
    }
  };

  const platformBadge = (p: string) => {
    switch (p) {
      case "youtube":
        return <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs font-semibold text-red-400">YouTube Live</span>;
      case "twitch":
        return <span className="rounded bg-purple-500/20 px-2 py-0.5 text-xs font-semibold text-purple-400">Twitch</span>;
      case "kick":
        return <span className="rounded bg-green-500/20 px-2 py-0.5 text-xs font-semibold text-green-400">Kick</span>;
      default:
        return null;
    }
  };

  const getStreamerBadge = (streamerName?: string, platform?: string) => {
    if (!streamerName) return null;
    let colorClass = "bg-red-500/80 text-white";
    if (platform === "twitch") colorClass = "bg-purple-600/90 text-white";
    if (platform === "kick") colorClass = "bg-emerald-600/90 text-white";

    return (
      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold backdrop-blur-md shadow-sm capitalize ${colorClass}`}>
        {streamerName}
      </span>
    );
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-8 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl bg-red-500/10 text-red-500">
                <Radio className="size-5 animate-pulse" />
              </div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
                Live Stream Auto-Clipper
              </h1>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              Monitor YouTube, Twitch, and Kick streamers. When they go live, AI buffers 10 minutes and generates instant vertical clips with subtitles without waiting for the stream to end.
            </p>
          </div>
          <button
            onClick={() => loadStreamers()}
            className="flex items-center gap-2 rounded-lg border border-border bg-card px-3.5 py-2 text-xs font-medium text-foreground hover:bg-accent transition"
          >
            <RefreshCw className="size-3.5" />
            Refresh
          </button>
        </div>

        {/* Top Grid: Add Streamer + Watchlist */}
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
          {/* Add Streamer Card */}
          <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
              <Plus className="size-5 text-red-500" />
              Watch Streamer
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Enter channel name or handle to auto-clip when live.
            </p>

            {error && (
              <div className="mt-4 rounded-lg bg-red-500/10 p-3 text-xs text-red-400">
                {error}
              </div>
            )}

            <form onSubmit={handleAddStreamer} className="mt-5 space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground">Platform</label>
                <div className="mt-1.5 grid grid-cols-3 gap-2">
                  {(["youtube", "twitch", "kick"] as const).map((p) => (
                    <button
                      type="button"
                      key={p}
                      onClick={() => setPlatform(p)}
                      className={`rounded-lg border px-3 py-2 text-xs font-medium capitalize transition ${
                        platform === p
                          ? "border-red-500 bg-red-500/10 text-red-400 font-bold"
                          : "border-border text-muted-foreground hover:bg-accent"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground">Streamer Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Shroud, xQc, Lofi Girl"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-red-500"
                />
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Channel Handle / URL
                </label>
                <input
                  type="text"
                  required
                  placeholder={
                    platform === "youtube"
                      ? "@LofiGirl or youtube.com/@handle/live"
                      : platform === "twitch"
                      ? "shroud or twitch.tv/shroud"
                      : "xqc or kick.com/xqc"
                  }
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-red-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3 pt-1">
                <div>
                  <label className="text-xs font-medium text-muted-foreground">
                    Buffer Window
                  </label>
                  <select
                    value={bufferMinutes}
                    onChange={(e) => setBufferMinutes(Number(e.target.value))}
                    className="mt-1.5 w-full rounded-lg border border-border bg-background px-2.5 py-2 text-xs text-foreground outline-none focus:border-red-500"
                  >
                    <option value={5}>5 Minutes</option>
                    <option value={10}>10 Minutes (Default)</option>
                    <option value={15}>15 Minutes</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground">
                    Min Virality
                  </label>
                  <select
                    value={minVirality}
                    onChange={(e) => setMinVirality(Number(e.target.value))}
                    className="mt-1.5 w-full rounded-lg border border-border bg-background px-2.5 py-2 text-xs text-foreground outline-none focus:border-red-500"
                  >
                    <option value={70}>70+ (More clips)</option>
                    <option value={75}>75+ (Balanced)</option>
                    <option value={85}>85+ (Only best)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground">Clip Format</label>
                <div className="mt-1.5 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setClipFormat("40_60")}
                    className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${
                      clipFormat === "40_60"
                        ? "border-red-500 bg-red-500/10 text-red-400 font-bold"
                        : "border-border text-muted-foreground hover:bg-accent"
                    }`}
                  >
                    40/60 Split
                  </button>
                  <button
                    type="button"
                    onClick={() => setClipFormat("crop")}
                    className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${
                      clipFormat === "crop"
                        ? "border-red-500 bg-red-500/10 text-red-400 font-bold"
                        : "border-border text-muted-foreground hover:bg-accent"
                    }`}
                  >
                    Top-Down Blur
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white shadow hover:bg-red-500 disabled:opacity-50 transition"
              >
                {submitting ? "Adding..." : "Start Monitoring"}
              </button>
            </form>
          </div>

          {/* Watchlist Streamers */}
          <div className="col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
                <span>Tracked Streamers ({streamers.length})</span>
                <span className="text-xs font-normal text-muted-foreground">
                  Auto-polls every 30s
                </span>
              </h2>

              {/* Quick toggle for All Streamers */}
              <button
                type="button"
                onClick={() => setSelectedStreamer("all")}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                  selectedStreamer === "all"
                    ? "bg-red-500 text-white font-bold shadow-sm"
                    : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground"
                }`}
              >
                All Streamers ({totalClipCount})
              </button>
            </div>

            {loading ? (
              <div className="flex h-48 items-center justify-center rounded-2xl border border-border bg-card">
                <RefreshCw className="size-6 animate-spin text-muted-foreground" />
              </div>
            ) : streamers.length === 0 ? (
              <div className="flex h-56 flex-col items-center justify-center rounded-2xl border border-dashed border-border p-8 text-center bg-card">
                <Tv className="size-10 text-muted-foreground/50 mb-2" />
                <p className="text-sm font-medium text-foreground">No streamers added yet</p>
                <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                  Add your favorite YouTube, Twitch, or Kick streamer on the left to start automatic moment detection.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {streamers.map((s) => (
                  <div
                    key={s.id}
                    onClick={() => setSelectedStreamer(selectedStreamer === s.id ? "all" : s.id)}
                    className={`cursor-pointer rounded-2xl border p-5 transition shadow-sm ${
                      selectedStreamer === s.id
                        ? "border-red-500 bg-red-500/5 ring-1 ring-red-500"
                        : "border-border bg-card hover:border-border/80"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold text-foreground">{s.name}</h3>
                          {platformBadge(s.platform)}
                        </div>
                        <p className="mt-0.5 text-xs text-muted-foreground">{s.channel_handle}</p>
                      </div>

                      {/* Live Badge */}
                      {s.is_live ? (
                        <span className="flex items-center gap-1.5 rounded-full bg-red-500/20 px-2.5 py-1 text-xs font-bold text-red-500 animate-pulse">
                          <span className="size-2 rounded-full bg-red-500" />
                          LIVE NOW
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                          <span className="size-2 rounded-full bg-muted-foreground/40" />
                          OFFLINE
                        </span>
                      )}
                    </div>

                    {s.is_live && s.current_stream_title && (
                      <div className="mt-3 rounded-lg bg-background p-2.5 text-xs text-foreground line-clamp-1 border border-border">
                        <span className="font-medium text-red-400">Streaming: </span>
                        {s.current_stream_title}
                      </div>
                    )}

                    {/* Format Selector */}
                    <div className="mt-3 flex items-center justify-between rounded-lg bg-background/80 px-2.5 py-1.5 border border-border">
                      <span className="text-[11px] font-medium text-muted-foreground">Clip Format:</span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleUpdateFormat(s.id, "40_60");
                          }}
                          className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
                            (s.clip_format || "40_60") === "40_60"
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
                            handleUpdateFormat(s.id, "crop");
                          }}
                          className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
                            s.clip_format === "crop"
                              ? "bg-red-500/20 text-red-400 border border-red-500/30"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          Top-Down Blur
                        </button>
                      </div>
                    </div>

                    <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
                      <div className="flex items-center gap-3">
                        <span className="flex items-center gap-1">
                          <Video className="size-3.5 text-red-400" />
                          {s.clip_count} clips
                        </span>
                        <span>{s.buffer_minutes}m buffer</span>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          title={s.is_active ? "Pause monitoring" : "Resume monitoring"}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleToggle(s.id, s.is_active);
                          }}
                          className={`rounded px-2 py-1 text-xs font-medium transition ${
                            s.is_active ? "text-emerald-400 hover:bg-emerald-500/10" : "text-amber-400 hover:bg-amber-500/10"
                          }`}
                        >
                          {s.is_active ? "Active" : "Paused"}
                        </button>
                        <button
                          title="Remove streamer"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(s.id);
                          }}
                          className="text-muted-foreground hover:text-red-400 transition"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Bottom Section: Real-Time Clips Feed */}
        <div className="mt-12">
          {/* Section Header with Filter Toolbar */}
          <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="flex items-center gap-2.5">
                <Sparkles className="size-5 text-amber-400" />
                <h2 className="text-xl font-bold text-foreground">Live Generated Clips</h2>
                <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
                  {processedClips.length} {processedClips.length === 1 ? "clip" : "clips"}
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

            {/* Filter and Sort Toolbar */}
            <div className="flex flex-wrap items-center gap-2.5">
              {/* Streamer Filter Dropdown */}
              <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-sm">
                <Users className="size-3.5 text-muted-foreground" />
                <span className="text-muted-foreground font-medium">Streamer:</span>
                <select
                  value={selectedStreamer}
                  onChange={(e) => setSelectedStreamer(e.target.value)}
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

              {/* Score-wise Sort Order Dropdown */}
              <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-sm">
                <ArrowUpDown className="size-3.5 text-muted-foreground" />
                <span className="text-muted-foreground font-medium">Sort:</span>
                <select
                  value={sortOrder}
                  onChange={(e) => setSortOrder(e.target.value as SortOrder)}
                  className="bg-transparent font-semibold text-foreground outline-none cursor-pointer"
                >
                  <option value="score-desc">🔥 Higher Score on Top (100 → 0)</option>
                  <option value="score-asc">📉 Lower Score on Top (0 → 100)</option>
                  <option value="newest">🕒 Newest First</option>
                  <option value="oldest">⏳ Oldest First</option>
                </select>
              </div>

              {/* Score Threshold Filter Dropdown */}
              <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-sm">
                <Filter className="size-3.5 text-muted-foreground" />
                <span className="text-muted-foreground font-medium">Min Score:</span>
                <select
                  value={minScoreFilter}
                  onChange={(e) => setMinScoreFilter(e.target.value as ScoreThreshold)}
                  className="bg-transparent font-semibold text-foreground outline-none cursor-pointer"
                >
                  <option value="all">All Scores</option>
                  <option value="95">⚡ 95+ (Instant Viral)</option>
                  <option value="90">🎯 90+ (Ultra High)</option>
                  <option value="80">✨ 80+ (High Score)</option>
                  <option value="70">📊 70+ (Standard)</option>
                </select>
              </div>

              {/* Reset Filters button */}
              {(sortOrder !== "score-desc" || minScoreFilter !== "all" || selectedStreamer !== "all") && (
                <button
                  type="button"
                  onClick={() => {
                    setSortOrder("score-desc");
                    setMinScoreFilter("all");
                    setSelectedStreamer("all");
                  }}
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
          ) : processedClips.length === 0 ? (
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
                    setMinScoreFilter("all");
                    setSelectedStreamer("all");
                  }}
                  className="mt-3 rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent transition"
                >
                  Clear Filters
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {processedClips.map((clip) => (
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

                    {/* Streamer Badge (Top Left) */}
                    {clip.streamer_name && (
                      <div className="absolute top-2.5 left-2.5">
                        {getStreamerBadge(clip.streamer_name, clip.streamer_platform)}
                      </div>
                    )}

                    {/* Virality Score Badge (Top Right) */}
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
      </div>
    </AppShell>
  );
}
