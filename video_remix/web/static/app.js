// Video Remix AI - Creative Studio Client

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function getGoldenHookEnabled() {
  const toggle = document.getElementById("golden-hook-toggle");
  return toggle ? toggle.checked : true;
}

let currentJobId = null;
let pollTimer = null;
let activeResult = null;
let cumulativeOffsets = [];

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  setupEventListeners();
});

// Load configuration
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (data.status === "ok") {
      const cfg = data.config;
      const providerEl = document.getElementById("provider-select");
      if (providerEl) providerEl.value = cfg.active_provider || "gemini_relay";
      updateModelLabel(cfg.active_provider);
    }
  } catch (err) {
    console.error("Failed to load config:", err);
  }
}

function updateModelLabel(provider) {
  const tag = document.getElementById("model-tag");
  if (!tag) return;
  tag.textContent = provider === "dashscope"
    ? "Qwen-VL Plus"
    : "Gemini 3.7 Flash";
}

// Save config
async function saveConfig() {
  const provider = document.getElementById("provider-select").value;
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_provider: provider })
    });
    const data = await res.json();
    if (data.status === "ok") {
      updateModelLabel(provider);
      showToast("✅ 模型已切换");
    }
  } catch (err) {
    console.error("Failed to save config:", err);
  }
}

function setupEventListeners() {
  const providerEl = document.getElementById("provider-select");
  if (providerEl) providerEl.addEventListener("change", saveConfig);

  document.getElementById("btn-demo").addEventListener("click", runDemo);
  document.getElementById("btn-process").addEventListener("click", runProcess);

  // Upload zone
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleSelectedFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleSelectedFile(e.target.files[0]);
    }
  });

  const pathInput = document.getElementById("video-path-input");
  pathInput.addEventListener("input", () => {
    const val = pathInput.value.trim();
    if (val) showSourceCard(val.split("/").pop(), "本机路径");
  });

  const videoPlayer = document.getElementById("video-player");
  videoPlayer.addEventListener("timeupdate", updateTimelinePlayhead);
}

// File upload
async function handleSelectedFile(file) {
  const label = document.getElementById("dropzone-label");
  if (label) label.textContent = `正在传输: ${file.name}...`;

  showSourceCard(file.name, `${(file.size / (1024 * 1024)).toFixed(1)} MB`);

  const formData = new FormData();
  formData.append("video", file);

  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (data.status === "ok") {
      document.getElementById("video-path-input").value = data.file_path;
      if (label) label.textContent = `已载入: ${file.name}`;
      showToast("✅ 视频载入成功");
    } else {
      if (label) label.textContent = `上传失败: ${data.message}`;
    }
  } catch (err) {
    if (label) label.textContent = `上传出错: ${err.message}`;
  }
}

function showSourceCard(filename, meta) {
  const card = document.getElementById("source-info-card");
  card.style.display = "block";
  setText("source-filename", filename);
  setText("source-duration", meta || "已就绪");
}

// Run demo
async function runDemo() {
  setProcessingState(true);
  resetSteps();
  clearLogs();
  appendLog("启动测试样片流水线...");

  try {
    const res = await fetch("/api/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enable_golden_hook: getGoldenHookEnabled() })
    });
    const data = await res.json();
    if (data.status === "ok") {
      currentJobId = data.job_id;
      startPolling();
    } else {
      appendLog(`❌ 启动失败: ${data.message}`);
      setProcessingState(false);
    }
  } catch (err) {
    appendLog(`❌ 网络请求失败: ${err.message}`);
    setProcessingState(false);
  }
}

// Run process
async function runProcess() {
  const videoPath = document.getElementById("video-path-input").value.trim();
  if (!videoPath) {
    showToast("请先上传视频或输入路径");
    return;
  }

  setProcessingState(true);
  resetSteps();
  clearLogs();
  appendLog(`开始处理: ${videoPath.split("/").pop()}`);

  try {
    const res = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: videoPath,
        mode: "multimodal",
        enable_golden_hook: getGoldenHookEnabled()
      })
    });
    const data = await res.json();
    if (data.status === "ok") {
      currentJobId = data.job_id;
      startPolling();
    } else {
      appendLog(`❌ 启动失败: ${data.message}`);
      setProcessingState(false);
    }
  } catch (err) {
    appendLog(`❌ 任务派发失败: ${err.message}`);
    setProcessingState(false);
  }
}

// Polling
function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!currentJobId) return;
    try {
      const res = await fetch(`/api/status?job_id=${currentJobId}`);
      const data = await res.json();

      if (data.status === "ok") {
        updateLogs(data.logs);

        const done = data.state === "completed" || data.job_status === "completed";
        const fail = data.state === "error" || data.state === "failed" || data.job_status === "failed";

        if (done) {
          clearInterval(pollTimer);
          setProcessingState(false);
          setAllStepsCompleted();
          showToast("🎉 智能剪辑完成！");
          renderResults(data.result);
        } else if (fail) {
          clearInterval(pollTimer);
          setProcessingState(false);
          appendLog(`❌ 任务失败: ${data.error || "未知异常"}`);
          showToast("处理异常，请查看控制台");
        }
      }
    } catch (err) {
      console.error("Polling error:", err);
    }
  }, 800);
}

// Logs
function clearLogs() {
  document.getElementById("log-console").innerHTML = "";
}

function appendLog(line) {
  const el = document.getElementById("log-console");
  const div = document.createElement("div");
  div.className = "log-line";

  if (line.includes("✅") || line.includes("完成")) div.className += " text-green";
  else if (line.includes("多模态") || line.includes("Gemini") || line.includes("审片")) div.className += " text-cyan";
  else if (line.includes("❌") || line.includes("失败")) div.className += " text-red";
  else if (line.includes("Token") || line.includes("消耗")) div.className += " text-violet";

  div.textContent = `> ${line}`;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  detectStageFromLine(line);
}

function updateLogs(arr) {
  if (!arr) return;
  document.getElementById("log-console").innerHTML = "";
  arr.forEach(l => appendLog(l));
}

// Steps
function detectStageFromLine(line) {
  if (line.includes("[1/4]") || line.includes("探测源视频")) {
    setStepActive("stage-probe");
  } else if (line.includes("代理视频") || line.includes("极速转码")) {
    setStepDone("stage-probe"); setStepActive("stage-proxy");
  } else if (line.includes("[2/4]") || line.includes("Gemini") || line.includes("全音画")) {
    setStepDone("stage-proxy"); setStepActive("stage-ai");
  } else if (line.includes("[3/4]") || line.includes("拼接") || line.includes("[4/4]")) {
    setStepDone("stage-ai"); setStepActive("stage-draft");
  }
}

function resetSteps() {
  ["stage-probe", "stage-proxy", "stage-ai", "stage-draft"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = "step-item";
  });
}

function setStepActive(id) {
  const el = document.getElementById(id);
  if (el) el.className = "step-item active";
}

function setStepDone(id) {
  const el = document.getElementById(id);
  if (el) el.className = "step-item completed";
}

function setAllStepsCompleted() {
  ["stage-probe", "stage-proxy", "stage-ai", "stage-draft"].forEach(id => setStepDone(id));
}

function setProcessingState(active) {
  const btnP = document.getElementById("btn-process");
  const btnD = document.getElementById("btn-demo");
  const pill = document.getElementById("pipeline-status-pill");
  const text = document.getElementById("pipeline-status-text");

  if (active) {
    if (btnP) btnP.disabled = true;
    if (btnD) btnD.disabled = true;
    if (pill) pill.className = "progress-badge active";
    if (text) text.textContent = "处理中...";
  } else {
    if (btnP) btnP.disabled = false;
    if (btnD) btnD.disabled = false;
    if (pill) pill.className = "progress-badge";
    if (text) text.textContent = "等待开始";
  }
}

// Render results
function renderResults(result) {
  if (!result) return;
  activeResult = result;

  const placeholder = document.getElementById("placeholder-view");
  if (placeholder) placeholder.style.display = "none";
  const rv = document.getElementById("result-view");
  if (rv) rv.style.display = "block";

  const plan = result.plan || {};

  setText("result-title", plan.title || "AI 智能精剪视频");
  setText("result-hook", plan.hook_summary ? `⚡ ${plan.hook_summary}` : "");

  // Golden Hook
  const ghCard = document.getElementById("golden-hook-card");
  const gh = plan.golden_hook;
  if (gh && ghCard) {
    ghCard.style.display = "block";
    setText("gh-timecode", `[${fmt(gh.start)} → ${fmt(gh.end)}] · ${gh.duration ? gh.duration.toFixed(1) : (gh.end - gh.start).toFixed(1)}s`);
    setText("gh-punchline", gh.punchline || "高潮爆点前置");
    setText("gh-technique", gh.hook_technique || "高潮前置");
    setText("gh-caption", gh.voiceover_caption || "");
  } else if (ghCard) {
    ghCard.style.display = "none";
  }

  // Discarded
  const discarded = plan.discarded_total_duration || 0;
  const discEl = document.getElementById("metric-discarded");
  if (discarded > 0 && discEl) {
    discEl.style.display = "inline";
    setText("metric-discarded", `已过滤 ${discarded.toFixed(0)}s 冗余`);
  }

  // Metrics
  const origDur = result.original_duration || 0;
  const remixDur = result.remix_duration || 0;
  const ratio = origDur > 0 ? ((remixDur / origDur) * 100).toFixed(0) : 100;
  setText("metric-duration", `${fmt(origDur)} → ${fmt(remixDur)}`);
  setText("metric-ratio", `保留 ${ratio}%`);

  // Player
  const player = document.getElementById("video-player");
  if (player && result.output_video) {
    player.src = `/media/${encodeURIComponent(result.output_video)}`;
    player.load();
  }

  setText("draft-path-text", result.draft_dir || "-");

  // Cumulative offsets
  cumulativeOffsets = [];
  const ghDur = (gh && getGoldenHookEnabled()) ? (gh.duration || (gh.end - gh.start) || 0) : 0;
  let cum = ghDur;
  (plan.clips || []).forEach(c => {
    cumulativeOffsets.push(cum);
    cum += (c.end - c.start);
  });

  renderTimeline(plan.clips || [], origDur);
  renderShots(plan.clips || []);
}

// Timeline
function renderTimeline(clips, totalDur) {
  const base = document.getElementById("timeline-base");
  const ticks = document.getElementById("timeline-ticks");
  const tooltip = document.getElementById("timeline-tooltip");
  base.innerHTML = "";
  ticks.innerHTML = "";
  if (totalDur <= 0) return;

  for (let i = 0; i <= 5; i++) {
    const span = document.createElement("span");
    span.textContent = fmt((totalDur / 5) * i);
    ticks.appendChild(span);
  }

  clips.forEach((clip, idx) => {
    const left = (clip.start / totalDur) * 100;
    const width = Math.max(1.5, ((clip.end - clip.start) / totalDur) * 100);
    const seg = document.createElement("div");
    seg.className = "timeline-segment";
    seg.style.left = `${left}%`;
    seg.style.width = `${width}%`;
    seg.textContent = `${idx + 1}`;

    const remStart = cumulativeOffsets[idx] || 0;

    seg.addEventListener("mouseenter", () => {
      if (tooltip && base) {
        tooltip.style.display = "block";
        tooltip.textContent = `[${fmt(clip.start)} - ${fmt(clip.end)}] ${clip.title} (${(clip.end - clip.start).toFixed(1)}s)`;
        const r = seg.getBoundingClientRect();
        const p = base.getBoundingClientRect();
        tooltip.style.left = `${r.left - p.left + r.width / 2 - 40}px`;
        tooltip.style.top = `-28px`;
      }
    });

    seg.addEventListener("mouseleave", () => { if (tooltip) tooltip.style.display = "none"; });
    seg.addEventListener("click", () => { seekPlayer(remStart); showToast(`▶ 镜头 ${idx + 1}: ${clip.title}`); });
    base.appendChild(seg);
  });
}

function updateTimelinePlayhead() {
  const player = document.getElementById("video-player");
  const head = document.getElementById("timeline-playhead");
  if (!activeResult || !player.duration) { head.style.display = "none"; return; }
  head.style.display = "block";
  head.style.left = `${(player.currentTime / player.duration) * 100}%`;
}

// Shot Cards
function renderShots(clips) {
  const list = document.getElementById("shot-list");
  list.innerHTML = "";
  setText("clip-count-badge", `${clips.length} 个镜头`);

  clips.forEach((clip, idx) => {
    const card = document.createElement("div");
    card.className = "shot-card";
    const remStart = cumulativeOffsets[idx] || 0;
    const dur = (clip.end - clip.start).toFixed(1);
    const role = roleLabel(clip.narrative_role);

    card.innerHTML = `
      <div class="shot-header">
        <div class="shot-tags">
          <span class="shot-role-tag">${role}</span>
          <span class="shot-time-tag">[${fmt(clip.start)} → ${fmt(clip.end)}] · ${dur}s</span>
        </div>
        <button class="btn-play-shot" onclick="event.stopPropagation(); seekPlayer(${remStart})">▶ 试听</button>
      </div>
      <div class="shot-title">${clip.title || `镜头 ${idx + 1}`}</div>
      <div class="shot-reason">${clip.reason || ""}</div>
      ${clip.visual_action ? `<div class="shot-detail"><span class="detail-icon">👁</span><span class="detail-label">景别</span><span class="detail-text">${clip.visual_action}</span></div>` : ''}
      ${clip.audio_dialogue ? `<div class="shot-detail"><span class="detail-icon">🎙</span><span class="detail-label">台词</span><span class="detail-text">${clip.audio_dialogue}</span></div>` : ''}
      ${clip.discarded_context ? `<div class="shot-detail"><span class="detail-icon">✂️</span><span class="detail-label">过滤</span><span class="detail-text">${clip.discarded_context}</span></div>` : ''}
    `;

    card.addEventListener("click", () => { seekPlayer(remStart); showToast(`▶ ${clip.title}`); });
    list.appendChild(card);
  });
}

function roleLabel(role) {
  switch (role) {
    case "hook": return "🎯 开篇";
    case "climax": return "🔥 高潮";
    case "twist": return "⚡ 转折";
    case "conclusion": return "🎬 收束";
    case "context": return "📖 铺垫";
    default: return "✨ 精选";
  }
}

// Player
function seekPlayer(t) {
  const p = document.getElementById("video-player");
  if (p) { p.currentTime = t; p.play(); }
}

function seekGoldenHook() {
  seekPlayer(0);
  showToast("⚡ 试听黄金3秒钩子");
}

// Copy
function copyDraftPath() {
  const text = document.getElementById("draft-path-text")?.textContent || "";
  if (!text || text === "-") return;
  navigator.clipboard.writeText(text).then(() => showToast("✅ 路径已复制")).catch(() => showToast("复制失败"));
}

// Toast
function showToast(msg) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.style.display = "block";
  setTimeout(() => { t.style.display = "none"; }, 2500);
}

// Format MM:SS
function fmt(s) {
  if (isNaN(s) || s < 0) return "00:00";
  return `${Math.floor(s / 60).toString().padStart(2, "0")}:${Math.floor(s % 60).toString().padStart(2, "0")}`;
}

// Keep old name for compatibility
const formatTime = fmt;

// Globals for onclick
window.runDemo = runDemo;
window.runProcess = runProcess;
window.clearLogs = clearLogs;
window.copyDraftPath = copyDraftPath;
window.seekGoldenHook = seekGoldenHook;
window.seekPlayer = seekPlayer;
