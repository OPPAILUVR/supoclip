import type { ClipFormat, CreateStreamerPayload, LiveClip, Streamer } from "./types";

export async function fetchStreamers(): Promise<Streamer[] | null> {
  const res = await fetch("/api/live-streamers");
  if (!res.ok) return null;
  return res.json();
}

export async function fetchStreamerClips(streamerId: string): Promise<LiveClip[] | null> {
  const res = await fetch(`/api/live-streamers/${streamerId}/clips`);
  if (!res.ok) return null;
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function createStreamer(payload: CreateStreamerPayload): Promise<void> {
  const res = await fetch("/api/live-streamers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to add streamer");
  }
}

export async function updateStreamerFormatApi(streamerId: string, format: ClipFormat): Promise<boolean> {
  const res = await fetch(`/api/live-streamers/${streamerId}/format`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_format: format }),
  });
  if (!res.ok) {
    console.error("Failed to update format upstream:", await res.text());
    return false;
  }
  return true;
}

export async function toggleStreamerActiveApi(streamerId: string, isActive: boolean): Promise<boolean> {
  const res = await fetch(`/api/live-streamers/${streamerId}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: isActive }),
  });
  if (!res.ok) {
    console.error("Toggle request failed on server");
    return false;
  }
  return true;
}

export async function deleteStreamerApi(streamerId: string): Promise<boolean> {
  const res = await fetch(`/api/live-streamers/${streamerId}`, { method: "DELETE" });
  if (!res.ok) {
    console.error("Delete request failed on server");
    return false;
  }
  return true;
}
