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

/**
 * InnerTube では字幕トラック URL だけを返す。本文（timedtext）はデータセンター IP
 * から空になりやすいので、ブラウザ側で取得する。
 */
function publicCaptionTracks(tracks) {
  return (tracks || [])
    .filter((track) => track?.baseUrl)
    .map((track) => ({
      languageCode: track.languageCode || "",
      kind: track.kind || "",
      baseUrl: track.baseUrl,
    }));
}

async function fetchViaInnertube(videoId, languages) {
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

    const selected = selectCaptionTrack(captionTracks, languages);
    return {
      language_code: selected?.languageCode || languages[0] || "en",
      is_generated: selected?.kind === "asr",
      snippets: [],
      caption_tracks: captionTracks,
    };
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
