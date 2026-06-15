/**
 * GET /?id=VIDEO_ID
 *
 * Response:
 * {
 *   "language_code": "ja",
 *   "is_generated": true,
 *   "snippets": [{ "start": 0.92, "duration": 1.52, "text": "..." }]
 * }
 */

import { fetchNormalizedTranscript } from "./transcript.js";

const VIDEO_ID_RE = /^[a-zA-Z0-9_-]{11}$/;
const CACHE_MAX_AGE_SEC = 86400;

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept",
};

function jsonResponse(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "application/json; charset=utf-8",
      ...extraHeaders,
    },
  });
}

function errorResponse(message, status = 502) {
  return jsonResponse({ ok: false, error: message }, status);
}

function errorStatus(message) {
  const lower = String(message || "").toLowerCase();
  if (lower.includes("見つから") || lower.includes("unavailable") || lower.includes("not found")) {
    return 404;
  }
  if (lower.includes("制限") || lower.includes("429") || lower.includes("rate limit")) {
    return 429;
  }
  return 502;
}

function cacheKeyForVideo(videoId) {
  return new Request(`https://vibe-speak-proxy.cache/transcript?id=${encodeURIComponent(videoId)}`);
}

async function readCachedTranscript(videoId) {
  const cache = caches.default;
  const cached = await cache.match(cacheKeyForVideo(videoId));
  if (!cached) return null;

  const body = await cached.json();
  if (body?.ok === false || !Array.isArray(body?.snippets) || !body.snippets.length) {
    return null;
  }
  return body;
}

async function writeCachedTranscript(videoId, transcript) {
  const cache = caches.default;
  const response = jsonResponse(transcript, 200, {
    "Cache-Control": `public, max-age=${CACHE_MAX_AGE_SEC}`,
  });
  await cache.put(cacheKeyForVideo(videoId), response.clone());
  return response;
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (request.method !== "GET") {
      return errorResponse("GET のみ対応しています。", 405);
    }

    const url = new URL(request.url);
    const videoId = String(url.searchParams.get("id") || "").trim();

    if (!videoId) {
      return errorResponse("動画 ID を指定してください (?id=VIDEO_ID)。", 400);
    }
    if (!VIDEO_ID_RE.test(videoId)) {
      return errorResponse("有効な 11 桁の YouTube 動画 ID を指定してください。", 400);
    }

    try {
      const cached = await readCachedTranscript(videoId);
      if (cached) {
        return jsonResponse(cached, 200, {
          "Cache-Control": `public, max-age=${CACHE_MAX_AGE_SEC}`,
          "X-Transcript-Cache": "HIT",
        });
      }

      const transcript = await fetchNormalizedTranscript(videoId);
      return writeCachedTranscript(videoId, transcript);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err || "字幕の取得に失敗しました。");
      return errorResponse(message, errorStatus(message));
    }
  },
};
