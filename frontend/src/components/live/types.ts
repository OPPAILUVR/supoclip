export type Platform = "youtube" | "twitch" | "kick";
export type ClipFormat = "40_60" | "crop";
export type SortOrder = "score-desc" | "score-asc" | "newest" | "oldest";
export type ScoreThreshold = "all" | "95" | "90" | "80" | "70";

export interface Streamer {
  id: string;
  name: string;
  platform: Platform;
  channel_url: string;
  channel_handle: string;
  is_live: boolean;
  current_stream_title?: string;
  current_task_id?: string;
  is_active: boolean;
  buffer_minutes: number;
  min_virality_score: number;
  clip_count: number;
  clip_format?: ClipFormat;
  last_checked_at?: string;
  last_live_at?: string;
}

export interface LiveClip {
  id: string;
  task_id: string;
  title: string;
  filename: string;
  url: string;
  virality_score: number;
  hook: string;
  duration: number;
  created_at?: string;
  streamer_id?: string;
  streamer_name?: string;
  streamer_platform?: string;
}

export interface CreateStreamerPayload {
  name: string;
  platform: Platform;
  identifier: string;
  buffer_minutes: number;
  min_virality_score: number;
  clip_format: ClipFormat;
}
