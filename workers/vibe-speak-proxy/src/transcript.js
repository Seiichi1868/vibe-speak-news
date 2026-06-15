import {
  fetchTranscript,
  YoutubeTranscriptDisabledError,
  YoutubeTranscriptNotAvailableError,
  YoutubeTranscriptNotAvailableLanguageError,
  YoutubeTranscriptTooManyRequestError,
  YoutubeTranscriptVideoUnavailableError,
} from "youtube-transcript";

const DEFAULT_LANGUAGES = ["en", "ja"];
const MAX_ATTEMPTS = 4;
const RETRY_BASE_DELAY_MS = 2000;

function roundSec(value) {
  return Math.round(Number(value) * 1000) / 1000;
}

function usesMillisecondTiming(items) {
  return items.some((item) => {
    const duration = Number(item.duration);
    return Number.isInteger(duration) && duration > 30;
  });
}

export function mapTranscriptItems(items) {
  const ms = usesMillisecondTiming(items);
  return items
    .map((item) => {
      const offset = Number(item.offset);
      const duration = Number(item.duration);
      const start = ms ? offset / 1000 : offset;
      const dur = ms ? duration / 1000 : duration;
      return {
        start: roundSec(start),
        duration: roundSec(Math.max(dur, 0.1)),
        text: String(item.text || "").trim(),
      };
    })
    .filter((snippet) => snippet.text);
}

function isRetryableFetchError(err) {
  if (err instanceof YoutubeTranscriptTooManyRequestError) return true;
  const message = String(err?.message || err || "").toLowerCase();
  return message.includes("429") || message.includes("rate limit") || message.includes("too many");
}

function isSoftCaptionError(err) {
  return (
    err instanceof YoutubeTranscriptDisabledError ||
    err instanceof YoutubeTranscriptNotAvailableError ||
    err instanceof YoutubeTranscriptNotAvailableLanguageError
  );
}

function mapLibraryError(err) {
  if (err instanceof YoutubeTranscriptTooManyRequestError) {
    return new Error("YouTube へのリクエストが制限されています。しばらく待ってから再試行してください。");
  }
  if (err instanceof YoutubeTranscriptVideoUnavailableError) {
    return new Error("動画が見つからないか、再生できません。");
  }
  if (isSoftCaptionError(err)) {
    return new Error("日本語・英語の字幕が見つかりませんでした。");
  }
  if (err instanceof Error) return err;
  return new Error(String(err || "字幕の取得に失敗しました。"));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchTranscriptOnce(videoId, languages = DEFAULT_LANGUAGES) {
  let lastSoftError = null;
  let sawRateLimit = false;

  for (const lang of languages) {
    try {
      const items = await fetchTranscript(videoId, { lang });
      const snippets = mapTranscriptItems(items);
      if (snippets.length) {
        return {
          language_code: lang,
          is_generated: false,
          snippets,
        };
      }
    } catch (err) {
      if (isSoftCaptionError(err)) {
        lastSoftError = err;
        continue;
      }
      if (isRetryableFetchError(err)) {
        sawRateLimit = true;
        continue;
      }
      throw mapLibraryError(err);
    }
  }

  try {
    const items = await fetchTranscript(videoId, {});
    const snippets = mapTranscriptItems(items);
    if (!snippets.length) {
      throw new Error("字幕データを解析できませんでした。");
    }
    return {
      language_code: items[0]?.lang || languages.find((lang) => lang === "en") || "en",
      is_generated: true,
      snippets,
    };
  } catch (err) {
    if (sawRateLimit || isRetryableFetchError(err)) {
      throw mapLibraryError(err);
    }
    if (isSoftCaptionError(err) || lastSoftError) {
      throw mapLibraryError(lastSoftError || err);
    }
    throw mapLibraryError(err);
  }
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
      await sleep(RETRY_BASE_DELAY_MS * 2 ** attempt);
    }
  }

  throw lastError || new Error("字幕の取得に失敗しました。");
}
