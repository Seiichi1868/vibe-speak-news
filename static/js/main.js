(function () {
  const STORAGE_KEY = "vibe_speak_selected_class_id";
  const STORAGE_STUDENT_KEY = "vibe_speak_student_info";

  const openingOverlay = document.getElementById("opening-overlay");
  const classPickerOverlay = document.getElementById("class-picker-overlay");
  const classPickerSelect = document.getElementById("class-picker-select");
  const classPickerStart = document.getElementById("class-picker-start");
  const classPickerError = document.getElementById("class-picker-error");
  const studentInfoOverlay = document.getElementById("student-info-overlay");
  const rosterSelectWrap = document.getElementById("roster-select-wrap");
  const rosterSelect = document.getElementById("roster-select");
  const lessonClassDisplay = document.getElementById("lesson-class-display");
  const studentClassInput = document.getElementById("student-class-name");
  const studentNumberInput = document.getElementById("student-number");
  const studentNameInput = document.getElementById("student-name");
  const studentInfoStart = document.getElementById("student-info-start");
  const studentInfoError = document.getElementById("student-info-error");
  const appMain = document.getElementById("app-main");
  const changeClassBtn = document.getElementById("change-class-btn");
  const activeClassNameEl = document.getElementById("active-class-name");
  const studentDisplayName = document.getElementById("student-display-name");

  const prepTimerEl = document.getElementById("prep-timer");
  const recordTimerEl = document.getElementById("record-timer");
  const prepTimerWrap = document.getElementById("prep-timer-wrap");
  const recordTimerWrap = document.getElementById("record-timer-wrap");
  const timersRow = document.getElementById("timers-row");
  const prepStartBtn = document.getElementById("prep-start-btn");
  const recordBtn = document.getElementById("record-btn");
  const recordStatus = document.getElementById("record-status");
  const transcriptArea = document.getElementById("transcript-area");
  const submitBtn = document.getElementById("submit-btn");
  const submitMessage = document.getElementById("submit-message");
  const feedbackArea = document.getElementById("feedback-area");
  const levelSelect = document.getElementById("level-select");
  const levelDisplay = document.getElementById("level-display");
  const youtubePlayer = document.getElementById("youtube-player");
  const videoPlaceholder = document.getElementById("video-placeholder");

  let selectedClassId = "";
  let prepSeconds = 60;
  let recordSeconds = 60;
  let prepRemaining = 60;
  let recordRemaining = 60;
  let prepInterval = null;
  let recordInterval = null;
  let recognition = null;
  let isRecording = false;
  let hasRecordingEnded = false;
  let finalTranscript = "";
  let pendingClassId = "";
  let pendingLessonClassName = "";
  let studentHrClass = "";
  let studentNumber = "";
  let studentName = "";
  let youtubeApiPlayer = null;
  let youtubeApiReadyPromise = null;
  let activePlayerSubtitles = null;
  let videoStartSeconds = 0;
  let videoEndSeconds = 0;
  let videoRangeGuardInterval = null;

  function formatTime(sec) {
    const s = Math.max(0, parseInt(sec, 10) || 0);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  }

  function updateSubmitState() {
    submitBtn.disabled = !transcriptArea.value.trim() || !selectedClassId;
  }

  function syncTranscriptFromInput() {
    finalTranscript = transcriptArea.value;
    updateSubmitState();
  }

  function escHtml(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderFeedback(text) {
    const html = escHtml(text)
      .split("\n")
      .map((line) => {
        if (line === "項目別評価点") {
          return '<div class="mt-3 mb-1 font-bold text-teal-700">項目別評価点</div>';
        }
        const total = line.match(/^合計:\s*(\d+\/\d+)/);
        if (total) {
          return `<div class="my-1 rounded-md bg-teal-50 px-2 py-1 font-bold text-teal-800">合計: ${total[1]}</div>`;
        }
        const score = line.match(/^- ([^:]+):\s*(\d+\/\d+)(.*)$/);
        if (score) {
          return `<div class="my-1 rounded-md bg-white/70 px-2 py-1"><span class="font-bold text-slate-800">${score[1]}</span>: <span class="font-bold text-teal-700">${score[2]}</span>${score[3]}</div>`;
        }
        return line ? `<div>${line}</div>` : '<div class="h-2"></div>';
      })
      .join("");
    feedbackArea.innerHTML = html;
  }

  function updatePrepDisplay() {
    prepTimerEl.textContent = formatTime(prepRemaining);
  }

  function updateRecordDisplay() {
    recordTimerEl.textContent = formatTime(recordRemaining);
  }

  function applyTimerSettings(timers) {
    prepSeconds = Math.max(0, parseInt(timers.prep_seconds, 10) || 0);
    recordSeconds = Math.max(0, parseInt(timers.record_seconds, 10) || 60);
    prepRemaining = prepSeconds;
    recordRemaining = recordSeconds;
    updatePrepDisplay();
    updateRecordDisplay();
    if (prepStartBtn) prepStartBtn.textContent = prepSeconds > 0 ? "開始" : "準備なし";

    const visible = timers.visible !== false;
    const showPrepTimer = visible && prepSeconds > 0;
    if (prepTimerWrap) prepTimerWrap.classList.toggle("hidden", !showPrepTimer);
    if (recordTimerWrap) recordTimerWrap.classList.toggle("hidden", !visible);
    if (prepStartBtn) prepStartBtn.classList.toggle("hidden", !showPrepTimer);
    if (timersRow) {
      timersRow.classList.toggle("sm:grid-cols-4", visible);
      timersRow.classList.toggle("sm:grid-cols-2", !visible);
    }
  }

  function buildPlayerVars(start, end, subtitlesEnabled) {
    const vars = {
      start: Math.max(0, start || 0),
      playsinline: 1,
      rel: 0,
      modestbranding: 1,
      enablejsapi: 1,
      fs: 1,
      iv_load_policy: 3,
      origin: window.location.origin,
      widget_referrer: window.location.origin,
    };
    if (end && end > start) vars.end = end;
    if (subtitlesEnabled) {
      vars.cc_load_policy = 1;
      vars.cc_lang_pref = "en";
    }
    return vars;
  }

  function buildEmbedUrl(videoId, start, end, subtitlesEnabled) {
    const params = new URLSearchParams();
    Object.entries(buildPlayerVars(start, end, subtitlesEnabled)).forEach(([key, value]) => {
      params.set(key, String(value));
    });
    return `https://www.youtube.com/embed/${videoId}?${params.toString()}`;
  }

  function destroyYouTubePlayer() {
    if (youtubeApiPlayer && typeof youtubeApiPlayer.destroy === "function") {
      try {
        youtubeApiPlayer.destroy();
      } catch (_) {
        /* ignore */
      }
    }
    youtubeApiPlayer = null;
    activePlayerSubtitles = null;
    if (youtubePlayer) {
      youtubePlayer.innerHTML = "";
      youtubePlayer.classList.add("hidden");
    }
  }

  function loadYouTubeApi() {
    if (window.YT && window.YT.Player) return Promise.resolve();
    if (youtubeApiReadyPromise) return youtubeApiReadyPromise;

    youtubeApiReadyPromise = new Promise((resolve) => {
      const previousReady = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        if (typeof previousReady === "function") previousReady();
        resolve();
      };
      if (!document.querySelector('script[src="https://www.youtube.com/iframe_api"]')) {
        const script = document.createElement("script");
        script.src = "https://www.youtube.com/iframe_api";
        document.head.appendChild(script);
      }
    });
    return youtubeApiReadyPromise;
  }

  function stopVideoRangeGuard() {
    clearInterval(videoRangeGuardInterval);
    videoRangeGuardInterval = null;
  }

  function mountPlainEmbed(embedUrl) {
    if (!youtubePlayer) return;
    destroyYouTubePlayer();
    const iframe = document.createElement("iframe");
    iframe.className = "absolute inset-0 h-full w-full border-0";
    iframe.title = "News video player";
    iframe.src = embedUrl;
    iframe.allow =
      "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    iframe.allowFullscreen = true;
    iframe.setAttribute("playsinline", "");
    youtubePlayer.appendChild(iframe);
    youtubePlayer.classList.remove("hidden");
  }

  function applySubtitles(player, enabled) {
    if (!player || !enabled) return;
    try {
      if (typeof player.loadModule === "function") {
        player.loadModule("captions");
      }
      if (typeof player.setOption === "function") {
        player.setOption("captions", "track", { languageCode: "en" });
      }
    } catch (_) {
      /* ignore */
    }
  }

  async function mountYouTubePlayer(videoId, start, end, subtitlesEnabled) {
    if (!youtubePlayer || !videoId) return;

    await loadYouTubeApi();
    const playerVars = buildPlayerVars(start, end, subtitlesEnabled);

    if (youtubeApiPlayer && activePlayerSubtitles !== subtitlesEnabled) {
      destroyYouTubePlayer();
    }

    if (youtubeApiPlayer && typeof youtubeApiPlayer.loadVideoById === "function") {
      youtubeApiPlayer.loadVideoById({
        videoId,
        startSeconds: Math.max(0, start || 0),
      });
      applySubtitles(youtubeApiPlayer, subtitlesEnabled);
      activePlayerSubtitles = subtitlesEnabled;
      youtubePlayer.classList.remove("hidden");
      return;
    }

    destroyYouTubePlayer();
    youtubePlayer.classList.remove("hidden");

    await new Promise((resolve, reject) => {
      let settled = false;
      const timeout = window.setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error("YouTube player timeout"));
      }, 8000);

      youtubeApiPlayer = new window.YT.Player(youtubePlayer, {
        videoId,
        width: "100%",
        height: "100%",
        playerVars,
        events: {
          onReady: () => {
            if (settled) return;
            settled = true;
            clearTimeout(timeout);
            applySubtitles(youtubeApiPlayer, subtitlesEnabled);
            activePlayerSubtitles = subtitlesEnabled;
            enforceVideoRange();
            startVideoRangeGuard();
            resolve();
          },
          onStateChange: enforceVideoRange,
          onError: () => {
            if (settled) return;
            settled = true;
            clearTimeout(timeout);
            reject(new Error("YouTube player error"));
          },
        },
      });
    });
  }

  function enforceVideoRange() {
    if (!youtubeApiPlayer || typeof youtubeApiPlayer.getCurrentTime !== "function") return;
    const current = youtubeApiPlayer.getCurrentTime();
    if (!Number.isFinite(current)) return;
    if (current < videoStartSeconds - 0.5) {
      youtubeApiPlayer.seekTo(videoStartSeconds, true);
      return;
    }
    if (videoEndSeconds > videoStartSeconds && current > videoEndSeconds + 0.5) {
      youtubeApiPlayer.seekTo(videoStartSeconds, true);
      if (typeof youtubeApiPlayer.pauseVideo === "function") {
        youtubeApiPlayer.pauseVideo();
      }
    }
  }

  function startVideoRangeGuard() {
    clearInterval(videoRangeGuardInterval);
    videoRangeGuardInterval = setInterval(enforceVideoRange, 500);
  }

  async function setVideoPlayer(video) {
    stopVideoRangeGuard();
    if (!video || !video.video_id) {
      destroyYouTubePlayer();
      if (videoPlaceholder) {
        videoPlaceholder.classList.remove("hidden");
        videoPlaceholder.textContent = "このクラスには動画が未設定です。管理画面で URL を登録してください。";
      }
      return;
    }

    videoStartSeconds = Math.max(0, parseInt(video.start_seconds, 10) || 0);
    videoEndSeconds = Math.max(0, parseInt(video.end_seconds, 10) || 0);
    if (videoPlaceholder) videoPlaceholder.classList.add("hidden");

    const embedUrl = buildEmbedUrl(
      video.video_id,
      videoStartSeconds,
      videoEndSeconds,
      video.subtitles_enabled
    );

    try {
      await mountYouTubePlayer(
        video.video_id,
        videoStartSeconds,
        videoEndSeconds,
        video.subtitles_enabled
      );
    } catch (_) {
      mountPlainEmbed(embedUrl);
    }
  }

  function showClassPicker() {
    classPickerOverlay.classList.remove("hidden");
    classPickerOverlay.classList.add("flex");
    appMain.classList.add("hidden");
  }

  function hideClassPicker() {
    classPickerOverlay.classList.add("hidden");
    classPickerOverlay.classList.remove("flex");
    appMain.classList.remove("hidden");
  }

  function showPickerError(msg) {
    classPickerError.textContent = msg;
    classPickerError.classList.remove("hidden");
  }

  function clearPickerError() {
    classPickerError.classList.add("hidden");
  }

  function showStudentInfoOverlay() {
    if (!studentInfoOverlay) return;
    studentInfoOverlay.classList.remove("hidden");
    studentInfoOverlay.classList.add("flex");
    appMain.classList.add("hidden");
  }

  function hideStudentInfoOverlay() {
    if (!studentInfoOverlay) return;
    studentInfoOverlay.classList.add("hidden");
    studentInfoOverlay.classList.remove("flex");
  }

  function getStudentInfoStore() {
    try {
      const raw = sessionStorage.getItem(STORAGE_STUDENT_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (_) {
      return {};
    }
  }

  function getSavedStudentInfo(classId) {
    const entry = getStudentInfoStore()[classId];
    if (!entry || (!entry.number && !entry.name)) return null;
    return entry;
  }

  function saveStudentInfo(classId, info) {
    const store = getStudentInfoStore();
    store[classId] = {
      hr_class: info.hrClass || "",
      number: info.number || "",
      name: info.name || "",
    };
    sessionStorage.setItem(STORAGE_STUDENT_KEY, JSON.stringify(store));
  }

  function applySavedStudentInfo(info) {
    studentHrClass = info.hr_class || "";
    studentNumber = info.number || "";
    studentName = info.name || "";
    if (studentDisplayName) {
      studentDisplayName.textContent = `${studentHrClass}　${studentNumber}　${studentName}`.trim();
    }
  }

  async function prepareStudentInfo(classId) {
    pendingClassId = classId;
    pendingLessonClassName = "";

    const saved = getSavedStudentInfo(classId);
    if (saved) {
      applySavedStudentInfo(saved);
      try {
        await loadClassSession(classId);
        hideStudentInfoOverlay();
        return;
      } catch (_) {
        /* fall through to registration form */
      }
    }

    studentHrClass = saved ? saved.hr_class || "" : "";
    if (studentInfoError) studentInfoError.classList.add("hidden");
    if (studentClassInput) studentClassInput.value = saved ? saved.hr_class || "" : "";
    if (studentNumberInput) studentNumberInput.value = saved ? saved.number || "" : "";
    if (studentNameInput) studentNameInput.value = saved ? saved.name || "" : "";
    if (rosterSelectWrap) rosterSelectWrap.classList.add("hidden");
    if (rosterSelect) rosterSelect.innerHTML = '<option value="">— 名前を選択 —</option>';

    try {
      const configRes = await fetch(`/api/config?class_id=${encodeURIComponent(classId)}`);
      const configData = await configRes.json();
      if (configData.ok && configData.class) {
        pendingLessonClassName = configData.class.name || "";
        if (lessonClassDisplay) lessonClassDisplay.textContent = pendingLessonClassName;
      }
    } catch (_) {
      /* ignore */
    }

    try {
      const res = await fetch(`/admin/api/roster/${encodeURIComponent(classId)}`);
      const data = await res.json();
      const roster = data.students || [];
      if (roster.length && rosterSelect && rosterSelectWrap) {
        roster.forEach((student) => {
          const opt = document.createElement("option");
          opt.value = JSON.stringify(student);
          opt.textContent = `${student.hr_class || ""}　${student.number || ""}　${student.name || ""}`.trim();
          rosterSelect.appendChild(opt);
        });
        rosterSelectWrap.classList.remove("hidden");
      }
    } catch (_) {
      if (rosterSelectWrap) rosterSelectWrap.classList.add("hidden");
    }

    showStudentInfoOverlay();
  }

  async function loadClassSession(classId) {
    const res = await fetch(`/api/config?class_id=${encodeURIComponent(classId)}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "クラス設定の読み込みに失敗しました");

    const cls = data.class;
    selectedClassId = cls.id;
    sessionStorage.setItem(STORAGE_KEY, selectedClassId);

    if (activeClassNameEl) activeClassNameEl.textContent = cls.name;

    applyTimerSettings(cls.timers || {});
    setVideoPlayer(cls.video);

    if (!cls.video.has_script) {
      feedbackArea.textContent =
        "参照スクリプトが未設定です。管理画面でスクリプトを保存してください。評価はスクリプト設定後に可能です。";
    } else {
      feedbackArea.textContent = "要約を提出すると、ここに CEFR レベル別の評価が表示されます。";
    }

    hideClassPicker();
    updateSubmitState();
  }

  function startPrepTimer() {
    if (prepSeconds <= 0) {
      if (!isRecording) startRecording();
      return;
    }
    clearInterval(prepInterval);
    prepRemaining = prepSeconds;
    updatePrepDisplay();
    prepStartBtn.disabled = true;
    prepInterval = setInterval(() => {
      prepRemaining -= 1;
      updatePrepDisplay();
      if (prepRemaining <= 0) {
        clearInterval(prepInterval);
        prepStartBtn.textContent = "完了";
        prepStartBtn.disabled = false;
        if (!isRecording) startRecording();
      }
    }, 1000);
    prepStartBtn.textContent = "計測中…";
  }

  function startRecordTimer() {
    clearInterval(recordInterval);
    recordRemaining = recordSeconds;
    updateRecordDisplay();
    if (recordRemaining <= 0) {
      stopRecording();
      return;
    }
    recordInterval = setInterval(() => {
      recordRemaining -= 1;
      updateRecordDisplay();
      if (recordRemaining <= 0) stopRecording();
    }, 1000);
  }

  function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      recordStatus.textContent = "このブラウザは Web Speech API 非対応です";
      recordBtn.disabled = true;
      return null;
    }
    const rec = new SpeechRecognition();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalTranscript += t + " ";
        else interim += t;
      }
      transcriptArea.value = (finalTranscript + interim).trim();
      updateSubmitState();
    };

    rec.onerror = (e) => {
      if (e.error !== "no-speech") recordStatus.textContent = `エラー: ${e.error}`;
    };

    rec.onend = () => {
      if (isRecording) {
        try {
          rec.start();
        } catch (_) {
          /* ignore */
        }
      }
    };

    return rec;
  }

  function startRecording() {
    clearInterval(prepInterval);
    if (prepStartBtn) {
      prepStartBtn.disabled = false;
      prepStartBtn.textContent = prepSeconds > 0 ? "開始" : "準備なし";
    }
    if (!recognition) recognition = initSpeechRecognition();
    if (!recognition) return;

    if (hasRecordingEnded) {
      transcriptArea.value = "";
      finalTranscript = "";
      hasRecordingEnded = false;
      updateSubmitState();
    } else {
      finalTranscript = transcriptArea.value.trim() ? transcriptArea.value + " " : "";
    }
    isRecording = true;
    recordBtn.textContent = "録音停止";
    recordBtn.classList.replace("from-teal-600", "from-slate-500");
    recordBtn.classList.replace("to-emerald-600", "to-slate-600");
    recordStatus.textContent = "録音中…";
    try {
      recognition.start();
    } catch (_) {
      /* ignore */
    }
    startRecordTimer();
  }

  function stopRecording() {
    isRecording = false;
    clearInterval(recordInterval);
    if (recognition) {
      try {
        recognition.stop();
      } catch (_) {
        /* ignore */
      }
    }
    recordBtn.textContent = "録音開始";
    recordBtn.classList.replace("from-slate-500", "from-teal-600");
    recordBtn.classList.replace("to-slate-600", "to-emerald-600");
    recordStatus.textContent = "停止";
    hasRecordingEnded = true;
    updateSubmitState();
  }

  transcriptArea.addEventListener("input", syncTranscriptFromInput);
  transcriptArea.addEventListener("paste", () => setTimeout(syncTranscriptFromInput, 0));

  recordBtn.addEventListener("click", () => {
    if (isRecording) stopRecording();
    else startRecording();
  });

  prepStartBtn.addEventListener("click", startPrepTimer);

  submitBtn.addEventListener("click", async () => {
    const summary = transcriptArea.value.trim();
    if (!summary || !selectedClassId) return;

    submitBtn.disabled = true;
    submitMessage.classList.remove("hidden", "text-red-600", "text-emerald-600", "text-slate-500");
    submitMessage.textContent = "AI が評価中…";
    submitMessage.classList.add("text-slate-500");
    feedbackArea.textContent = "評価を生成しています…";

    try {
      const res = await fetch("/api/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          level: levelSelect.value,
          summary,
          class_id: selectedClassId,
          student_hr_class: studentHrClass,
          student_number: studentNumber,
          student_name: studentName,
        }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "評価に失敗しました");
      renderFeedback(data.feedback);
      feedbackArea.scrollTop = 0;
      submitMessage.textContent = "評価が完了しました。";
      submitMessage.classList.replace("text-slate-500", "text-emerald-600");
    } catch (err) {
      feedbackArea.textContent = err.message;
      submitMessage.textContent = err.message;
      submitMessage.classList.replace("text-slate-500", "text-red-600");
    } finally {
      updateSubmitState();
    }
  });

  if (classPickerStart) {
    classPickerStart.addEventListener("click", async () => {
      clearPickerError();
      const classId = classPickerSelect ? classPickerSelect.value.trim() : "";
      if (!classId) {
        showPickerError("クラスを選択してください。");
        return;
      }
      classPickerStart.disabled = true;
      try {
        await prepareStudentInfo(classId);
      } catch (err) {
        showPickerError(err.message);
      } finally {
        classPickerStart.disabled = false;
      }
    });
  }

  if (changeClassBtn) {
    changeClassBtn.addEventListener("click", () => {
      showClassPicker();
    });
  }

  if (rosterSelect) {
    rosterSelect.addEventListener("change", (e) => {
      if (!e.target.value) return;
      try {
        const student = JSON.parse(e.target.value);
        if (studentClassInput) studentClassInput.value = student.hr_class || "";
        if (studentNumberInput) studentNumberInput.value = student.number || "";
        if (studentNameInput) studentNameInput.value = student.name || "";
      } catch (_) {
        /* ignore */
      }
    });
  }

  if (studentInfoStart) {
    studentInfoStart.addEventListener("click", async () => {
      const number = studentNumberInput ? studentNumberInput.value.trim() : "";
      const name = studentNameInput ? studentNameInput.value.trim() : "";
      if (!number && !name) {
        if (studentInfoError) {
          studentInfoError.textContent = "番号または名前を入力してください。";
          studentInfoError.classList.remove("hidden");
        }
        return;
      }

      studentNumber = number;
      studentName = name;
      studentHrClass = studentClassInput ? studentClassInput.value.trim() : "";
      saveStudentInfo(pendingClassId, {
        hrClass: studentHrClass,
        number: studentNumber,
        name: studentName,
      });
      if (studentDisplayName) studentDisplayName.textContent = `${studentHrClass}　${number}　${name}`.trim();
      hideStudentInfoOverlay();
      try {
        await loadClassSession(pendingClassId);
      } catch (err) {
        appMain.classList.remove("hidden");
        feedbackArea.textContent = err.message || "クラス設定の読み込みに失敗しました。";
      }
    });
  }

  const urlParams = new URLSearchParams(window.location.search);
  const levelParam = urlParams.get("level");
  const allowedLevels = window.CEFR_LEVELS || ["A1", "A2", "B1", "B2"];
  if (levelParam && allowedLevels.includes(levelParam.toUpperCase())) {
    levelSelect.value = levelParam.toUpperCase();
  } else if (window.INITIAL_LEVEL) {
    levelSelect.value = window.INITIAL_LEVEL;
  }
  if (levelDisplay) levelDisplay.textContent = levelSelect.value;

  const urlClass = urlParams.get("class") || window.INITIAL_CLASS_ID || "";
  const initialClass = urlClass;
  if (classPickerSelect && initialClass) classPickerSelect.value = initialClass;

  function startInitialSession() {
    if (!initialClass) {
      appMain.classList.remove("hidden");
      feedbackArea.textContent = "クラスが未設定です。先生に共有リンクを確認してください。";
      return;
    }
    prepareStudentInfo(initialClass);
  }

  if (openingOverlay) {
    setTimeout(() => {
      openingOverlay.classList.add("opacity-0", "pointer-events-none", "transition-opacity", "duration-300");
      setTimeout(() => {
        openingOverlay.remove();
        startInitialSession();
      }, 320);
    }, 1950);
  } else {
    startInitialSession();
  }
})();
