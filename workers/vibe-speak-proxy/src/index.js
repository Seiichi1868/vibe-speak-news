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

import { fetchNormalizedTranscript, fetchTimedTextFromUrl } from "./transcript.js";

const VIDEO_ID_RE = /^[a-zA-Z0-9_-]{11}$/;
const CACHE_MAX_AGE_SEC = 259200;

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
  // 「字幕が見つからない」は YouTube 側の一時的なブロックでも出るメッセージなので
  // 404（クライアント側で再試行しない）にはせず、再試行可能な 502 のままにする。
  // 本当に動画が存在しない/非公開の場合だけ 404 として扱う。
  if (lower.includes("unavailable") || lower.includes("video not found") || lower.includes("private")) {
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

function isUsableTranscript(body) {
  return Boolean(body && Array.isArray(body.snippets) && body.snippets.length);
}

async function readEdgeCache(videoId) {
  const cached = await caches.default.match(cacheKeyForVideo(videoId));
  if (!cached) return null;
  const body = await cached.json();
  return isUsableTranscript(body) ? body : null;
}

async function readKvCache(env, videoId) {
  if (!env?.TRANSCRIPTS) return null;
  try {
    const body = await env.TRANSCRIPTS.get(videoId, "json");
    return isUsableTranscript(body) ? body : null;
  } catch (_err) {
    return null;
  }
}

async function writeCaches(env, ctx, videoId, transcript) {
  const response = jsonResponse(transcript, 200, {
    "Cache-Control": `public, max-age=${CACHE_MAX_AGE_SEC}`,
  });
  const writes = [caches.default.put(cacheKeyForVideo(videoId), response.clone())];
  if (env?.TRANSCRIPTS) {
    writes.push(
      env.TRANSCRIPTS.put(videoId, JSON.stringify(transcript), { expirationTtl: CACHE_MAX_AGE_SEC })
    );
  }
  if (ctx?.waitUntil) ctx.waitUntil(Promise.all(writes));
  else await Promise.all(writes);
  return response;
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (request.method !== "GET") {
      return errorResponse("GET のみ対応しています。", 405);
    }

    const url = new URL(request.url);
    const timedTextUrl = String(url.searchParams.get("timedtext") || "").trim();
    if (timedTextUrl) {
      try {
        const parsed = new URL(timedTextUrl);
        if (parsed.protocol !== "https:" || !parsed.hostname.endsWith("youtube.com") || !parsed.pathname.includes("timedtext")) {
          return errorResponse("timedtext URL が不正です。", 400);
        }
        const transcript = await fetchTimedTextFromUrl(timedTextUrl);
        return jsonResponse(transcript, 200, { "Cache-Control": "no-store" });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err || "字幕の取得に失敗しました。");
        return errorResponse(message, errorStatus(message));
      }
    }

    const videoId = String(url.searchParams.get("id") || "").trim();

    if (!videoId) {
      return errorResponse("動画 ID を指定してください (?id=VIDEO_ID)。", 400);
    }
    if (!VIDEO_ID_RE.test(videoId)) {
      return errorResponse("有効な 11 桁の YouTube 動画 ID を指定してください。", 400);
    }

    try {
      const edgeCached = await readEdgeCache(videoId);
      if (edgeCached) {
        if (env?.TRANSCRIPTS && ctx?.waitUntil) {
          ctx.waitUntil(
            env.TRANSCRIPTS.put(videoId, JSON.stringify(edgeCached), { expirationTtl: CACHE_MAX_AGE_SEC })
          );
        }
        return jsonResponse(edgeCached, 200, {
          "Cache-Control": `public, max-age=${CACHE_MAX_AGE_SEC}`,
          "X-Transcript-Cache": "HIT",
        });
      }

      const kvCached = await readKvCache(env, videoId);
      if (kvCached) {
        if (ctx?.waitUntil) {
          ctx.waitUntil(caches.default.put(cacheKeyForVideo(videoId), jsonResponse(kvCached, 200, {
            "Cache-Control": `public, max-age=${CACHE_MAX_AGE_SEC}`,
          })));
        }
        return jsonResponse(kvCached, 200, {
          "Cache-Control": `public, max-age=${CACHE_MAX_AGE_SEC}`,
          "X-Transcript-Cache": "KV",
        });
      }

      const transcript = await fetchNormalizedTranscript(videoId);
      if (Array.isArray(transcript?.snippets) && transcript.snippets.length) {
        return writeCaches(env, ctx, videoId, transcript);
      }
      return jsonResponse(transcript, 200, { "Cache-Control": "no-store" });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err || "字幕の取得に失敗しました。");
      return errorResponse(message, errorStatus(message));
    }
  },
};
