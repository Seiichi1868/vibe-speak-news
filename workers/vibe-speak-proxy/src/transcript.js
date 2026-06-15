import {
  fetchTranscript,
  YoutubeTranscriptDisabledError,
  YoutubeTranscriptNotAvailableError,
  YoutubeTranscriptNotAvailableLanguageError,
  YoutubeTranscriptTooManyRequestError,
  YoutubeTranscriptVideoUnavailableError,
} from "youtube-transcript";

const DEFAULT_LANGUAGES = ["ja", "en"];

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

function mapLibraryError(err) {
  if (err instanceof YoutubeTranscriptTooManyRequestError) {
    return new Error("YouTube へのリクエストが制限されています。しばらく待ってから再試行してください。");
  }
  if (err instanceof YoutubeTranscriptVideoUnavailableError) {
    return new Error("動画が見つからないか、再生できません。");
  }
  if (
    err instanceof YoutubeTranscriptDisabledError ||
    err instanceof YoutubeTranscriptNotAvailableError ||
    err instanceof YoutubeTranscriptNotAvailableLanguageError
  ) {
    return new Error("日本語・英語の字幕が見つかりませんでした。");
  }
  if (err instanceof Error) return err;
  return new Error(String(err || "字幕の取得に失敗しました。"));
}

export async function fetchNormalizedTranscript(videoId, languages = DEFAULT_LANGUAGES) {
  let lastLanguageError = null;

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
      if (err instanceof YoutubeTranscriptNotAvailableLanguageError) {
        lastLanguageError = err;
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
      language_code: items[0]?.lang || languages[0] || "en",
      is_generated: true,
      snippets,
    };
  } catch (err) {
    if (lastLanguageError) {
      throw mapLibraryError(lastLanguageError);
    }
    throw mapLibraryError(err);
  }
}
