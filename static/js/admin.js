(function () {
  const CEFR_LEVELS = window.CEFR_LEVELS || ["A2", "B1", "B2"];

  const classSelect = document.getElementById("class-select");
  const newClassName = document.getElementById("new-class-name");
  const createClassBtn = document.getElementById("create-class-btn");
  const reloadClassBtn = document.getElementById("reload-class-btn");
  const classMessage = document.getElementById("class-message");
  const lessonForm = document.getElementById("lesson-form");
  const lessonMessage = document.getElementById("lesson-message");
  const lessonClassId = document.getElementById("lesson-class-id");
  const lessonClassLabel = document.getElementById("lesson-class-label");
  const archiveBtn = document.getElementById("archive-btn");
  const archiveTitle = document.getElementById("archive-title");
  const archiveSummary = document.getElementById("archive-summary");
  const archiveList = document.getElementById("archive-list");
  const archiveEmptyMessage = document.getElementById("archive-empty-message");
  const resetLessonBtn = document.getElementById("reset-lesson-btn");
  const settingsForm = document.getElementById("settings-form");
  const settingsMessage = document.getElementById("settings-message");
  const adminSettingsLock = document.getElementById("admin-settings-lock");
  const adminSettingsPassword = document.getElementById("admin-settings-password");
  const adminSettingsUnlock = document.getElementById("admin-settings-unlock");
  const adminSettingsLockMessage = document.getElementById("admin-settings-lock-message");
  const generateLinkBtn = document.getElementById("generate-link-btn");
  const copyShareLinkBtn = document.getElementById("copy-share-link-btn");
  const shareLinkOutput = document.getElementById("share-link-output");
  const cnn10OpenBtn = document.getElementById("cnn10-open-btn");
  const cnn10Panel = document.getElementById("cnn10-panel");
  const cnn10CloseBtn = document.getElementById("cnn10-close-btn");
  const cnn10List = document.getElementById("cnn10-list");
  const cnn10Message = document.getElementById("cnn10-message");
  const cnn10MoreBtn = document.getElementById("cnn10-more-btn");
  const tabLesson = document.getElementById("tab-lesson");
  const tabResults = document.getElementById("tab-results");
  const resultsClassFilter = document.getElementById("results-class-filter");
  const resultsLessonFilter = document.getElementById("results-lesson-filter");
  const resultsLoadBtn = document.getElementById("results-load-btn");
  const resultsExportBtn = document.getElementById("results-export-btn");
  const resultsSelectAllBtn = document.getElementById("results-select-all-btn");
  const resultsDeleteSelectedBtn = document.getElementById("results-delete-selected-btn");
  const resultsSortKey = document.getElementById("results-sort-key");
  const resultsSortDirection = document.getElementById("results-sort-direction");
  const resultsTable = document.getElementById("results-table");
  const resultsTbody = document.getElementById("results-tbody");
  const resultsEmpty = document.getElementById("results-empty");
  const rosterFileInput = document.getElementById("roster-file-input");
  const rosterUploadBtn = document.getElementById("roster-upload-btn");
  const rosterMessage = document.getElementById("roster-message");
  let adminClasses = window.ADMIN_CLASSES || [];
  let adminSettingsPasswordValue = "";
  let latestSubmissions = [];
  let allResultsSelected = false;
  let cnn10NextOffset = 0;
  let cnn10HasMore = false;
  let cnn10Loading = false;
  let cnn10OpenPreviewRow = null;
  const transcriptClientCache = new Map();
  let suppressAutoScriptFill = false;
  let scriptAutoManaged = false;
  let autoScriptTimer = null;
  let autoScriptRequestId = 0;

  function showMessage(el, text, isError) {
    if (!el) return;
    el.textContent = text;
    el.classList.remove("hidden", "text-emerald-600", "text-red-600", "text-amber-800");
    el.classList.add(isError ? "text-red-600" : "text-emerald-600");
  }

  function showCnn10Panel() {
    if (!cnn10Panel) return;
    cnn10Panel.classList.remove("hidden");
    cnn10Panel.classList.add("flex");
  }

  function hideCnn10Panel() {
    if (!cnn10Panel) return;
    if (cnn10OpenPreviewRow) {
      const prevPanel = cnn10OpenPreviewRow.querySelector("[data-cnn10-preview]");
      const prevThumb = cnn10OpenPreviewRow.querySelector("[data-cnn10-thumb]");
      const prevIframe = cnn10OpenPreviewRow.querySelector("iframe");
      prevPanel?.classList.add("hidden");
      prevThumb?.classList.remove("ring-2", "ring-sky-400");
      if (prevIframe) prevIframe.src = prevIframe.src;
      cnn10OpenPreviewRow = null;
    }
    cnn10Panel.classList.add("hidden");
    cnn10Panel.classList.remove("flex");
  }

  function parseLessonTime(text) {
    const raw = String(text || "").trim();
    if (!raw) return null;
    const normalized = raw.replace(/\s*秒\s*$/i, "").trim();
    if (/^\d+$/.test(normalized)) return parseInt(normalized, 10);
    if (normalized.includes(":")) {
      const parts = normalized.split(":").map((part) => parseInt(part, 10));
      if (parts.some((value) => !Number.isFinite(value))) return null;
      if (parts.length === 2) return parts[0] * 60 + parts[1];
      if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
      return null;
    }
    return null;
  }

  function getVideoIdFromLessonUrl() {
    const url = document.getElementById("youtube-url")?.value.trim() || "";
    if (/^[a-zA-Z0-9_-]{11}$/.test(url)) return url;
    const match = url.match(/(?:v=|vi=|\/)([0-9A-Za-z_-]{11})(?=$|[^0-9A-Za-z_-])/i);
    return match ? match[1] : "";
  }

  async function fetchYoutubeTranscriptClient({ videoId, startSec = null, endSec = null } = {}) {
    if (!window.YoutubeTranscript?.fetchTranscript) {
      throw new Error("字幕取得モジュールが読み込まれていません。ページを再読み込みしてください。");
    }

    const cacheKey = `${videoId || ""}:${startSec ?? ""}:${endSec ?? ""}`;
    if (transcriptClientCache.has(cacheKey)) {
      return transcriptClientCache.get(cacheKey);
    }

    try {
      const data = await window.YoutubeTranscript.fetchTranscript(videoId, {
        languages: ["en", "ja"],
        startSec,
        endSec,
      });
      transcriptClientCache.set(cacheKey, data);
      return data;
    } catch (err) {
      throw err instanceof Error ? err : new Error(String(err || "文字起こしの取得に失敗しました。"));
    }
  }

  async function fetchYoutubeHighlight(title, snippets) {
    const res = await fetch("/admin/api/youtube/highlight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        snippets: snippets || [],
      }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "区間推定に失敗しました。");
    return data.highlight || null;
  }

  async function autoFillLessonScriptFromTranscript() {
    if (suppressAutoScriptFill) return;

    const startEl = document.getElementById("start-time");
    const endEl = document.getElementById("end-time");
    const scriptEl = document.getElementById("lesson-script");
    if (!startEl || !endEl || !scriptEl) return;

    const videoId = getVideoIdFromLessonUrl();
    const startSec = parseLessonTime(startEl.value);
    const endSec = parseLessonTime(endEl.value);
    if (!videoId || startSec === null || endSec === null || endSec <= startSec) return;

    const currentScript = scriptEl.value.trim();
    if (currentScript && !scriptAutoManaged) return;

    const requestId = ++autoScriptRequestId;
    scriptEl.placeholder = "文字起こしを取得中…";

    try {
      const data = await fetchYoutubeTranscriptClient({
        videoId,
        startSec,
        endSec,
      });
      if (requestId !== autoScriptRequestId) return;

      scriptEl.value = data.script || "";
      scriptEl.placeholder = "英文スクリプトをここに貼り付け…";
      scriptAutoManaged = true;
      if (lessonMessage) {
        showMessage(
          lessonMessage,
          "指定時間のスクリプトを自動入力しました。内容を確認して保存してください。",
          false
        );
      }
    } catch (err) {
      if (requestId !== autoScriptRequestId) return;
      scriptEl.placeholder = "英文スクリプトをここに貼り付け…";
      if (lessonMessage) {
        showMessage(lessonMessage, err.message || "文字起こしの自動取得に失敗しました。", true);
      }
    }
  }

  function scheduleAutoScriptFill() {
    if (autoScriptTimer) clearTimeout(autoScriptTimer);
    autoScriptTimer = setTimeout(() => {
      autoScriptTimer = null;
      autoFillLessonScriptFromTranscript();
    }, 600);
  }

  function selectCnn10EpisodeForLesson(episode, highlight) {
    const urlEl = document.getElementById("youtube-url");
    const startEl = document.getElementById("start-time");
    const endEl = document.getElementById("end-time");
    const scriptEl = document.getElementById("lesson-script");

    suppressAutoScriptFill = true;
    if (urlEl) urlEl.value = episode.url || "";
    if (highlight?.ok) {
      if (startEl) startEl.value = highlight.start_display || formatTime(highlight.start_sec);
      if (endEl) endEl.value = highlight.end_display || formatTime(highlight.end_sec);
    } else {
      if (startEl) startEl.value = "";
      if (endEl) endEl.value = "";
    }
    if (scriptEl) {
      scriptEl.value = "";
      scriptEl.placeholder = highlight?.ok
        ? "開始・終了時間を確認するとスクリプトが自動入力されます…"
        : "開始・終了時間を入力すると自動入力されます…";
    }
    suppressAutoScriptFill = false;
    scriptAutoManaged = true;

    hideCnn10Panel();
    document.querySelector('.tab-btn[data-tab="lesson"]')?.click();
    startEl?.focus();
    if (lessonMessage) {
      showMessage(
        lessonMessage,
        highlight?.ok
          ? "動画とAI推定区間を授業設定に反映しました。内容を確認して保存してください。"
          : "動画を授業設定に反映しました。開始・終了時間を入力するとスクリプトが自動入力されます。",
        false
      );
    }
    scheduleAutoScriptFill();
  }

  function updateCnn10MoreButton() {
    if (!cnn10MoreBtn) return;
    cnn10MoreBtn.classList.toggle("hidden", !cnn10HasMore);
    cnn10MoreBtn.disabled = cnn10Loading;
    cnn10MoreBtn.textContent = cnn10Loading ? "読み込み中…" : "さらに古い動画を見る";
  }

  async function loadCnn10Transcript(videoId, episodeTitle, transcriptMeta, transcriptText, highlightBanner) {
    transcriptText.textContent = "文字起こしを読み込み中…";
    transcriptText.classList.remove("font-mono");
    if (highlightBanner) {
      highlightBanner.classList.add("hidden");
      highlightBanner.innerHTML = "";
    }
    transcriptMeta.classList.add("hidden");

    const data = await fetchYoutubeTranscriptClient({ videoId });
    let highlight = null;
    if (episodeTitle) {
      try {
        highlight = await fetchYoutubeHighlight(episodeTitle, data.all_snippets || data.snippets || []);
      } catch (err) {
        highlight = { ok: false, error: err.message || "区間推定に失敗しました。" };
      }
    }

    renderCnn10Transcript(transcriptText, data.snippets || [], highlight, highlightBanner);

    const kind = data.is_generated ? "自動生成" : "手動";
    let metaText = `${data.language || "English"} (${kind})`;
    if (highlight?.ok) {
      metaText += ` · AI推定区間 ${highlight.start_display}–${highlight.end_display} (${highlight.confidence})`;
    }
    transcriptMeta.textContent = metaText;
    transcriptMeta.classList.remove("hidden");
    return { ...data, highlight };
  }

  function renderCnn10Transcript(container, snippets, highlight, highlightBanner) {
    container.innerHTML = "";
    container.classList.remove("font-mono");

    if (highlightBanner) {
      if (highlight?.ok) {
        highlightBanner.classList.remove("hidden");
        highlightBanner.className =
          "mb-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[10px] text-amber-950";

        const label = document.createElement("p");
        label.textContent = `タイトルに対応する区間（AI推定・要確認）: ${highlight.start_display} – ${highlight.end_display}`;
        highlightBanner.appendChild(label);

        if (highlight.note) {
          const note = document.createElement("p");
          note.className = "mt-0.5 text-[10px] text-amber-800/90";
          note.textContent = highlight.note;
          highlightBanner.appendChild(note);
        }

        const applyBtn = document.createElement("button");
        applyBtn.type = "button";
        applyBtn.className =
          "mt-1 rounded border border-amber-300 bg-white px-2 py-0.5 text-[10px] font-semibold text-amber-900 hover:bg-amber-100";
        applyBtn.textContent = "開始・終了時刻に反映";
        applyBtn.addEventListener("click", () => {
          applyCnn10HighlightToLesson(highlight);
        });
        highlightBanner.appendChild(applyBtn);
      } else if (highlight?.error) {
        highlightBanner.classList.remove("hidden");
        highlightBanner.className =
          "mb-2 rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-[10px] text-slate-600";
        highlightBanner.textContent = highlight.error;
      } else {
        highlightBanner.classList.add("hidden");
        highlightBanner.innerHTML = "";
      }
    }

    if (!snippets.length) {
      container.textContent = "（文字起こしが空です）";
      container.classList.add("font-mono");
      return;
    }

    const startSec = highlight?.ok ? highlight.start_sec : null;
    const endSec = highlight?.ok ? highlight.end_sec : null;

    snippets.forEach((snippet) => {
      const line = document.createElement("div");
      const start = Number(snippet.start) || 0;
      const inRange =
        startSec !== null && endSec !== null && start >= startSec && start < endSec;
      line.className = inRange
        ? "rounded bg-amber-100/90 px-1 py-0.5 -mx-1 font-mono text-[10px] leading-relaxed text-slate-800"
        : "font-mono text-[10px] leading-relaxed text-slate-700";
      line.textContent = `${formatTime(start)}  ${snippet.text || ""}`;
      container.appendChild(line);
    });
  }

  function applyCnn10HighlightToLesson(highlight) {
    if (!highlight?.ok) return;
    const startEl = document.getElementById("start-time");
    const endEl = document.getElementById("end-time");
    if (startEl) startEl.value = highlight.start_display || formatTime(highlight.start_sec);
    if (endEl) endEl.value = highlight.end_display || formatTime(highlight.end_sec);
    scriptAutoManaged = true;
    hideCnn10Panel();
    document.querySelector('.tab-btn[data-tab="lesson"]')?.click();
    scheduleAutoScriptFill();
    if (lessonMessage) {
      showMessage(
        lessonMessage,
        "AI推定区間を開始・終了時刻に反映しました。内容を確認して保存してください。",
        false
      );
    }
  }

  function createCnn10EpisodeRow(episode) {
    const videoUrl = episode.url || "#";
    const thumbnailUrl =
      episode.thumbnail_url ||
      (episode.video_id ? `https://i.ytimg.com/vi/${episode.video_id}/mqdefault.jpg` : "");

    const row = document.createElement("div");
    row.className = "rounded-lg border border-teal-50 bg-white/70 px-2 py-2";
    row.dataset.videoId = episode.video_id || "";

    const main = document.createElement("div");
    main.className = "flex items-start gap-3";

    const thumbBtn = document.createElement("button");
    thumbBtn.type = "button";
    thumbBtn.title = "プレビューを表示";
    thumbBtn.dataset.cnn10Thumb = "1";
    thumbBtn.className =
      "block shrink-0 overflow-hidden rounded border border-slate-100 bg-slate-100 hover:ring-2 hover:ring-sky-300";
    thumbBtn.innerHTML = `
      <img src="${esc(thumbnailUrl)}" alt="" loading="lazy" width="112" height="63"
        class="aspect-video h-16 w-28 object-cover pointer-events-none"
        onerror="this.closest('button')?.classList.add('hidden')">`;

    const body = document.createElement("div");
    body.className = "min-w-0 flex-1";

    const published = document.createElement("p");
    published.className = "text-[11px] font-semibold text-slate-500";
    published.textContent = episode.published || "";

    const title = document.createElement("p");
    title.className = "mt-0.5 font-semibold text-slate-800";
    title.textContent = episode.title || "Untitled";

    const urlLine = document.createElement("p");
    urlLine.className = "mt-0.5 truncate font-mono text-[10px] text-slate-500";
    const urlLink = document.createElement("a");
    urlLink.className = "text-sky-600 hover:text-sky-800 hover:underline";
    urlLink.href = videoUrl;
    urlLink.target = "_blank";
    urlLink.rel = "noopener noreferrer";
    urlLink.textContent = videoUrl !== "#" ? videoUrl : "";
    urlLink.title = videoUrl;
    urlLine.appendChild(urlLink);

    const actions = document.createElement("div");
    actions.className = "mt-1 flex flex-wrap items-center gap-2";

    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className =
      "rounded-full border border-sky-200 bg-sky-600 px-2.5 py-0.5 text-[11px] font-semibold text-white hover:bg-sky-500";
    selectBtn.textContent = "授業に設定";

    const openLink = document.createElement("a");
    openLink.className = "text-[11px] font-medium text-sky-600 hover:text-sky-800";
    openLink.href = videoUrl;
    openLink.target = "_blank";
    openLink.rel = "noopener noreferrer";
    openLink.textContent = "YouTubeで開く";

    const previewPanel = document.createElement("div");
    previewPanel.dataset.cnn10Preview = "1";
    previewPanel.className = "mt-2 hidden rounded border border-slate-100 bg-slate-50/80 p-2";

    const previewGrid = document.createElement("div");
    previewGrid.className = "grid gap-2 md:grid-cols-2";

    const videoWrap = document.createElement("div");
    videoWrap.className = "aspect-video overflow-hidden rounded border border-slate-100 bg-black";
    const iframe = document.createElement("iframe");
    iframe.className = "h-full w-full";
    iframe.src = episode.video_id
      ? `https://www.youtube.com/embed/${encodeURIComponent(episode.video_id)}?rel=0&modestbranding=1`
      : "";
    iframe.title = episode.title || "YouTube preview";
    iframe.loading = "lazy";
    iframe.allow =
      "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    iframe.allowFullscreen = true;
    videoWrap.appendChild(iframe);

    const transcriptWrap = document.createElement("div");
    transcriptWrap.className = "flex min-h-[10rem] flex-col";

    const transcriptMeta = document.createElement("p");
    transcriptMeta.className = "mb-1 hidden text-[10px] text-slate-500";

    const highlightBanner = document.createElement("div");
    highlightBanner.className = "mb-1 hidden";

    const transcriptText = document.createElement("div");
    transcriptText.className =
      "min-h-[10rem] flex-1 overflow-y-auto rounded border border-slate-100 bg-white/80 p-2 leading-relaxed";

    transcriptWrap.appendChild(transcriptMeta);
    transcriptWrap.appendChild(highlightBanner);
    transcriptWrap.appendChild(transcriptText);
    previewGrid.appendChild(videoWrap);
    previewGrid.appendChild(transcriptWrap);
    previewPanel.appendChild(previewGrid);

    actions.appendChild(selectBtn);
    actions.appendChild(openLink);
    body.appendChild(published);
    body.appendChild(title);
    body.appendChild(urlLine);
    body.appendChild(actions);
    main.appendChild(thumbBtn);
    main.appendChild(body);
    row.appendChild(main);
    row.appendChild(previewPanel);

    let transcriptLoaded = false;
    let transcriptLoading = false;
    let episodeHighlight = null;

    selectBtn.addEventListener("click", () => {
      selectCnn10EpisodeForLesson(episode, episodeHighlight);
    });

    async function togglePreview() {
      if (cnn10OpenPreviewRow === row) {
        previewPanel.classList.add("hidden");
        thumbBtn.classList.remove("ring-2", "ring-sky-400");
        iframe.src = iframe.src;
        cnn10OpenPreviewRow = null;
        return;
      }

      if (cnn10OpenPreviewRow) {
        const prevPanel = cnn10OpenPreviewRow.querySelector("[data-cnn10-preview]");
        const prevThumb = cnn10OpenPreviewRow.querySelector("[data-cnn10-thumb]");
        const prevIframe = cnn10OpenPreviewRow.querySelector("iframe");
        prevPanel?.classList.add("hidden");
        prevThumb?.classList.remove("ring-2", "ring-sky-400");
        if (prevIframe) prevIframe.src = prevIframe.src;
      }

      cnn10OpenPreviewRow = row;
      previewPanel.classList.remove("hidden");
      thumbBtn.classList.add("ring-2", "ring-sky-400");

      if (!episode.video_id) {
        transcriptText.textContent = "動画 ID がありません。";
        return;
      }

      if (transcriptLoaded || transcriptLoading) return;

      transcriptLoading = true;
      try {
        const data = await loadCnn10Transcript(
          episode.video_id,
          episode.title || "",
          transcriptMeta,
          transcriptText,
          highlightBanner
        );
        episodeHighlight = data.highlight?.ok ? data.highlight : null;
        transcriptLoaded = true;
      } catch (err) {
        transcriptText.textContent = "";
        if (cnn10Message) {
          cnn10Message.textContent = err.message || "文字起こしの取得に失敗しました。";
          cnn10Message.classList.remove("hidden");
        }
      } finally {
        transcriptLoading = false;
      }
    }

    thumbBtn.addEventListener("click", () => {
      togglePreview();
    });

    return row;
  }

  function appendCnn10Episodes(episodes) {
    if (!cnn10List || !episodes.length) return;
    episodes.forEach((episode) => {
      cnn10List.appendChild(createCnn10EpisodeRow(episode));
    });
  }

  async function loadCnn10Episodes(reset = true) {
    if (cnn10Loading) return;

    if (reset) {
      cnn10NextOffset = 0;
      cnn10HasMore = false;
      cnn10OpenPreviewRow = null;
      if (cnn10Message) {
        cnn10Message.classList.add("hidden");
        cnn10Message.textContent = "";
      }
      if (cnn10List) {
        cnn10List.innerHTML =
          '<p class="rounded border border-slate-100 bg-slate-50 px-2 py-2 text-slate-500">読み込み中…</p>';
      }
    }

    cnn10Loading = true;
    updateCnn10MoreButton();

    try {
      const res = await fetch(`/admin/api/cnn10/episodes?offset=${cnn10NextOffset}&limit=10`);
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "CNN10 の取得に失敗しました。");

      const episodes = data.episodes || [];
      if (reset) {
        if (!episodes.length) {
          cnn10List.innerHTML =
            '<p class="rounded border border-slate-100 bg-slate-50 px-2 py-2 text-slate-500">動画一覧がありません。</p>';
        } else {
          cnn10List.innerHTML = "";
          appendCnn10Episodes(episodes);
        }
      } else {
        appendCnn10Episodes(episodes);
      }

      cnn10NextOffset = data.next_offset ?? cnn10NextOffset + episodes.length;
      cnn10HasMore = !!data.has_more;
    } catch (err) {
      if (reset && cnn10List) cnn10List.innerHTML = "";
      if (cnn10Message) {
        cnn10Message.textContent = err.message || "CNN10 の取得に失敗しました。";
        cnn10Message.classList.remove("hidden");
      }
    } finally {
      cnn10Loading = false;
      updateCnn10MoreButton();
    }
  }

  async function loadMoreCnn10Episodes() {
    if (!cnn10HasMore || cnn10Loading) return;
    await loadCnn10Episodes(false);
  }

  function getSelectedClassId() {
    return classSelect ? classSelect.value.trim() : "";
  }

  function collectDefaultCriteria() {
    const criteria = {};
    CEFR_LEVELS.forEach((lv) => {
      const el = document.getElementById(`default-criteria-${lv}`);
      criteria[lv] = el ? el.value.trim() : "";
    });
    return criteria;
  }

  function collectClassCriteria() {
    const criteria = {};
    CEFR_LEVELS.forEach((lv) => {
      const el = document.getElementById(`class-criteria-${lv}`);
      criteria[lv] = el ? el.value.trim() : "";
    });
    return criteria;
  }

  function fillLessonForm(cls) {
    if (!cls || !cls.current) return;
    const c = cls.current;
    suppressAutoScriptFill = true;
    document.getElementById("youtube-url").value = c.source_url || "";
    document.getElementById("start-time").value = formatTime(c.start_seconds || 0);
    document.getElementById("end-time").value = formatTime(c.end_seconds || 0);
    document.getElementById("lesson-script").value = c.script || "";
    document.getElementById("prep-timer-seconds").value = c.prep_timer_seconds ?? 60;
    document.getElementById("record-timer-seconds").value = c.record_timer_seconds ?? 60;
    document.getElementById("timers-visible").checked = c.timers_visible !== false;
    document.getElementById("subtitles-enabled").checked = c.subtitles_enabled === true;
    scriptAutoManaged = false;
    suppressAutoScriptFill = false;
    if (lessonClassId) lessonClassId.value = cls.id;
    if (lessonClassLabel) lessonClassLabel.textContent = cls.name;
    CEFR_LEVELS.forEach((lv) => {
      const el = document.getElementById(`class-criteria-${lv}`);
      if (el) el.value = (c.evaluation_criteria && c.evaluation_criteria[lv]) || "";
    });
    if (archiveBtn) archiveBtn.disabled = false;
    if (resetLessonBtn) resetLessonBtn.disabled = false;
    const saveBtn = document.getElementById("save-lesson-btn");
    if (saveBtn) saveBtn.disabled = false;
    renderArchiveList(cls);
  }

  function formatTime(sec) {
    const s = Math.max(0, parseInt(sec, 10) || 0);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  }

  function parseTimerValue(el, fallback) {
    if (!el || el.value.trim() === "") return fallback;
    const value = parseInt(el.value, 10);
    return Number.isFinite(value) ? Math.max(0, value) : fallback;
  }

  function renderArchiveList(cls) {
    if (!archiveList || !archiveSummary || !archiveEmptyMessage) return;
    const archive = cls && Array.isArray(cls.archive) ? cls.archive : [];
    const currentClassId = cls ? cls.id : getSelectedClassId();

    archiveSummary.textContent = `アーカイブ（${archive.length} 件）`;
    archiveList.innerHTML = "";
    archiveEmptyMessage.classList.toggle("hidden", archive.length > 0);

    archive.forEach((item, index) => {
      const li = document.createElement("li");
      li.className = "rounded border border-teal-100/80 bg-white/50 px-1.5 py-1";
      li.dataset.archiveIndex = String(index);

      const row = document.createElement("div");
      row.className = "flex min-w-0 items-center gap-1.5";

      const textWrap = document.createElement("div");
      textWrap.className = "min-w-0 flex-1";

      const title = document.createElement("p");
      title.className = "truncate font-semibold leading-tight text-slate-700";
      title.textContent = item.title || item.video_id || "無題のアーカイブ";

      const meta = document.createElement("p");
      meta.className = "truncate leading-tight";
      const archivedAt = item.archived_at ? String(item.archived_at).slice(0, 10) : "—";
      const scriptLength = (item.script || "").length;
      meta.textContent = `${archivedAt} · ${item.video_id || "—"} · ${item.start_seconds || 0}s–${item.end_seconds || 0}s · ${scriptLength}字`;

      textWrap.append(title, meta);
      row.appendChild(textWrap);

      const actions = document.createElement("div");
      actions.className = "flex shrink-0 items-center gap-1";

      const restoreBtn = document.createElement("button");
      restoreBtn.type = "button";
      restoreBtn.className = "restore-archive-btn rounded border border-sky-100 bg-white/80 px-1.5 py-0.5 text-[9px] font-semibold leading-none text-sky-700 hover:bg-sky-50";
      restoreBtn.textContent = "戻す";

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "delete-archive-btn rounded border border-red-100 bg-white/80 px-1.5 py-0.5 text-[9px] font-semibold leading-none text-red-600 hover:bg-red-50";
      deleteBtn.textContent = "削除";

      actions.append(restoreBtn, deleteBtn);

      const copyTargets = adminClasses.filter((c) => c.id !== currentClassId);
      if (copyTargets.length) {
        const targetSelect = document.createElement("select");
        targetSelect.className = "archive-copy-target rounded border border-teal-100 bg-white/80 px-1 py-0.5 text-[9px] text-slate-700";
        copyTargets.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.id;
          opt.textContent = c.name;
          targetSelect.appendChild(opt);
        });

        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "copy-archive-btn rounded border border-emerald-100 bg-white/80 px-1.5 py-0.5 text-[9px] font-semibold leading-none text-emerald-700 hover:bg-emerald-50";
        copyBtn.textContent = "コピー";
        actions.append(targetSelect, copyBtn);
      }

      row.appendChild(actions);
      li.appendChild(row);
      archiveList.appendChild(li);
    });
  }

  async function refreshClassList(selectId) {
    const res = await fetch("/admin/api/classes");
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "クラス一覧の取得に失敗しました");
    adminClasses = data.classes || [];

    if (classSelect) {
      const prev = classSelect.value;
      classSelect.innerHTML = "";
      if (!data.classes.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "（クラス未作成）";
        classSelect.appendChild(opt);
      } else {
        data.classes.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.id;
          opt.textContent = c.name;
          classSelect.appendChild(opt);
        });
      }
      const target = selectId || data.active_class_id || prev;
      if (target) classSelect.value = target;
    }
    return data;
  }

  async function selectClass(classId) {
    const res = await fetch("/admin/api/classes/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ class_id: classId }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "クラスの切り替えに失敗しました");
    fillLessonForm(data.class);
    return data;
  }

  if (classSelect) {
    classSelect.addEventListener("change", async () => {
      const id = getSelectedClassId();
      if (!id) return;
      try {
        await selectClass(id);
        showMessage(classMessage, "クラスを切り替えました。", false);
      } catch (err) {
        showMessage(classMessage, err.message, true);
      }
    });
  }

  if (createClassBtn) {
    createClassBtn.addEventListener("click", async () => {
      const name = newClassName ? newClassName.value.trim() : "";
      if (!name) {
        showMessage(classMessage, "クラス名を入力してください。", true);
        return;
      }
      createClassBtn.disabled = true;
      try {
        const res = await fetch("/admin/api/classes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "作成に失敗しました");
        await refreshClassList(data.class.id);
        fillLessonForm(data.class);
        if (newClassName) newClassName.value = "";
        showMessage(classMessage, `「${data.class.name}」を作成しました。`, false);
      } catch (err) {
        showMessage(classMessage, err.message, true);
      } finally {
        createClassBtn.disabled = false;
      }
    });
  }

  if (reloadClassBtn) {
    reloadClassBtn.addEventListener("click", () => location.reload());
  }

  function unlockAdminSettings() {
    const password = adminSettingsPassword ? adminSettingsPassword.value.trim() : "";
    if (password !== "2479") {
      if (adminSettingsLockMessage) {
        adminSettingsLockMessage.textContent = "パスワードが違います。";
        adminSettingsLockMessage.classList.remove("hidden");
      }
      return;
    }

    adminSettingsPasswordValue = password;
    if (settingsForm) settingsForm.classList.remove("hidden");
    if (adminSettingsLock) adminSettingsLock.classList.add("hidden");
    if (adminSettingsLockMessage) adminSettingsLockMessage.classList.add("hidden");
  }

  if (adminSettingsUnlock) {
    adminSettingsUnlock.addEventListener("click", unlockAdminSettings);
  }

  if (adminSettingsPassword) {
    adminSettingsPassword.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        unlockAdminSettings();
      }
    });
  }

  if (lessonForm) {
    lessonForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const classId = getSelectedClassId() || (lessonClassId && lessonClassId.value);
      if (!classId) {
        showMessage(lessonMessage, "クラスを選択または作成してください。", true);
        return;
      }

      const btn = document.getElementById("save-lesson-btn");
      btn.disabled = true;
      btn.textContent = "保存中…";
      lessonMessage.classList.add("hidden");

      const payload = {
        class_id: classId,
        url: document.getElementById("youtube-url").value.trim(),
        start_time: document.getElementById("start-time").value.trim(),
        end_time: document.getElementById("end-time").value.trim(),
        script: document.getElementById("lesson-script").value.trim(),
        evaluation_criteria: collectClassCriteria(),
        prep_timer_seconds: parseTimerValue(document.getElementById("prep-timer-seconds"), 0),
        record_timer_seconds: parseTimerValue(document.getElementById("record-timer-seconds"), 60),
        timers_visible: document.getElementById("timers-visible").checked,
        subtitles_enabled: document.getElementById("subtitles-enabled").checked,
      };

      try {
        const res = await fetch("/admin/api/class/lesson", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "保存に失敗しました");
        showMessage(lessonMessage, data.message || "保存しました。", false);
        if (data.class) fillLessonForm(data.class);
      } catch (err) {
        showMessage(lessonMessage, err.message, true);
      } finally {
        btn.disabled = false;
        btn.textContent = "授業設定を保存";
      }
    });
  }

  if (archiveBtn) {
    archiveBtn.addEventListener("click", async () => {
      const classId = getSelectedClassId();
      if (!classId) return;
      if (!confirm("現在の授業をアーカイブし、入力欄を空にします。よろしいですか？")) return;

      archiveBtn.disabled = true;
      try {
        const res = await fetch("/admin/api/class/archive", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ class_id: classId, title: archiveTitle ? archiveTitle.value.trim() : "" }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "アーカイブに失敗しました");
        showMessage(lessonMessage, data.message || "アーカイブしました。", false);
        setTimeout(() => location.reload(), 700);
      } catch (err) {
        showMessage(lessonMessage, err.message, true);
        archiveBtn.disabled = false;
      }
    });
  }

  if (resetLessonBtn) {
    resetLessonBtn.addEventListener("click", async () => {
      const classId = getSelectedClassId();
      if (!classId) return;
      if (!confirm("現在開いているリンク、時間、スクリプト、評価基準、タイマー設定を消去します。よろしいですか？")) {
        return;
      }

      resetLessonBtn.disabled = true;
      try {
        const res = await fetch("/admin/api/class/lesson/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ class_id: classId }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "リセットに失敗しました");
        if (data.class) fillLessonForm(data.class);
        if (archiveTitle) archiveTitle.value = "";
        showMessage(lessonMessage, data.message || "現在の授業設定をリセットしました。", false);
      } catch (err) {
        showMessage(lessonMessage, err.message, true);
      } finally {
        resetLessonBtn.disabled = false;
      }
    });
  }

  if (archiveList) {
    archiveList.addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      const itemEl = btn.closest("li");
      const classId = getSelectedClassId();
      const archiveIndex = parseInt(itemEl && itemEl.dataset.archiveIndex, 10);
      if (!classId || !Number.isFinite(archiveIndex)) return;

      btn.disabled = true;
      try {
        if (btn.classList.contains("restore-archive-btn")) {
          if (!confirm("現在設定されている動画やスクリプトなどは上書きされます。アーカイブの内容を設定画面に戻しますか？")) {
            return;
          }
          const res = await fetch("/admin/api/class/archive/restore", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ class_id: classId, archive_index: archiveIndex }),
          });
          const data = await res.json();
          if (!data.ok) throw new Error(data.error || "復元に失敗しました");
          if (data.class) fillLessonForm(data.class);
          showMessage(lessonMessage, data.message || "アーカイブを設定画面に戻しました。", false);
          return;
        }

        if (btn.classList.contains("delete-archive-btn")) {
          if (!confirm("このアーカイブを削除します。元に戻せません。よろしいですか？")) {
            return;
          }
          const res = await fetch("/admin/api/class/archive/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ class_id: classId, archive_index: archiveIndex }),
          });
          const data = await res.json();
          if (!data.ok) throw new Error(data.error || "削除に失敗しました");
          if (data.class) renderArchiveList(data.class);
          showMessage(lessonMessage, data.message || "アーカイブを削除しました。", false);
          return;
        }

        if (btn.classList.contains("copy-archive-btn")) {
          const targetSelect = itemEl.querySelector(".archive-copy-target");
          const targetClassId = targetSelect ? targetSelect.value : "";
          const targetName = targetSelect && targetSelect.selectedOptions[0] ? targetSelect.selectedOptions[0].textContent : "コピー先";
          if (!targetClassId) return;
          if (!confirm(`このアーカイブを「${targetName}」へコピーしますか？`)) {
            return;
          }
          const res = await fetch("/admin/api/class/archive/copy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ class_id: classId, archive_index: archiveIndex, target_class_id: targetClassId }),
          });
          const data = await res.json();
          if (!data.ok) throw new Error(data.error || "コピーに失敗しました");
          showMessage(lessonMessage, data.message || "アーカイブをコピーしました。", false);
        }
      } catch (err) {
        showMessage(lessonMessage, err.message, true);
      } finally {
        btn.disabled = false;
      }
    });
  }

  if (settingsForm) {
    settingsForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = {
        display_language: document.getElementById("display-language").value,
        ai_model: document.getElementById("ai-model").value,
        openai_api_key: document.getElementById("openai-api-key").value.trim(),
        default_evaluation_criteria: collectDefaultCriteria(),
        admin_password: adminSettingsPasswordValue,
      };
      try {
        const res = await fetch("/admin/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "保存に失敗しました");
        showMessage(settingsMessage, "管理設定を保存しました。", false);
        document.getElementById("openai-api-key").value = "";
      } catch (err) {
        showMessage(settingsMessage, err.message, true);
      }
    });
  }

  function copyTextFromInput(inputEl, buttonEl, emptyMessage) {
    const text = inputEl ? inputEl.value.trim() : "";
    if (!text) {
      alert(emptyMessage || "コピーする内容がありません。");
      return;
    }
    const copy = async () => {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else if (inputEl) {
        inputEl.select();
        document.execCommand("copy");
        inputEl.blur();
      }
    };
    copy()
      .then(() => {
        if (!buttonEl) return;
        const prev = buttonEl.textContent;
        buttonEl.textContent = "済";
        setTimeout(() => {
          buttonEl.textContent = prev;
        }, 1200);
      })
      .catch(() => {
        alert("コピーできませんでした。リンク欄を選択してコピーしてください。");
      });
  }

  if (generateLinkBtn) {
    generateLinkBtn.addEventListener("click", async () => {
      const classId = getSelectedClassId();
      if (!classId) {
        alert("クラスを選択してください。");
        return;
      }
      const level = document.getElementById("share-level").value;
      try {
        const res = await fetch(
          `/admin/api/share-link?level=${encodeURIComponent(level)}&class_id=${encodeURIComponent(classId)}`
        );
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "リンク生成に失敗しました");
        shareLinkOutput.value = data.link;
      } catch (err) {
        shareLinkOutput.value = "";
        alert(err.message);
      }
    });
  }

  if (copyShareLinkBtn) {
    copyShareLinkBtn.addEventListener("click", () => {
      copyTextFromInput(shareLinkOutput, copyShareLinkBtn, "先に共有リンクを生成してください。");
    });
  }

  if (cnn10OpenBtn) {
    cnn10OpenBtn.addEventListener("click", () => {
      showCnn10Panel();
      loadCnn10Episodes(true);
    });
  }

  if (cnn10MoreBtn) {
    cnn10MoreBtn.addEventListener("click", loadMoreCnn10Episodes);
  }

  if (cnn10CloseBtn) {
    cnn10CloseBtn.addEventListener("click", hideCnn10Panel);
  }

  if (cnn10Panel) {
    cnn10Panel.addEventListener("click", (e) => {
      if (e.target === cnn10Panel) hideCnn10Panel();
    });
  }

  ["start-time", "end-time", "youtube-url"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", scheduleAutoScriptFill);
    el.addEventListener("change", scheduleAutoScriptFill);
  });

  const lessonScriptEl = document.getElementById("lesson-script");
  if (lessonScriptEl) {
    lessonScriptEl.addEventListener("input", () => {
      scriptAutoManaged = false;
    });
  }

  function esc(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function scoreOnlyFeedback(feedback) {
    const text = String(feedback || "").trim();
    const start = text.indexOf("項目別評価点");
    if (start < 0) return text;
    const rest = text.slice(start);
    const nextHeading = rest.search(/\n\s*(要点チェックとキーワードチェック|文法・構成アドバイス|【AIからの模範要約】|今回の要約スピーチへのアドバイス|今回の要約スピーチ文の改良例)/);
    return (nextHeading >= 0 ? rest.slice(0, nextHeading) : rest).trim();
  }

  async function loadLessonFilterOptions() {
    if (!resultsLessonFilter) return;
    const classId = resultsClassFilter ? resultsClassFilter.value : "";
    resultsLessonFilter.innerHTML = "";
    if (!classId) {
      resultsLessonFilter.disabled = true;
      resultsLessonFilter.innerHTML = '<option value="">先にクラスを選択</option>';
      return;
    }
    resultsLessonFilter.disabled = false;
    resultsLessonFilter.innerHTML = '<option value="">すべての動画</option>';
    try {
      const res = await fetch(`/admin/api/class/lessons?class_id=${encodeURIComponent(classId)}`);
      const data = await res.json();
      (data.lessons || []).forEach((lesson) => {
        const opt = document.createElement("option");
        opt.value = lesson.key || "";
        opt.textContent = lesson.title || "未分類";
        resultsLessonFilter.appendChild(opt);
      });
    } catch (err) {
      console.error("動画タイトルの取得に失敗:", err);
    }
  }

  async function loadResults() {
    if (!resultsTbody || !resultsTable || !resultsEmpty) return;
    const classId = resultsClassFilter ? resultsClassFilter.value : "";
    const lessonKey = resultsLessonFilter && !resultsLessonFilter.disabled ? resultsLessonFilter.value : "";
    const params = new URLSearchParams();
    if (classId) params.set("class_id", classId);
    if (lessonKey) params.set("lesson_key", lessonKey);
    const url = params.toString() ? `/admin/api/submissions?${params.toString()}` : "/admin/api/submissions";
    try {
      const res = await fetch(url);
      const data = await res.json();
      latestSubmissions = data.submissions || [];
      renderResults(latestSubmissions);
    } catch (err) {
      console.error("結果の取得に失敗:", err);
    }
  }

  function renderResults(submissions) {
    submissions = sortSubmissions(submissions);
    allResultsSelected = false;
    resultsTbody.innerHTML = "";
    updateBulkDeleteState();
    if (!submissions.length) {
      resultsTable.classList.add("hidden");
      resultsEmpty.classList.remove("hidden");
      return;
    }
    resultsTable.classList.remove("hidden");
    resultsEmpty.classList.add("hidden");

    submissions.forEach((submission) => {
      const tr = document.createElement("tr");
      const dt = submission.submitted_at ? new Date(submission.submitted_at).toLocaleString("ja-JP") : "";
      tr.innerHTML = `
        <td class="py-1 pr-2 text-center">
          <input type="checkbox" class="submission-select h-3.5 w-3.5 rounded border-teal-200 text-teal-600" data-id="${esc(submission.id)}">
        </td>
        <td class="py-1 pr-2 whitespace-nowrap text-slate-500">${esc(dt)}</td>
        <td class="py-1 pr-2">${esc(submission.class_name)}</td>
        <td class="py-1 pr-2">${esc(submission.student_hr_class)}</td>
        <td class="py-1 pr-2">${esc(submission.student_number)}</td>
        <td class="py-1 pr-2 font-medium">${esc(submission.student_name)}</td>
        <td class="py-1 pr-2">${esc(submission.lesson_title || "未分類")}</td>
        <td class="py-1 pr-2 text-center font-semibold text-slate-700">${esc(submission.content_score)}</td>
        <td class="py-1 pr-2 text-center font-semibold text-slate-700">${esc(submission.organization_score)}</td>
        <td class="py-1 pr-2 text-center font-semibold text-slate-700">${esc(submission.language_score)}</td>
        <td class="py-1 pr-2 text-center font-semibold text-slate-700">${esc(submission.speaking_summary_score)}</td>
        <td class="py-1 pr-2 text-center font-bold text-teal-700">${esc(submission.total_score)}</td>
        <td class="py-1 pr-2">${esc(submission.level)}</td>
        <td class="py-1 pr-2 align-top">
          <div class="max-h-32 overflow-y-auto whitespace-pre-wrap rounded bg-white/45 p-1">${esc(submission.transcript)}</div>
        </td>
        <td class="py-1 pr-2 align-top text-slate-600">
          <div class="max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-white/45 p-1">${esc(scoreOnlyFeedback(submission.feedback))}</div>
        </td>
        <td class="py-1">
          <button type="button" data-id="${esc(submission.id)}"
            class="del-submission-btn text-[10px] text-red-400 hover:text-red-600">削除</button>
        </td>`;
      resultsTbody.appendChild(tr);
    });
    updateBulkDeleteState();
  }

  function getSubmissionCheckboxes() {
    return resultsTbody ? Array.from(resultsTbody.querySelectorAll(".submission-select")) : [];
  }

  function updateBulkDeleteState() {
    const boxes = getSubmissionCheckboxes();
    const selectedCount = boxes.filter((box) => box.checked).length;
    if (resultsSelectAllBtn) {
      resultsSelectAllBtn.disabled = boxes.length === 0;
      allResultsSelected = boxes.length > 0 && selectedCount === boxes.length;
      resultsSelectAllBtn.textContent = allResultsSelected ? "選択解除" : "全て選択";
    }
    if (resultsDeleteSelectedBtn) {
      resultsDeleteSelectedBtn.disabled = selectedCount === 0;
      resultsDeleteSelectedBtn.textContent = selectedCount ? `選択削除（${selectedCount}件）` : "選択削除";
    }
  }

  function normalizeNumber(value) {
    const number = parseInt(String(value || "").replace(/[^\d]/g, ""), 10);
    return Number.isFinite(number) ? number : 999999;
  }

  function sortSubmissions(submissions) {
    const key = resultsSortKey ? resultsSortKey.value : "submitted_at";
    const direction = resultsSortDirection ? resultsSortDirection.dataset.direction || "desc" : "desc";
    const multiplier = direction === "asc" ? 1 : -1;
    return [...submissions].sort((a, b) => {
      if (key === "student_number") {
        return (normalizeNumber(a.student_number) - normalizeNumber(b.student_number)) * multiplier;
      }
      const aValue = String(a[key] || "");
      const bValue = String(b[key] || "");
      return aValue.localeCompare(bValue, "ja", { numeric: true }) * multiplier;
    });
  }

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach((b) => {
        const active = b === btn;
        b.classList.toggle("bg-white/70", active);
        b.classList.toggle("border", active);
        b.classList.toggle("border-teal-100", active);
        b.classList.toggle("border-b-0", active);
        b.classList.toggle("-mb-px", active);
        b.classList.toggle("text-teal-700", active);
        b.classList.toggle("text-slate-500", !active);
      });
      if (tabLesson) tabLesson.classList.toggle("hidden", tab !== "lesson");
      if (tabResults) tabResults.classList.toggle("hidden", tab !== "results");
      if (tab === "results") loadResults();
    });
  });

  if (resultsLoadBtn) {
    resultsLoadBtn.addEventListener("click", loadResults);
  }

  if (resultsClassFilter) {
    resultsClassFilter.addEventListener("change", async () => {
      await loadLessonFilterOptions();
      loadResults();
    });
  }

  if (resultsLessonFilter) {
    resultsLessonFilter.addEventListener("change", loadResults);
  }

  if (resultsSortKey) {
    resultsSortKey.addEventListener("change", () => renderResults(latestSubmissions));
  }

  if (resultsSortDirection) {
    resultsSortDirection.addEventListener("click", () => {
      const next = resultsSortDirection.dataset.direction === "asc" ? "desc" : "asc";
      resultsSortDirection.dataset.direction = next;
      resultsSortDirection.textContent = next === "asc" ? "昇順" : "降順";
      renderResults(latestSubmissions);
    });
  }

  if (resultsSelectAllBtn) {
    resultsSelectAllBtn.addEventListener("click", () => {
      const boxes = getSubmissionCheckboxes();
      const nextChecked = !allResultsSelected;
      boxes.forEach((box) => {
        box.checked = nextChecked;
      });
      updateBulkDeleteState();
    });
  }

  if (resultsDeleteSelectedBtn) {
    resultsDeleteSelectedBtn.addEventListener("click", async () => {
      const ids = getSubmissionCheckboxes()
        .filter((box) => box.checked)
        .map((box) => box.dataset.id)
        .filter(Boolean);
      if (!ids.length) return;
      if (!confirm(`選択した${ids.length}件の提出データを削除しますか？`)) return;
      resultsDeleteSelectedBtn.disabled = true;
      try {
        await Promise.all(
          ids.map((id) => fetch(`/admin/api/submissions/${encodeURIComponent(id)}`, { method: "DELETE" }))
        );
        loadResults();
      } catch (err) {
        alert("削除に失敗しました。もう一度試してください。");
        updateBulkDeleteState();
      }
    });
  }

  if (resultsTbody) {
    resultsTbody.addEventListener("click", async (e) => {
      if (e.target.closest(".submission-select")) {
        updateBulkDeleteState();
        return;
      }
      const btn = e.target.closest(".del-submission-btn");
      if (!btn) return;
      if (!confirm("この提出データを削除しますか？")) return;
      await fetch(`/admin/api/submissions/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE" });
      loadResults();
    });
  }

  if (resultsExportBtn) {
    resultsExportBtn.addEventListener("click", () => {
      const classId = resultsClassFilter ? resultsClassFilter.value : "";
      const lessonKey = resultsLessonFilter && !resultsLessonFilter.disabled ? resultsLessonFilter.value : "";
      const params = new URLSearchParams();
      if (classId) params.set("class_id", classId);
      if (lessonKey) params.set("lesson_key", lessonKey);
      window.location.href = params.toString()
        ? `/admin/api/submissions/export?${params.toString()}`
        : "/admin/api/submissions/export";
    });
  }

  if (rosterUploadBtn) {
    rosterUploadBtn.addEventListener("click", async () => {
      const classId = classSelect ? classSelect.value : "";
      if (!classId) {
        showMessage(rosterMessage, "先にクラスを選択してください。", true);
        return;
      }
      if (!rosterFileInput || !rosterFileInput.files.length) {
        showMessage(rosterMessage, "ファイルを選択してください。", true);
        return;
      }

      const form = new FormData();
      form.append("class_id", classId);
      form.append("file", rosterFileInput.files[0]);

      try {
        const res = await fetch("/admin/api/roster/upload", { method: "POST", body: form });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "アップロードに失敗しました。");
        showMessage(rosterMessage, `✓ ${data.count} 件の名簿を登録しました。`, false);
      } catch (err) {
        showMessage(rosterMessage, err.message, true);
      }
    });
  }

  if (window.ADMIN_ACTIVE_CLASS) {
    fillLessonForm(window.ADMIN_ACTIVE_CLASS);
  }
})();
