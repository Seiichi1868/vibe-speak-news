import { fetchTranscript } from "youtube-transcript";

const DEFAULT_LANGUAGES = ["en", "ja"];
const MAX_ATTEMPTS = 2;
const RETRY_BASE_DELAY_MS = 800;
const CONSENT_COOKIE = "CONSENT=YES+; SOCS=CAI; PREF=hl=en&tz=UTC";
const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

/**
 * InnerTube で字幕トラック URL を取り、署名付き timedtext から本文も取得する。
 * 以前動いていた決め手は「Worker が snippets まで返す + 3日キャッシュ」。
 * トラックだけ返してブラウザに本文取得を任せる方式は、Worker が 502 のときに落ちる。
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

class RetryableFetchError extends Error {}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

function decodeXmlEntities(text) {
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

function parseTimedTextXml(xml) {
  const results = [];
  const pRegex = /<p\b([^>]*)>([\s\S]*?)<\/p>/g;
  const sRegex = /<s[^>]*>([^<]*)<\/s>/g;
  let match;
  while ((match = pRegex.exec(xml || "")) !== null) {
    const attrs = match[1] || "";
    const tMatch = attrs.match(/\bt="(\d+)"/);
    const dMatch = attrs.match(/\bd="(\d+)"/);
    if (!tMatch || !dMatch) continue;
    const startMs = parseInt(tMatch[1], 10);
    const durMs = parseInt(dMatch[1], 10);
    const inner = match[2] || "";
    let text = "";
    let sMatch;
    sRegex.lastIndex = 0;
    while ((sMatch = sRegex.exec(inner)) !== null) {
      text += sMatch[1];
    }
    if (!text) text = inner.replace(/<[^>]+>/g, "");
    text = decodeXmlEntities(text).trim();
    if (!text) continue;
    results.push({
      start: Math.round((startMs / 1000) * 1000) / 1000,
      duration: Math.round(Math.max(durMs / 1000, 0.1) * 1000) / 1000,
      text,
    });
  }
  if (results.length) return results;

  const classicRegex = /<text start="([^"]*)" dur="([^"]*)">([^<]*)<\/text>/g;
  while ((match = classicRegex.exec(xml || "")) !== null) {
    const text = decodeXmlEntities(match[3]).trim();
    if (!text) continue;
    results.push({
      start: Math.round(parseFloat(match[1]) * 1000) / 1000,
      duration: Math.round(Math.max(parseFloat(match[2]), 0.1) * 1000) / 1000,
      text,
    });
  }
  return results;
}

function publicCaptionTracks(tracks) {
  return (tracks || [])
    .filter((track) => track?.baseUrl)
    .map((track) => ({
      languageCode: track.languageCode || "",
      kind: track.kind || "",
      baseUrl: track.baseUrl,
    }));
}

function payloadFromTracks(captionTracks, languages, snippets) {
  const selected = selectCaptionTrack(captionTracks, languages);
  return {
    language_code: selected?.languageCode || languages[0] || "en",
    is_generated: selected?.kind === "asr",
    snippets: snippets || [],
    caption_tracks: captionTracks,
  };
}

async function fetchCaptionTracksViaInnertube(videoId, client) {
  const response = await fetch("https://www.youtube.com/youtubei/v1/player?prettyPrint=false", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": client.userAgent,
      "Accept-Language": "en-US,en;q=0.9",
      Origin: "https://www.youtube.com",
      Referer: "https://www.youtube.com/",
      Cookie: CONSENT_COOKIE,
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

async function fetchTimedTextSnippets(baseUrl) {
  if (!baseUrl) return [];
  const response = await fetch(baseUrl, {
    headers: {
      "User-Agent": BROWSER_UA,
      "Accept-Language": "en-US,en;q=0.9",
      Referer: "https://www.youtube.com/",
      Cookie: CONSENT_COOKIE,
    },
  });
  if (response.status === 429) {
    throw new RetryableFetchError("timedtext rate limited");
  }
  if (!response.ok) return [];
  const xml = await response.text();
  return parseTimedTextXml(xml);
}

async function fetchViaInnertube(videoId, languages) {
  let tracksOnly = null;
  for (const client of INNERTUBE_CLIENTS) {
    let tracks = null;
    try {
      tracks = await fetchCaptionTracksViaInnertube(videoId, client);
    } catch (err) {
      if (!(err instanceof RetryableFetchError)) throw err;
      tracks = null;
    }
    if (!tracks?.length) continue;

    const captionTracks = publicCaptionTracks(tracks);
    if (!captionTracks.length) continue;
    if (!tracksOnly) tracksOnly = payloadFromTracks(captionTracks, languages, []);

    const selected = selectCaptionTrack(captionTracks, languages);
    if (!selected?.baseUrl) continue;
    try {
      const snippets = await fetchTimedTextSnippets(selected.baseUrl);
      if (snippets.length) {
        return payloadFromTracks(captionTracks, languages, snippets);
      }
    } catch (err) {
      if (!(err instanceof RetryableFetchError)) throw err;
    }
  }
  return tracksOnly;
}

function extractJsonObject(html, marker) {
  const startToken = html.indexOf(marker);
  if (startToken < 0) return null;
  const jsonStart = html.indexOf("{", startToken);
  if (jsonStart < 0) return null;
  let depth = 0;
  for (let i = jsonStart; i < html.length; i += 1) {
    if (html[i] === "{") depth += 1;
    else if (html[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        try {
          return JSON.parse(html.slice(jsonStart, i + 1));
        } catch (_err) {
          return null;
        }
      }
    }
  }
  return null;
}

function tracksFromPlayerResponse(data) {
  const tracks = data?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
  return Array.isArray(tracks) && tracks.length ? tracks : null;
}

async function fetchViaWatchPage(videoId, languages) {
  const headers = {
    "User-Agent": BROWSER_UA,
    "Accept-Language": "en-US,en;q=0.9",
    Cookie: CONSENT_COOKIE,
  };

  const page = await fetch(`https://www.youtube.com/watch?v=${videoId}&hl=en`, { headers });
  if (!page.ok) return null;
  const html = await page.text();
  if (html.includes("g-recaptcha") && !html.includes("ytInitialPlayerResponse")) return null;
  const player = extractJsonObject(html, "ytInitialPlayerResponse");
  const captionTracks = publicCaptionTracks(tracksFromPlayerResponse(player));
  if (!captionTracks.length) return null;

  const selected = selectCaptionTrack(captionTracks, languages);
  let snippets = [];
  if (selected?.baseUrl) {
    try {
      snippets = await fetchTimedTextSnippets(selected.baseUrl);
    } catch (err) {
      if (!(err instanceof RetryableFetchError)) throw err;
    }
  }
  return payloadFromTracks(captionTracks, languages, snippets);
}

function isRetryableFetchError(err) {
  if (err instanceof RetryableFetchError) return true;
  const message = String(err?.message || err || "").toLowerCase();
  return message.includes("429") || message.includes("rate limit") || message.includes("too many");
}

function mapLibraryItems(items) {
  const ms = (items || []).some((item) => {
    const duration = Number(item.duration);
    return Number.isInteger(duration) && duration > 30;
  });
  return (items || [])
    .map((item) => {
      const offset = Number(item.offset);
      const duration = Number(item.duration);
      const start = ms ? offset / 1000 : offset;
      const dur = ms ? duration / 1000 : duration;
      const text = String(item.text || "").trim();
      if (!text) return null;
      return {
        start: Math.round(start * 1000) / 1000,
        duration: Math.round(Math.max(dur, 0.1) * 1000) / 1000,
        text,
      };
    })
    .filter(Boolean);
}

async function fetchViaLibrary(videoId, languages) {
  for (const lang of languages) {
    try {
      const items = await fetchTranscript(videoId, { lang });
      const snippets = mapLibraryItems(items);
      if (snippets.length) {
        return { language_code: lang, is_generated: false, snippets };
      }
    } catch (_err) {
      /* try next language */
    }
  }
  try {
    const items = await fetchTranscript(videoId, {});
    const snippets = mapLibraryItems(items);
    if (snippets.length) {
      return {
        language_code: items[0]?.lang || languages[0] || "en",
        is_generated: true,
        snippets,
      };
    }
  } catch (_err) {
    /* InnerTube / watch already tried */
  }
  return null;
}

async function fetchTranscriptOnce(videoId, languages = DEFAULT_LANGUAGES) {
  const innertube = await fetchViaInnertube(videoId, languages);
  if (innertube?.snippets?.length) return innertube;
  const watchPage = await fetchViaWatchPage(videoId, languages);
  if (watchPage?.snippets?.length) return watchPage;
  const library = await fetchViaLibrary(videoId, languages);
  if (library?.snippets?.length) return library;
  if (innertube?.caption_tracks?.length) return innertube;
  if (watchPage?.caption_tracks?.length) return watchPage;
  throw new Error("日本語・英語の字幕が見つかりませんでした。");
}

export async function fetchNormalizedTranscript(videoId, languages = DEFAULT_LANGUAGES) {
  let lastError = null;

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    try {
      const result = await fetchTranscriptOnce(videoId, languages);
      if (result?.snippets?.length || result?.caption_tracks?.length) return result;
      lastError = new Error("日本語・英語の字幕が見つかりませんでした。");
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err || "字幕の取得に失敗しました。"));
    }
    if (attempt >= MAX_ATTEMPTS - 1) break;
    const jitterMs = Math.floor(Math.random() * 400);
    await sleep(RETRY_BASE_DELAY_MS * 2 ** attempt + jitterMs);
  }

  throw lastError || new Error("字幕の取得に失敗しました。");
}

export async function fetchTimedTextFromUrl(timedTextUrl) {
  const snippets = await fetchTimedTextSnippets(timedTextUrl);
  if (!snippets.length) {
    throw new Error("日本語・英語の字幕が見つかりませんでした。");
  }
  return { language_code: "en", is_generated: true, snippets };
}
