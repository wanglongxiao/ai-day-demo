/* Lumina video generator frontend logic. */
(function () {
  "use strict";

  var I18N = window.I18N;
  var SUPPORTED = window.SUPPORTED_LANGS;
  var DEFAULT_LANG = window.DEFAULT_LANG;

  var lang = detectLang();
  var pollTimer = null;
  var previewUrl = null;

  // ---- i18n ---------------------------------------------------------------
  function detectLang() {
    var saved = localStorage.getItem("lang");
    if (saved && SUPPORTED.indexOf(saved) >= 0) return saved;
    return DEFAULT_LANG;
  }

  function t(key) {
    var dict = I18N[lang] || I18N[DEFAULT_LANG];
    return dict[key] || I18N[DEFAULT_LANG][key] || key;
  }

  function applyI18n() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-ph]").forEach(function (el) {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-ph")));
    });
    document.querySelectorAll("[data-i18n-alt]").forEach(function (el) {
      el.setAttribute("alt", t(el.getAttribute("data-i18n-alt")));
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach(function (el) {
      el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria-label")));
    });
    var sel = document.getElementById("lang-select");
    if (sel) sel.value = lang;
  }

  function setLang(l) {
    lang = l;
    localStorage.setItem("lang", l);
    applyI18n();
    // refresh dynamic strings depending on current view
    if (currentTaskId && isTaskView()) refreshTaskUI(lastState);
  }

  // ---- helpers ------------------------------------------------------------
  function $(id) { return document.getElementById(id); }
  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function getQueryTaskId() {
    var p = new URLSearchParams(window.location.search);
    return p.get("task");
  }

  function isTaskView() {
    return !!getQueryTaskId();
  }

  async function api(path, opts) {
    var res = await fetch(path, opts);
    if (!res.ok) {
      var msg = "request failed";
      try { msg = (await res.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    return res.json();
  }

  // ---- password gate ------------------------------------------------------
  async function checkGate() {
    try {
      var cfg = await api("/api/config");
      if (cfg.require_password) {
        var authed = sessionStorage.getItem("authed") === "1";
        if (!authed) show($("gate"));
      }
    } catch (e) { /* ignore */ }
  }

  function initGate() {
    $("gate-btn").addEventListener("click", async function () {
      var pwd = $("gate-pwd").value;
      var fd = new FormData();
      fd.append("password", pwd);
      try {
        await api("/api/auth", { method: "POST", body: fd });
        sessionStorage.setItem("authed", "1");
        hide($("gate"));
      } catch (e) {
        show($("gate-err"));
      }
    });
  }

  // ---- CREATE view --------------------------------------------------------
  var currentTaskId = null;
  var selectedFile = null;
  var selectedGender = null;

  function initCreate() {
    document.querySelectorAll(".gender-option").forEach(function (option) {
      option.addEventListener("click", function () {
        selectGender(option.getAttribute("data-gender"));
      });
    });

    $("image-input").addEventListener("change", function (e) {
      var f = e.target.files[0];
      selectedFile = f || null;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = null;
      if (f) {
        previewUrl = URL.createObjectURL(f);
        $("preview-img").src = previewUrl;
        show($("preview-wrap"));
      } else {
        hide($("preview-wrap"));
      }
    });

    $("generate-btn").addEventListener("click", onGenerate);
  }

  function selectGender(gender) {
    selectedGender = gender;
    document.querySelectorAll(".gender-option").forEach(function (option) {
      var selected = option.getAttribute("data-gender") === gender;
      option.classList.toggle("selected", selected);
      option.setAttribute("aria-checked", selected ? "true" : "false");
    });
    $("image-input").disabled = false;
    hide($("create-err"));
  }

  async function onGenerate() {
    var errEl = $("create-err");
    hide(errEl);
    if (!selectedGender) {
      errEl.textContent = t("err_need_gender");
      show(errEl);
      return;
    }
    if (!selectedFile) {
      errEl.textContent = t("err_need_image");
      show(errEl);
      return;
    }

    var btn = $("generate-btn");
    btn.disabled = true;
    try {
      // Create task (unique task_id for this browser window)
      var created = await api("/api/task", { method: "POST" });
      currentTaskId = created.task_id;

      var fd = new FormData();
      fd.append("gender", selectedGender);
      fd.append("image", selectedFile);

      await api("/api/task/" + currentTaskId + "/generate", {
        method: "POST",
        body: fd,
      });

      await showSubmitted(currentTaskId);
    } catch (e) {
      errEl.textContent = e.message;
      show(errEl);
      btn.disabled = false;
    }
  }

  function taskPageUrl(taskId) {
    var base = window.location.origin + window.location.pathname.replace(/index\.html$/, "");
    if (!base.endsWith("/")) base += "/";
    return base + "?task=" + encodeURIComponent(taskId);
  }

  async function showSubmitted(taskId) {
    $("submitted-notice").textContent = t("submitted_notice");
    var url = taskPageUrl(taskId);
    var link = $("task-link");
    link.href = url;
    link.textContent = url;

    try {
      var qr = await api("/api/qrcode?url=" + encodeURIComponent(url));
      $("qr-img").src = qr.data_uri;
    } catch (e) { /* ignore */ }

    // Hide the form card (first .card in create-view), reveal the QR panel.
    var cards = document.querySelectorAll("#create-view > .card");
    if (cards[0]) hide(cards[0]);
    show($("submitted-panel"));
  }

  // ---- TASK view (via QR / shared URL) -----------------------------------
  var lastState = null;

  async function initTaskView(taskId) {
    hide($("create-view"));
    show($("task-view"));
    currentTaskId = taskId;
    await pollTask(taskId);
    pollTimer = setInterval(function () { pollTask(taskId); }, 60000);
  }

  async function pollTask(taskId) {
    try {
      var state = await api("/api/task/" + taskId);
      lastState = state;
      refreshTaskUI(state);
      if (state.status === "succeeded" || state.status === "expired" || state.status === "failed") {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      }
    } catch (e) {
      // task not found -> show generating-ish message
    }
  }

  function refreshTaskUI(state) {
    if (!state) return;
    var msg = $("task-message");
    var spinner = $("task-spinner");
    var result = $("task-result");

    if (state.status === "succeeded" && state.video_url) {
      hide(spinner);
      hide(msg);
      show(result);
      $("result-video").src = state.video_url;
      $("result-url").textContent = state.video_url;
      var dl = $("download-link");
      dl.href = state.video_url;
      dl.querySelector("span").textContent = t("download_btn");
      // success headline
      msg.textContent = t("task_succeeded");
      show(msg);
    } else if (state.status === "expired") {
      hide(spinner);
      hide(result);
      show(msg);
      msg.textContent = t("task_expired");
    } else if (state.status === "failed") {
      hide(spinner);
      hide(result);
      show(msg);
      msg.textContent = t("task_failed");
    } else {
      show(spinner);
      hide(result);
      show(msg);
      msg.textContent = t("task_generating");
    }
  }

  // ---- boot ---------------------------------------------------------------
  function init() {
    applyI18n();
    $("lang-select").addEventListener("change", function (e) {
      setLang(e.target.value);
    });
    initGate();
    checkGate();

    var taskId = getQueryTaskId();
    if (taskId) {
      initTaskView(taskId);
    } else {
      initCreate();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
