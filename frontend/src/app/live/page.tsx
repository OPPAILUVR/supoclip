"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Radio, RefreshCw, Tv } from "lucide-react";
import { AppShell } from "@/components/app/app-shell";
import { AddStreamerForm } from "@/components/live/AddStreamerForm";
import { StreamerCard } from "@/components/live/StreamerCard";
import { LiveClipsFeed } from "@/components/live/LiveClipsFeed";
import {
  createStreamer,
  deleteStreamerApi,
  fetchStreamerClips,
  fetchStreamers,
  toggleStreamerActiveApi,
  updateStreamerFormatApi,
} from "@/components/live/live-api";
import type {
  ClipFormat,
  CreateStreamerPayload,
  LiveClip,
  ScoreThreshold,
  SortOrder,
  Streamer,
} from "@/components/live/types";

export default function LiveStreamPage() {
  const [streamers, setStreamers] = useState<Streamer[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedStreamer, setSelectedStreamer] = useState<string>("all");
  const [sortOrder, setSortOrder] = useState<SortOrder>("score-desc");
  const [minScoreFilter, setMinScoreFilter] = useState<ScoreThreshold>("all");
  const [clips, setClips] = useState<LiveClip[]>([]);
  const [clipsLoading, setClipsLoading] = useState(false);

  const loadStreamers = useCallback(async () => {
    try {
      const data = await fetchStreamers();
      if (data) setStreamers(data);
    } catch (e) {
      console.error("Failed to load streamers:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadClips = useCallback(async (streamerId: string, showSpinner = false) => {
    if (showSpinner) setClipsLoading(true);
    try {
      const data = await fetchStreamerClips(streamerId);
      if (data) setClips(data);
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

  const totalClipCount = useMemo(
    () => streamers.reduce((acc, s) => acc + (s.clip_count || 0), 0),
    [streamers]
  );

  const processedClips = useMemo(() => {
    let result = [...clips];
    if (minScoreFilter !== "all") {
      const threshold = parseInt(minScoreFilter, 10);
      result = result.filter((c) => (c.virality_score || 0) >= threshold);
    }
    result.sort((a, b) => {
      if (sortOrder === "score-desc") return (b.virality_score || 0) - (a.virality_score || 0);
      if (sortOrder === "score-asc") return (a.virality_score || 0) - (b.virality_score || 0);
      if (sortOrder === "oldest") {
        return new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
      }
      return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    });
    return result;
  }, [clips, sortOrder, minScoreFilter]);

  const handleAddStreamer = async (payload: CreateStreamerPayload) => {
    await createStreamer(payload);
    await loadStreamers();
  };

  const handleUpdateFormat = async (streamerId: string, format: ClipFormat) => {
    setStreamers((prev) =>
      prev.map((s) => (s.id === streamerId ? { ...s, clip_format: format } : s))
    );
    try {
      const ok = await updateStreamerFormatApi(streamerId, format);
      if (!ok) await loadStreamers();
    } catch (e) {
      console.error("Failed to update format:", e);
      await loadStreamers();
    }
  };

  const handleToggle = async (streamerId: string, currentStatus: boolean) => {
    const nextStatus = !currentStatus;
    setStreamers((prev) =>
      prev.map((s) =>
        s.id === streamerId
          ? { ...s, is_active: nextStatus, is_live: nextStatus ? s.is_live : false }
          : s
      )
    );
    try {
      await toggleStreamerActiveApi(streamerId, nextStatus);
      await loadStreamers();
    } catch (e) {
      console.error("Failed to toggle:", e);
      await loadStreamers();
    }
  };

  const handleDelete = async (streamerId: string) => {
    if (!confirm("Are you sure you want to completely delete this streamer and all its data?")) return;
    const deleted = streamers.find((s) => s.id === streamerId);
    const nextSelected = selectedStreamer === streamerId ? "all" : selectedStreamer;

    setStreamers((prev) => prev.filter((s) => s.id !== streamerId));
    if (selectedStreamer === streamerId) {
      setSelectedStreamer("all");
    }
    setClips((prev) =>
      prev.filter(
        (c) =>
          c.streamer_id !== streamerId &&
          (!deleted?.name || c.streamer_name?.toLowerCase() !== deleted.name.toLowerCase())
      )
    );
    try {
      await deleteStreamerApi(streamerId);
      await loadStreamers();
      await loadClips(nextSelected, false);
    } catch (e) {
      console.error("Failed to delete:", e);
      await loadStreamers();
      await loadClips(nextSelected, false);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
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

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
          <AddStreamerForm onAdd={handleAddStreamer} />

          <div className="col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
                <span>Tracked Streamers ({streamers.length})</span>
                <span className="text-xs font-normal text-muted-foreground">
                  Auto-polls every 30s
                </span>
              </h2>

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
                  <StreamerCard
                    key={s.id}
                    streamer={s}
                    selected={selectedStreamer === s.id}
                    onSelect={(id) => setSelectedStreamer(selectedStreamer === id ? "all" : id)}
                    onSelectFormat={handleUpdateFormat}
                    onToggle={handleToggle}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <LiveClipsFeed
          clips={processedClips}
          clipsLoading={clipsLoading}
          streamers={streamers}
          selectedStreamer={selectedStreamer}
          onSelectStreamer={setSelectedStreamer}
          sortOrder={sortOrder}
          onChangeSortOrder={setSortOrder}
          minScoreFilter={minScoreFilter}
          onChangeMinScoreFilter={setMinScoreFilter}
          totalClipCount={totalClipCount}
        />
      </div>
    </AppShell>
  );
}
