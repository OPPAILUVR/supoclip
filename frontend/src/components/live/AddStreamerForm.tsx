"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import type { ClipFormat, CreateStreamerPayload, Platform } from "./types";

interface AddStreamerFormProps {
  onAdd: (payload: CreateStreamerPayload) => Promise<void>;
}

export function AddStreamerForm({ onAdd }: AddStreamerFormProps) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("youtube");
  const [identifier, setIdentifier] = useState("");
  const [bufferMinutes, setBufferMinutes] = useState(10);
  const [minVirality, setMinVirality] = useState(75);
  const [clipFormat, setClipFormat] = useState<ClipFormat>("40_60");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !identifier.trim()) return;

    setSubmitting(true);
    setError(null);
    try {
      await onAdd({
        name: name.trim(),
        platform,
        identifier: identifier.trim(),
        buffer_minutes: bufferMinutes,
        min_virality_score: minVirality,
        clip_format: clipFormat,
      });
      setName("");
      setIdentifier("");
      setClipFormat("40_60");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add streamer");
    } finally {
      setSubmitting(false);
    }
  };

  return (
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

      <form onSubmit={handleSubmit} className="mt-5 space-y-4">
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
  );
}
