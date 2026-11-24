import { NextResponse } from "next/server";

import { createProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const body = await request.text();

  const upstream = await fetchBackend(`/live-streamers/${id}/format`, {
    method: "POST",
    userId: session.user.id,
    extraHeaders: { "Content-Type": "application/json" },
    body,
  });

  return createProxyResponse(upstream);
}
