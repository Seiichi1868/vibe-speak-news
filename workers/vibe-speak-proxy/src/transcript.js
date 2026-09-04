const DEFAULT_LANGUAGES = ["en", "ja"];
const MAX_ATTEMPTS = 1;
const RETRY_BASE_DELAY_MS = 400;

/**
 * InnerTube (YouTube 内部 API) を「アプリ」のクライアントとして直接叩き、
 * 字幕トラック一覧を取得する。HTML ページのスクレイピング（youtube-transcript
 * パッケージのフォールバック経路）は YouTube のボット判定に引っかかりやすく、
 * 429 / reCAPTCHA ブロックの主な原因になっているため、まずはこちらを試す。
 *
 * clientVersion は YouTube 側の要求変化で失効することがある。動作しなくなった
 * 場合は最新の Android/iOS YouTube アプリのバージョンに更新すること。
 */
const INNERTUBE_CLIENTS = [
  {
    name: "ANDROID",
    context: { client: { clientName: "ANDROID", clientVersion: "20.10.38" } },
    userAgent: "com.google.android.youtube/20.10.38 (Linux; U; Android 14)",
  },
  {
    name: "IOS",
    context: { client: { clientName: "IOS", clientVersion: "20.10.4", deviceModel: "iPhone16,2" } },
    userAgent: "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)",
  },
];

const TIMEDTEXT_USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

class RetryableFetchError extends Error {}

function roundSec(value) {
  return Math.round(Number(value) * 1000) / 1000;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function decodeEntities(text) {
  return String(text || "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)));
}

// srv3 形式 (<p t="ms" d="ms">…</p>) と classic 形式 (<text start="s" dur="s">) の両方に対応。
function parseTimedTextXml(xml) {
  const results = [];
  const pRegex = /<p\s+t="(\d+)"\s+d="(\d+)"[^>]*>([\s\S]*?)<\/p>/g;
  let match;
  while ((match = pRegex.exec(xml)) !== null) {
    const startMs = parseInt(match[1], 10);
    const durMs = parseInt(match[2], 10);
    const inner = match[3];
    let text = "";
    const sRegex = /<s[^>]*>([^<]*)<\/s>/g;
    let sMatch;
    while ((sMatch = sRegex.exec(inner)) !== null) {
      text += sMatch[1];
    }
    if (!text) text = inner.replace(/<[^>]+>/g, "");
    text = decodeEntities(text).trim();
    if (text) {
      results.push({
        start: roundSec(startMs / 1000),
        duration: roundSec(Math.max(durMs / 1000, 0.1)),
        text,
      });
    }
  }
  if (results.length) return results;

  const classicRegex = /<text start="([^"]*)" dur="([^"]*)">([^<]*)<\/text>/g;
  while ((match = classicRegex.exec(xml)) !== null) {
    const text = decodeEntities(match[3]).trim();
    if (!text) continue;
    results.push({
      start: roundSec(parseFloat(match[1])),
      duration: roundSec(Math.max(parseFloat(match[2]), 0.1)),
      text,
    });
  }
  return results;
}

function langMatches(candidate, preferred) {
  const c = String(candidate || "").toLowerCase();
  const p = String(preferred || "").toLowerCase();
  return c === p || c.startsWith(`${p}-`);
}

function selectCaptionTrack(tracks, languages) {
  if (!tracks?.length) return null;
  const manual = tracks.filter((track) => track.kind !== "asr");
  const auto = tracks.filter((track) => track.kind === "asr");
  for (const pool of [manual, auto]) {
    for (const lang of languages) {
      const found = pool.find((track) => langMatches(track.languageCode, lang));
      if (found) return found;
    }
  }
  return manual[0] || auto[0] || null;
}

async function fetchCaptionTracksViaInnertube(videoId, client) {
  const response = await fetch("https://www.youtube.com/youtubei/v1/player?prettyPrint=false", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": client.userAgent,
      "Accept-Language": "en-US,en;q=0.9",
    },
    body: JSON.stringify({ context: client.context, videoId }),
  });

  if (response.status === 429) {
    throw new RetryableFetchError(`InnerTube (${client.name}) rate limited`);
  }
  if (!response.ok) return null;

  const data = await response.json().catch(() => null);
  const tracks = data?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
  return Array.isArray(tracks) && tracks.length ? tracks : null;
}

async function fetchTimedTextBody(baseUrl) {
  const response = await fetch(baseUrl, {
    headers: { "User-Agent": TIMEDTEXT_USER_AGENT, "Accept-Language": "en-US,en;q=0.9" },
  });
  if (response.status === 429) {
    throw new RetryableFetchError("timedtext rate limited");
  }
  if (!response.ok) return [];
  const body = await response.text();
  return parseTimedTextXml(body);
}

/**
 * InnerTube API（アプリクライアント）経由で字幕トラック一覧を取得し、本文を取得する。
 * HTML スクレイピングを行わないため、reCAPTCHA ブロックの主要因を回避できる。
 * 複数クライアントを順に試すことで、片方がブロック／要求バージョン不一致でも
 * もう片方で継続できるようにしている。
 */
async function fetchViaInnertube(videoId, languages) {
  for (const client of INNERTUBE_CLIENTS) {
    let tracks = null;
    try {
      tracks = await fetchCaptionTracksViaInnertube(videoId, client);
    } catch (err) {
      if (!(err instanceof RetryableFetchError)) throw err;
      tracks = null;
    }
    if (!tracks) continue;

    const track = selectCaptionTrack(tracks, languages);
    if (!track?.baseUrl) continue;

    let snippets = [];
    try {
      snippets = await fetchTimedTextBody(track.baseUrl);
    } catch (err) {
      if (!(err instanceof RetryableFetchError)) throw err;
      continue;
    }
    if (snippets.length) {
      return {
        language_code: track.languageCode || languages[0] || "en",
        is_generated: track.kind === "asr",
        snippets,
      };
    }
  }
  return null;
}

function isRetryableFetchError(err) {
  if (err instanceof RetryableFetchError) return true;
  const message = String(err?.message || err || "").toLowerCase();
  return message.includes("429") || message.includes("rate limit") || message.includes("too many");
}

async function fetchTranscriptOnce(videoId, languages = DEFAULT_LANGUAGES) {
  const result = await fetchViaInnertube(videoId, languages);
  if (result) return result;
  throw new Error("日本語・英語の字幕が見つかりませんでした。");
}

export async function fetchNormalizedTranscript(videoId, languages = DEFAULT_LANGUAGES) {
  let lastError = null;

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    try {
      return await fetchTranscriptOnce(videoId, languages);
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err || "字幕の取得に失敗しました。"));
      if (!isRetryableFetchError(err) || attempt >= MAX_ATTEMPTS - 1) {
        throw lastError;
      }
      const jitterMs = Math.floor(Math.random() * 400);
      await sleep(RETRY_BASE_DELAY_MS * 2 ** attempt + jitterMs);
    }
  }

  throw lastError || new Error("字幕の取得に失敗しました。");
}
