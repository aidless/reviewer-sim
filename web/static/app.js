/**
 * 智能论文评审系统 - 仪表盘前端
 */

// 状态
let currentRunDir = "";
let currentRunId = null;
let eventSource = null;
let runStartTime = null;
let elapsedInterval = null;
let sortColumn = "display_date";
let sortAsc = false;  // 默认：最新在前
let promptFiles = [];        // [{filename, content}, ...]
let currentPromptFilename = "";
let configDirty = {};        // {key: value} 待保存的修改
let originalConfig = {};     // 编辑前的快照
let batchActive = false;
let batchDirs = [];
let batchRunId = null;       // 当前批量目录的 SSE run_id

// DOM 引用
const runSelector = document.getElementById("run-selector");
const modeSelector = document.getElementById("mode-selector");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const uploadBtn = document.getElementById("upload-btn");
const uploadInput = document.getElementById("upload-input");
const paperCount = document.getElementById("paper-count");
const dropOverlay = document.getElementById("drop-overlay");
const uploadToast = document.getElementById("upload-toast");
const uploadToastMsg = document.getElementById("upload-toast-msg");
const progressBar = document.getElementById("progress-bar");
const progressText = document.getElementById("progress-text");
const progressEta = document.getElementById("progress-eta");
const costDisplay = document.getElementById("cost-display");
const elapsedDisplay = document.getElementById("elapsed-display");
const currentPaperDisplay = document.getElementById("current-paper-display");
const resultsTbody = document.getElementById("results-tbody");
const noResults = document.getElementById("no-results");
const logContent = document.getElementById("log-content");
const configContent = document.getElementById("config-content");
const reviewModal = document.getElementById("review-modal");
const reviewModalTitle = document.getElementById("review-modal-title");
const reviewModalBody = document.getElementById("review-modal-body");
const reviewModalClose = document.getElementById("review-modal-close");
const promptSelector = document.getElementById("prompt-selector");
const promptsEditor = document.getElementById("prompts-editor");
const promptVarsHint = document.getElementById("prompt-vars-hint");
const promptSaveBtn = document.getElementById("prompt-save-btn");
const promptReloadBtn = document.getElementById("prompt-reload-btn");
const promptValidation = document.getElementById("prompt-validation");
const criteriaEditorWrap = document.getElementById("criteria-editor-wrap");
const criteriaSaveBtn = document.getElementById("criteria-save-btn");
const criteriaReloadBtn = document.getElementById("criteria-reload-btn");
const criteriaValidation = document.getElementById("criteria-validation");
const sourcesEditor = document.getElementById("sources-editor");
const sourcesSaveBtn = document.getElementById("sources-save-btn");
const sourcesReloadBtn = document.getElementById("sources-reload-btn");
const sourcesValidation = document.getElementById("sources-validation");
const configSaveBtn = document.getElementById("config-save-btn");
const costsEditor = document.getElementById("costs-editor");
const costsSaveBtn = document.getElementById("costs-save-btn");
const costsReloadBtn = document.getElementById("costs-reload-btn");
const costsLookupBtn = document.getElementById("costs-lookup-btn");
const costsValidation = document.getElementById("costs-validation");
const costsLookupResult = document.getElementById("costs-lookup-result");
const judgeBtn = document.getElementById("judge-btn");
const viewVerdictsBtn = document.getElementById("view-verdicts-btn");
const batchBtn = document.getElementById("batch-btn");
const batchStopBtn = document.getElementById("batch-stop-btn");
const batchPanel = document.getElementById("batch-panel");
const batchProgressBar = document.getElementById("batch-progress-bar");
const batchText = document.getElementById("batch-text");
const batchCurrent = document.getElementById("batch-current");
const batchDirsList = document.getElementById("batch-dirs-list");
const judgeModal = document.getElementById("judge-modal");
const judgeModalBody = document.getElementById("judge-modal-body");
const judgeModalClose = document.getElementById("judge-modal-close");

// ---- 初始化 ----

async function init() {
    await loadRuns();
    runSelector.addEventListener("change", onRunSelected);
    startBtn.addEventListener("click", startRun);
    stopBtn.addEventListener("click", stopRun);
    reviewModalClose.addEventListener("click", () => reviewModal.style.display = "none");

    // 侧边栏标签页
    document.querySelectorAll(".sidebar-tab").forEach(tab => {
        tab.addEventListener("click", () => switchSidebarTab(tab.dataset.tab));
    });

    // 可折叠配置面板
    document.getElementById("panel-toggle").addEventListener("click", toggleConfigPanel);

    // 提示词编辑器
    promptSelector.addEventListener("change", onPromptSelected);
    promptSaveBtn.addEventListener("click", savePrompt);
    promptReloadBtn.addEventListener("click", reloadPrompt);

    // 评审标准编辑器
    criteriaSaveBtn.addEventListener("click", saveCriteria);
    criteriaReloadBtn.addEventListener("click", reloadCriteria);

    // 文献源编辑器
    sourcesSaveBtn.addEventListener("click", saveSources);
    sourcesReloadBtn.addEventListener("click", reloadSources);

    // 配置保存
    configSaveBtn.addEventListener("click", saveConfig);

    // 费用编辑器
    costsSaveBtn.addEventListener("click", saveCosts);
    costsReloadBtn.addEventListener("click", reloadCosts);
    costsLookupBtn.addEventListener("click", lookupModelCost);

    // 裁判
    judgeBtn.addEventListener("click", startJudge);
    judgeModalClose.addEventListener("click", () => judgeModal.style.display = "none");
    if (viewVerdictsBtn) viewVerdictsBtn.addEventListener("click", showJudgeVerdicts);

    // 批量处理
    batchBtn.addEventListener("click", startBatch);
    batchStopBtn.addEventListener("click", stopBatch);

    // 上传
    uploadBtn.addEventListener("click", () => uploadInput.click());
    uploadInput.addEventListener("change", handleFileSelect);
    setupDragDrop();

    // 加载全局资源
    await loadPrompts();
    await loadSources();
    await loadCosts();

    // 排序表头
    document.querySelectorAll("#results-table th[data-sort]").forEach(th => {
        th.addEventListener("click", () => {
            const col = th.dataset.sort;
            if (sortColumn === col) sortAsc = !sortAsc;
            else { sortColumn = col; sortAsc = true; }
            sortAndRenderResults();
        });
    });

    // 刷新报告按钮
    document.getElementById("refresh-reports-btn").addEventListener("click", loadResults);

    // 未保存修改时提醒
    window.addEventListener("beforeunload", (e) => {
        if (Object.keys(configDirty).length > 0) {
            e.preventDefault();
            e.returnValue = "";
        }
    });
}

// ---- API 辅助 ----

async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    if (!res.ok) {
        let detail = `${res.status}: ${res.statusText}`;
        try {
            const body = await res.json();
            if (body.detail) detail = body.detail;
        } catch {}
        throw new Error(detail);
    }
    return res.json();
}

// ---- 运行目录选择 ----

async function loadRuns() {
    const data = await api("/api/runs");
    runSelector.innerHTML = '<option value="">选择运行目录...</option>';
    for (const run of data.runs) {
        const opt = document.createElement("option");
        opt.value = run.name;
        opt.textContent = `${run.name}（${run.paper_count} 篇论文）`;
        runSelector.appendChild(opt);
    }
}

async function onRunSelected() {
    currentRunDir = runSelector.value;
    startBtn.disabled = !currentRunDir;

    // 清除上一个运行目录的过期状态
    reportsData = [];
    renderResults([]);
    configDirty = {};
    originalConfig = {};
    configSaveBtn.style.display = "none";
    logContent.innerHTML = "";
    progressBar.style.width = "0%";
    progressText.textContent = "";
    progressEta.textContent = "";
    costDisplay.textContent = "$0.00";
    elapsedDisplay.textContent = "0秒";
    currentPaperDisplay.textContent = "";
    clearStages();
    if (viewVerdictsBtn) viewVerdictsBtn.style.display = "none";

    if (!currentRunDir) {
        configContent.innerHTML = '<p class="placeholder-text">选择运行目录以查看配置</p>';
        criteriaEditorWrap.innerHTML = '<p class="placeholder-text">选择运行目录以编辑评审标准</p>';
        uploadBtn.disabled = true;
        paperCount.textContent = "📄 0";
        return;
    }

    uploadBtn.disabled = false;
    await refreshPaperCount();

    // 加载可编辑配置
    await loadConfig();

    // 加载评审标准（原始 YAML）
    await loadCriteria();

    // 加载已有结果
    await loadResults();
    await loadReviews();
    await checkJudgeVerdicts();
}

// ---- 开始 / 停止 ----

async function startRun() {
    if (!currentRunDir) return;

    startBtn.disabled = true;
    stopBtn.style.display = "inline-block";
    runStartTime = Date.now();
    logContent.innerHTML = "";
    clearStages();

    try {
        const data = await api("/api/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                run_dir: currentRunDir,
                mode: modeSelector.value,
                config_overrides: {},
            }),
        });
        currentRunId = data.run_id;
        connectSSE();
        startElapsedTimer();
    } catch (e) {
        addLog("启动失败：" + e.message, "error");
        startBtn.disabled = false;
        stopBtn.style.display = "none";
    }
}

async function stopRun() {
    if (!currentRunId) return;
    try {
        await api(`/api/stop/${currentRunId}`, { method: "POST" });
        addLog("已请求取消...", "warning");
    } catch (e) {
        addLog("停止失败：" + e.message, "error");
    }
}

// ---- SSE ----

let sseReconnectAttempts = 0;
const SSE_MAX_RECONNECT = 5;

function connectSSE() {
    if (eventSource) eventSource.close();
    sseReconnectAttempts = 0;
    _openSSE();
}

function _openSSE() {
    eventSource = new EventSource(`/api/events/${currentRunId}`);

    eventSource.addEventListener("progress", (e) => {
        sseReconnectAttempts = 0;
        try {
            const evt = JSON.parse(e.data);
            handleEvent(evt);
        } catch {}
    });

    eventSource.addEventListener("ping", () => {
        sseReconnectAttempts = 0;
    });

    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        sseReconnectAttempts++;
        if (sseReconnectAttempts <= SSE_MAX_RECONNECT) {
            addLog(`连接断开 — 正在重连（${sseReconnectAttempts}/${SSE_MAX_RECONNECT}）...`, "warning");
            setTimeout(_openSSE, 2000 * sseReconnectAttempts);
        } else {
            addLog("连接断开。请刷新页面重新连接。", "error");
        }
    };
}

function handleEvent(evt) {
    switch (evt.event_type) {
        case "run_started":
            addLog(`评审开始：${evt.mode === "standard" ? "标准" : "文献增强"}模式，${evt.paper_count} 篇论文`, "info");
            break;

        case "stage_started":
            activateStage(evt.stage_name);
            addLog(`[${stageLabel(evt.stage_name)}] 开始处理 ${evt.paper_filename}`, "info");
            currentPaperDisplay.textContent = evt.paper_filename;
            break;

        case "stage_progress":
            addLog(`[${stageLabel(evt.stage_name)}] ${evt.current}/${evt.total} ${evt.detail}`, "info");
            break;

        case "stage_completed":
            completeStage(evt.stage_name);
            addLog(`[${stageLabel(evt.stage_name)}] 完成，耗时 ${evt.duration_s?.toFixed(1)}秒 — ${evt.result_summary}`, "success");
            break;

        case "paper_completed":
            addLog(`论文完成：${evt.paper_filename} | 分数：${evt.score?.toFixed(1)} | ${evt.recommendation} | $${evt.cost?.toFixed(4)}`, "success");
            break;

        case "run_progress": {
            const pct = evt.papers_total > 0 ? (100 * evt.papers_done / evt.papers_total) : 0;
            progressBar.style.width = pct + "%";
            progressText.textContent = `${evt.papers_done}/${evt.papers_total} 篇（${pct.toFixed(0)}%）`;
            if (evt.estimated_remaining_s > 0) {
                progressEta.textContent = `预计剩余：${formatDuration(evt.estimated_remaining_s)}`;
            }
            break;
        }

        case "cost_update":
            costDisplay.textContent = `$${evt.total_cost?.toFixed(4)}`;
            break;

        case "error":
            addLog(`[${stageLabel(evt.stage_name)}] ${evt.message}`, evt.recoverable ? "warning" : "error");
            break;

        case "run_completed":
            addLog(`评审完成：${evt.total_papers} 篇论文，$${evt.total_cost?.toFixed(4)}，耗时 ${formatDuration(evt.total_time_s)}`, "success");
            progressBar.style.width = "100%";
            progressText.textContent = "完成";
            progressEta.textContent = "";
            if (!batchActive) finishRun();
            break;

        case "batch_dir_started":
            addLog(`[批量] 开始处理 ${evt.dir_name}（${evt.dir_index + 1}/${evt.dir_total}）`, "info");
            updateBatchProgress(evt.dir_index, evt.dir_total, evt.dir_name);
            break;

        case "batch_completed":
            addLog(`[批量] 完成：${evt.completed} 成功，${evt.failed} 失败，耗时 ${formatDuration(evt.total_time_s)}`, "success");
            finishBatch();
            break;
    }
}

function stageLabel(name) {
    const map = {
        "Ingestion": "论文解析", "Librarian": "文献检索",
        "Extraction": "逐项评估", "Fact-Check": "事实核查",
        "Synthesis": "综合评审", "Output": "输出结果",
        "Judge-Compare": "模型对比", "Judge-Adjudicate": "裁判裁决"
    };
    return map[name] || name;
}

function finishRun() {
    startBtn.disabled = false;
    stopBtn.style.display = "none";
    judgeBtn.disabled = false;
    if (elapsedInterval) clearInterval(elapsedInterval);
    if (eventSource) { eventSource.close(); eventSource = null; }
    loadResults();
    checkJudgeVerdicts();
}

// ---- 报告表格 ----

let reportsData = [];

async function loadResults() {
    if (!currentRunDir) return;
    try {
        const data = await api(`/api/all-reviews/${currentRunDir}`);
        reportsData = data.reviews || [];
        sortAndRenderResults();
    } catch {
        reportsData = [];
        renderResults([]);
    }
}

async function loadReviews() {
    // 评审详情按需加载（点击"查看"时）
}

function sortAndRenderResults() {
    let sorted = [...reportsData];
    if (sortColumn) {
        sorted.sort((a, b) => {
            let va = a[sortColumn], vb = b[sortColumn];
            if (va == null) va = "";
            if (vb == null) vb = "";
            if (typeof va === "string") va = va.toLowerCase();
            if (typeof vb === "string") vb = vb.toLowerCase();
            if (va < vb) return sortAsc ? -1 : 1;
            if (va > vb) return sortAsc ? 1 : -1;
            return 0;
        });
    }
    renderResults(sorted);
}

function renderResults(results) {
    resultsTbody.innerHTML = "";
    noResults.style.display = results.length ? "none" : "block";
    judgeBtn.disabled = results.length === 0;

    for (const r of results) {
        const tr = document.createElement("tr");

        const scoreVal = r.overall_score;
        const scoreClass = scoreVal != null && scoreVal !== "" ? (scoreVal >= 70 ? "score-high" : scoreVal >= 50 ? "score-mid" : "score-low") : "";
        const recClass = getRecClass(r.recommendation);

        tr.innerHTML = `
            <td>${escapeHtml(r.paper || "")}</td>
            <td class="td-date">${escapeHtml(r.display_date || "")}</td>
            <td class="td-model" title="${escapeHtml(r.extractor_model || "")}">${escapeHtml(r.extractor_model || "")}</td>
            <td class="td-model" title="${escapeHtml(r.synthesizer_model || "")}">${escapeHtml(r.synthesizer_model || "")}</td>
            <td><span class="score-badge ${scoreClass}">${scoreVal != null && scoreVal !== "" ? Number(scoreVal).toFixed(1) : "-"}</span></td>
            <td><span class="rec-badge ${recClass}">${escapeHtml(r.recommendation || "-")}</span></td>
            <td>${r.total_cost != null && r.total_cost !== "" ? "$" + Number(r.total_cost).toFixed(4) : "-"}</td>
            <td>${r.confidence != null && r.confidence !== "" ? (Number(r.confidence) * 100).toFixed(0) + "%" : "-"}</td>
            <td><button class="btn-view" data-filename="${escapeHtml(r.filename)}">查看</button></td>
        `;
        resultsTbody.appendChild(tr);
    }

    // 绑定查看按钮事件
    resultsTbody.querySelectorAll(".btn-view").forEach(btn => {
        btn.addEventListener("click", () => showReviewByFilename(btn.dataset.filename));
    });
}

async function showReviewByFilename(filename) {
    if (!currentRunDir) return;
    const paperName = filename.split("_20")[0] || filename;
    reviewModalTitle.textContent = `评审：${paperName}`;
    reviewModalBody.innerHTML = "加载中...";

    try {
        const res = await fetch(`/api/review/${currentRunDir}/${filename}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        reviewModalBody.innerHTML = renderMarkdown(text);
        reviewModal.style.display = "flex";
    } catch (e) {
        reviewModalBody.innerHTML = "加载评审失败：" + e.message;
    }
}

function getRecClass(rec) {
    if (!rec) return "";
    const l = rec.toLowerCase();
    // 支持中文建议标签
    if (l.includes("直接接收") || (l.includes("accept") && !l.includes("revision"))) return "rec-accept";
    if (l.includes("修改后接收") || l.includes("accept with revision") || l.includes("minor")) return "rec-revision";
    if (l.includes("大修") || l.includes("revise") || l.includes("resubmit") || l.includes("major")) return "rec-resubmit";
    if (l.includes("拒稿") || l.includes("reject")) return "rec-reject";
    return "";
}

// ---- 阶段指示器 ----

const stageMap = {
    "Ingestion": "stage-ingest",
    "Librarian": "stage-ingest",
    "Extraction": "stage-extraction",
    "Fact-Check": "stage-extraction",
    "Synthesis": "stage-synthesis",
    "Output": "stage-output",
    "Judge-Compare": "stage-extraction",
    "Judge-Adjudicate": "stage-synthesis",
};

function activateStage(name) {
    const id = stageMap[name];
    if (id) {
        const el = document.getElementById(id);
        el?.classList.add("active");
        el?.classList.remove("completed");
    }
}

function completeStage(name) {
    const id = stageMap[name];
    if (id) {
        const el = document.getElementById(id);
        el?.classList.remove("active");
        el?.classList.add("completed");
    }
}

function clearStages() {
    document.querySelectorAll(".stage-item").forEach(el => {
        el.classList.remove("active", "completed");
    });
}

// ---- 日志 ----

function addLog(message, level = "info") {
    const entry = document.createElement("div");
    entry.className = `log-entry log-${level}`;
    const now = new Date();
    const time = now.toLocaleTimeString("zh-CN", { hour12: false });
    entry.innerHTML = `<span class="log-time">${time}</span><span class="log-msg">${escapeHtml(message)}</span>`;
    logContent.appendChild(entry);
    logContent.scrollTop = logContent.scrollHeight;
}

// ---- 工具函数 ----

function startElapsedTimer() {
    if (elapsedInterval) clearInterval(elapsedInterval);
    elapsedInterval = setInterval(() => {
        if (runStartTime) {
            const s = (Date.now() - runStartTime) / 1000;
            elapsedDisplay.textContent = formatDuration(s);
        }
    }, 1000);
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds.toFixed(0)}秒`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(1)}分钟`;
    return `${(seconds / 3600).toFixed(1)}小时`;
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/^(\d+)\. (.+)$/gm, "<li>$2</li>");
    html = html.replace(/\n\n/g, "</p><p>");
    html = "<p>" + html + "</p>";
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/^---$/gm, "<hr>");
    return html;
}

// ---- 侧边栏标签切换 ----

function toggleConfigPanel() {
    const panel = document.getElementById("config-panel");
    const btn = document.getElementById("panel-toggle");
    panel.classList.toggle("collapsed");
    btn.innerHTML = panel.classList.contains("collapsed") ? "&rsaquo;" : "&lsaquo;";
    btn.title = panel.classList.contains("collapsed") ? "展开面板" : "折叠面板";
}

function switchSidebarTab(tabName) {
    document.querySelectorAll(".sidebar-tab").forEach(t => t.classList.remove("active"));
    document.querySelector(`.sidebar-tab[data-tab="${tabName}"]`).classList.add("active");
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    document.getElementById(`tab-${tabName}`).classList.add("active");
}

// ---- 配置编辑器 ----

const PROVIDER_OPTIONS = ["openai", "anthropic", "deepseek", "google", "gemini", "mistral", "ollama"];
const PROVIDER_KEYS = ["PROVIDER_EXTRACTION", "PROVIDER_SYNTHESIS", "JUDGE_PROVIDER"];
const NUMBER_KEYS = ["TEMPERATURE", "TEMPERATURE_EXTRACTION", "TEMPERATURE_SYNTHESIS", "JUDGE_TEMPERATURE", "MAX_TOKENS_EXTRACTION", "MAX_TOKENS_SYNTHESIS", "EXTRACTION_BATCH_SIZE", "MAX_PARALLEL_EXTRACTIONS", "MAX_RETRIES", "CONCURRENCY"];

async function loadConfig() {
    try {
        const data = await api(`/api/config/${currentRunDir}`);
        originalConfig = data.config || {};
        renderConfigEditor(originalConfig);
    } catch {
        configContent.innerHTML = '<p class="placeholder-text">无法加载配置</p>';
    }
}

function renderConfigEditor(config) {
    let html = "";
    for (const [k, v] of Object.entries(config)) {
        const isMasked = v === "***masked***";
        if (isMasked) {
            html += `<div class="config-item config-locked">
                <span class="config-key">${escapeHtml(k)}</span>
                <span class="config-value locked">***<span class="lock-hint">请直接编辑 .env 文件</span></span>
            </div>`;
            continue;
        }
        const isProvider = PROVIDER_KEYS.includes(k);
        const isNumber = NUMBER_KEYS.includes(k);
        let inputHtml;
        if (isProvider) {
            const opts = PROVIDER_OPTIONS.map(o =>
                `<option value="${o}" ${o === v ? "selected" : ""}>${o}</option>`
            ).join("");
            inputHtml = `<select class="config-input config-select" data-key="${escapeHtml(k)}">${opts}</select>`;
        } else if (isNumber) {
            const step = k.includes("TEMPERATURE") ? 'step="0.1"' : "";
            inputHtml = `<input type="number" class="config-input config-number" data-key="${escapeHtml(k)}" value="${escapeHtml(v)}" ${step}>`;
        } else {
            inputHtml = `<input type="text" class="config-input config-text" data-key="${escapeHtml(k)}" value="${escapeHtml(v)}">`;
        }
        html += `<div class="config-item editable-config">
            <span class="config-key">${escapeHtml(k)}</span>
            ${inputHtml}
        </div>`;
    }
    configContent.innerHTML = html || '<p class="placeholder-text">未找到配置</p>';

    // 跟踪修改
    configContent.querySelectorAll(".config-input").forEach(el => {
        el.addEventListener("change", () => {
            configDirty[el.dataset.key] = String(el.value);
            configSaveBtn.style.display = Object.keys(configDirty).length ? "inline-block" : "none";
        });
    });
}

async function saveConfig() {
    if (!currentRunDir || !Object.keys(configDirty).length) return;
    try {
        for (const [key, value] of Object.entries(configDirty)) {
            const data = await api(`/api/config/${currentRunDir}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ key, value }),
            });
            originalConfig = data.config || originalConfig;
        }
        configDirty = {};
        renderConfigEditor(originalConfig);
        configSaveBtn.style.display = "none";
        addLog("配置已保存", "success");
    } catch (e) {
        addLog("保存配置失败：" + e.message, "error");
    }
}

// ---- 评审标准编辑器 ----

let criteriaTextarea = null;

async function loadCriteria() {
    if (!currentRunDir) return;
    try {
        const data = await api(`/api/criteria-raw/${currentRunDir}`);
        criteriaEditorWrap.innerHTML = "";
        criteriaTextarea = document.createElement("textarea");
        criteriaTextarea.className = "code-editor";
        criteriaTextarea.value = data.content || "";
        criteriaEditorWrap.appendChild(criteriaTextarea);
        criteriaSaveBtn.style.display = "inline-block";
        criteriaReloadBtn.style.display = "inline-block";
        criteriaValidation.textContent = "";
    } catch (e) {
        criteriaEditorWrap.innerHTML = `<p class="placeholder-text">无法加载评审标准：${escapeHtml(e.message)}</p>`;
        criteriaSaveBtn.style.display = "none";
        criteriaReloadBtn.style.display = "none";
    }
}

async function saveCriteria() {
    if (!currentRunDir || !criteriaTextarea) return;
    criteriaValidation.textContent = "";
    try {
        await api(`/api/criteria/${currentRunDir}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: criteriaTextarea.value }),
        });
        criteriaValidation.textContent = "已保存！";
        criteriaValidation.className = "validation-msg success";
        addLog("评审标准已保存", "success");
    } catch (e) {
        criteriaValidation.textContent = e.message;
        criteriaValidation.className = "validation-msg error";
    }
}

async function reloadCriteria() {
    await loadCriteria();
}

// ---- 提示词编辑器 ----

const PROMPT_TEMPLATE_VARS = {
    "extractor_system.txt": "无模板变量（系统指令）",
    "extractor_user.txt": "{domain}、{paper_markdown}、{criterion_name}、{criterion_description}、{scale_definition}",
    "synthesizer_system.txt": "无模板变量（系统指令）",
    "synthesizer_user.txt": "{paper_title}、{paper_abstract}、{json_dump_of_extractions}、{weights_table}、{calculated_score}、{calculated_recommendation}",
};

async function loadPrompts() {
    try {
        const data = await api("/api/prompts");
        promptFiles = data.prompts || [];
        promptSelector.innerHTML = "";
        for (const p of promptFiles) {
            const opt = document.createElement("option");
            opt.value = p.filename;
            opt.textContent = p.filename.replace(/\.txt$/, "");
            promptSelector.appendChild(opt);
        }
        if (promptFiles.length > 0) {
            promptSelector.value = promptFiles[0].filename;
            onPromptSelected();
        }
    } catch {
        promptSelector.innerHTML = '<option value="">加载提示词失败</option>';
    }
}

function onPromptSelected() {
    const fn = promptSelector.value;
    if (!fn) return;
    currentPromptFilename = fn;
    const file = promptFiles.find(p => p.filename === fn);
    promptsEditor.value = file ? file.content : "";
    promptVarsHint.textContent = PROMPT_TEMPLATE_VARS[fn] || "";
    promptSaveBtn.disabled = false;
    promptValidation.textContent = "";
}

async function savePrompt() {
    if (!currentPromptFilename) return;
    promptValidation.textContent = "";
    try {
        await api(`/api/prompts/${currentPromptFilename}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: promptsEditor.value }),
        });
        const idx = promptFiles.findIndex(p => p.filename === currentPromptFilename);
        if (idx >= 0) promptFiles[idx].content = promptsEditor.value;
        promptValidation.textContent = "已保存！";
        promptValidation.className = "validation-msg success";
        addLog(`提示词「${currentPromptFilename}」已保存`, "success");
    } catch (e) {
        promptValidation.textContent = e.message;
        promptValidation.className = "validation-msg error";
    }
}

async function reloadPrompt() {
    try {
        const data = await api("/api/prompts");
        promptFiles = data.prompts || [];
        onPromptSelected();
        promptValidation.textContent = "已从磁盘重新加载";
        promptValidation.className = "validation-msg success";
    } catch (e) {
        promptValidation.textContent = e.message;
        promptValidation.className = "validation-msg error";
    }
}

// ---- 文献源编辑器 ----

async function loadSources() {
    try {
        const data = await api("/api/literature-sources");
        sourcesEditor.value = data.content || "";
        sourcesValidation.textContent = "";
    } catch {
        sourcesEditor.value = "";
        sourcesEditor.placeholder = "无法加载文献源配置";
    }
}

async function saveSources() {
    sourcesValidation.textContent = "";
    try {
        await api("/api/literature-sources", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: sourcesEditor.value }),
        });
        sourcesValidation.textContent = "已保存！";
        sourcesValidation.className = "validation-msg success";
        addLog("文献源配置已保存", "success");
    } catch (e) {
        sourcesValidation.textContent = e.message;
        sourcesValidation.className = "validation-msg error";
    }
}

async function reloadSources() {
    await loadSources();
}

// ---- 模型费用编辑器 ----

async function loadCosts() {
    try {
        const data = await api("/api/model-costs");
        costsEditor.value = data.content || "";
        costsValidation.textContent = "";
    } catch {
        costsEditor.value = "";
        costsEditor.placeholder = "无法加载模型费用";
    }
}

async function saveCosts() {
    costsValidation.textContent = "";
    try {
        await api("/api/model-costs", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: costsEditor.value }),
        });
        costsValidation.textContent = "已保存！模型已在 litellm 中重新注册。";
        costsValidation.className = "validation-msg success";
        addLog("模型费用已保存并重新注册", "success");
    } catch (e) {
        costsValidation.textContent = e.message;
        costsValidation.className = "validation-msg error";
    }
}

async function reloadCosts() {
    await loadCosts();
}

async function lookupModelCost() {
    const modelName = prompt("输入模型名称（如 openai/gpt-5.4-nano、anthropic/claude-sonnet-4-6）：");
    if (!modelName) return;
    costsLookupResult.textContent = "查询中...";
    try {
        const data = await api(`/api/model-costs/lookup/${encodeURIComponent(modelName)}`);
        costsLookupResult.innerHTML =
            `<strong>${escapeHtml(data.model)}</strong>：` +
            `输入 $${data.input_cost_per_million}/百万tokens，` +
            `输出 $${data.output_cost_per_million}/百万tokens` +
            (data.max_input_tokens ? ` | 最大输入：${(data.max_input_tokens / 1000).toFixed(0)}K` : "") +
            (data.max_output_tokens ? `，输出：${(data.max_output_tokens / 1000).toFixed(0)}K` : "");
        costsLookupResult.className = "lookup-result success";
    } catch (e) {
        costsLookupResult.textContent = e.message;
        costsLookupResult.className = "lookup-result error";
    }
}

// ---- 裁判 ----

async function checkJudgeVerdicts() {
    if (!currentRunDir) return;
    try {
        const data = await api(`/api/judge/results/${currentRunDir}`);
        const verdicts = data.verdicts || [];
        if (viewVerdictsBtn) viewVerdictsBtn.style.display = verdicts.length > 0 ? "inline-block" : "none";
    } catch {
        if (viewVerdictsBtn) viewVerdictsBtn.style.display = "none";
    }
}

async function startJudge() {
    if (!currentRunDir) return;
    judgeBtn.disabled = true;
    logContent.innerHTML = "";
    clearStages();

    try {
        const data = await api(`/api/judge/${currentRunDir}`, { method: "POST" });
        currentRunId = data.run_id;
        runStartTime = Date.now();
        connectSSE();
        startElapsedTimer();
        addLog("裁判流程已启动...", "info");
    } catch (e) {
        const msg = e.message || "未知错误";
        if (msg.includes("2 consolidated") || msg.includes("400")) {
            addLog("无法裁决：请先用至少两种不同模型运行评审，然后进行对比。", "warning");
        } else {
            addLog("裁判失败：" + msg, "error");
        }
        judgeBtn.disabled = false;
    }
}

async function showJudgeVerdicts() {
    if (!currentRunDir) return;
    judgeModalBody.innerHTML = "加载裁决中...";

    try {
        const data = await api(`/api/judge/results/${currentRunDir}`);
        const verdicts = data.verdicts || [];
        if (!verdicts.length) {
            judgeModalBody.innerHTML = '<p class="placeholder-text">暂无裁判裁决。请先运行"对比 & 裁决"。</p>';
            judgeModal.style.display = "flex";
            return;
        }

        let html = '<table class="results-table judge-table"><thead><tr>';
        html += "<th>论文</th><th>裁判决定</th><th>胜出</th><th>理由</th><th>费用</th>";
        html += "</tr></thead><tbody>";

        for (const v of verdicts) {
            const winClass = v.winning_review === "A" ? "rec-accept" :
                             v.winning_review === "B" ? "rec-reject" : "rec-revision";
            html += "<tr>";
            html += `<td>${escapeHtml(v.paper_filename || "")}</td>`;
            html += `<td><span class="rec-badge rec-revision">${escapeHtml(v.judge_recommendation || "")}</span></td>`;
            html += `<td><span class="rec-badge ${winClass}">${escapeHtml(v.winning_review || "")}</span></td>`;
            html += `<td>${escapeHtml(v.judge_rationale || "")}</td>`;
            html += `<td>$${parseFloat(v.judge_cost || 0).toFixed(4)}</td>`;
            html += "</tr>";
        }

        html += "</tbody></table>";
        judgeModalBody.innerHTML = html;
        judgeModal.style.display = "flex";
    } catch (e) {
        judgeModalBody.innerHTML = "错误：" + e.message;
    }
}

// ---- 批量处理 ----

async function startBatch() {
    batchBtn.disabled = true;
    startBtn.disabled = true;
    batchStopBtn.style.display = "inline-block";
    batchActive = true;

    batchPanel.style.display = "block";
    batchDirsList.innerHTML = "";
    batchProgressBar.style.width = "0%";
    batchText.textContent = "正在启动批量处理...";
    batchCurrent.textContent = "";
    logContent.innerHTML = "";

    try {
        const data = await api("/api/batch-start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: modeSelector.value }),
        });
        batchDirs = data.dirs || [];
        renderBatchDirsList(batchDirs);
        batchText.textContent = `0/${batchDirs.length} 目录`;
        addLog(`批量处理已启动：${batchDirs.length} 个目录，${modeSelector.value === "standard" ? "标准" : "文献增强"}模式`, "info");

        connectBatchSSE();
        runStartTime = Date.now();
        startElapsedTimer();
    } catch (e) {
        addLog("批量处理失败：" + e.message, "error");
        finishBatch();
    }
}

function connectBatchSSE() {
    if (eventSource) eventSource.close();
    sseReconnectAttempts = 0;

    eventSource = new EventSource("/api/events/batch");

    eventSource.addEventListener("progress", (e) => {
        sseReconnectAttempts = 0;
        try {
            const evt = JSON.parse(e.data);
            handleEvent(evt);
        } catch {}
    });

    eventSource.addEventListener("ping", () => {
        sseReconnectAttempts = 0;
    });

    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        sseReconnectAttempts++;
        if (sseReconnectAttempts <= SSE_MAX_RECONNECT && batchActive) {
            addLog(`连接断开 — 正在重连（${sseReconnectAttempts}/${SSE_MAX_RECONNECT}）...`, "warning");
            setTimeout(() => { if (batchActive) connectBatchSSE(); }, 2000 * sseReconnectAttempts);
        } else if (batchActive) {
            addLog("连接断开。请刷新页面重新连接。", "error");
        }
    };
}

async function stopBatch() {
    try {
        await api("/api/batch-stop", { method: "POST" });
        addLog("已请求取消批量处理...", "warning");
    } catch (e) {
        addLog("停止批量处理失败：" + e.message, "error");
    }
}

function updateBatchProgress(index, total, dirName) {
    const pct = total > 0 ? (100 * index / total) : 0;
    batchProgressBar.style.width = pct + "%";
    batchText.textContent = `${index}/${total} 目录`;
    batchCurrent.textContent = `当前：${dirName}`;

    const items = batchDirsList.querySelectorAll(".batch-dir-item");
    items.forEach((item, i) => {
        item.classList.remove("active", "completed");
        if (i < index) item.classList.add("completed");
        else if (i === index) item.classList.add("active");
    });
}

function renderBatchDirsList(dirs) {
    batchDirsList.innerHTML = dirs.map(d =>
        `<span class="batch-dir-item">${escapeHtml(d)}</span>`
    ).join("");
}

function finishBatch() {
    batchActive = false;
    batchBtn.disabled = false;
    startBtn.disabled = !currentRunDir;
    batchStopBtn.style.display = "none";
    batchProgressBar.style.width = "100%";
    batchText.textContent = "批量处理完成";
    batchCurrent.textContent = "";
    if (elapsedInterval) clearInterval(elapsedInterval);
    if (eventSource) { eventSource.close(); eventSource = null; }

    const items = batchDirsList.querySelectorAll(".batch-dir-item");
    items.forEach(item => {
        if (!item.classList.contains("completed")) item.classList.add("completed");
    });

    if (currentRunDir) loadResults();
}

// ---- 论文上传 ----

async function refreshPaperCount() {
    if (!currentRunDir) return;
    try {
        const data = await api(`/api/papers/${currentRunDir}`);
        paperCount.textContent = `📄 ${data.count}`;
        paperCount.title = data.papers.slice(0, 10).join("\n") + (data.count > 10 ? `\n...还有 ${data.count - 10} 篇` : "");
    } catch {
        paperCount.textContent = "📄 ?";
    }
}

function handleFileSelect() {
    const files = uploadInput.files;
    if (files.length > 0) uploadFiles(files);
    uploadInput.value = "";
}

function setupDragDrop() {
    let dragCounter = 0;

    document.addEventListener("dragenter", (e) => {
        e.preventDefault();
        dragCounter++;
        if (currentRunDir) dropOverlay.classList.add("show");
    });

    document.addEventListener("dragleave", (e) => {
        e.preventDefault();
        dragCounter--;
        if (dragCounter <= 0) {
            dragCounter = 0;
            dropOverlay.classList.remove("show");
        }
    });

    document.addEventListener("dragover", (e) => {
        e.preventDefault();
    });

    document.addEventListener("drop", (e) => {
        e.preventDefault();
        dragCounter = 0;
        dropOverlay.classList.remove("show");

        if (!currentRunDir) {
            showToast("请先选择运行目录", "warning");
            return;
        }

        const files = e.dataTransfer.files;
        if (files.length > 0) uploadFiles(files);
    });
}

async function uploadFiles(files) {
    const formData = new FormData();
    let validCount = 0;
    const allowedExts = [".pdf", ".md", ".txt", ".docx"];

    for (const file of files) {
        const ext = "." + file.name.split(".").pop().toLowerCase();
        if (allowedExts.includes(ext)) {
            formData.append("files", file);
            validCount++;
        }
    }

    if (validCount === 0) {
        showToast("没有支持的文件（仅支持 PDF、MD、TXT、DOCX）", "warning");
        return;
    }

    showToast(`正在上传 ${validCount} 个文件...`, "info");

    try {
        const res = await fetch(`/api/upload/${currentRunDir}`, {
            method: "POST",
            body: formData,
        });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || "上传失败");

        let msg = `✅ 已上传 ${data.uploaded.length} 个文件`;
        if (data.skipped.length > 0) {
            msg += `，${data.skipped.length} 个跳过`;
        }
        showToast(msg, "success");
        addLog(msg, "success");

        await refreshPaperCount();
    } catch (e) {
        showToast("上传失败：" + e.message, "error");
        addLog("上传失败：" + e.message, "error");
    }
}

function showToast(message, level = "info") {
    uploadToastMsg.textContent = message;
    uploadToast.className = `toast toast-${level}`;
    uploadToast.style.display = "block";

    if (uploadToast._timeout) clearTimeout(uploadToast._timeout);
    uploadToast._timeout = setTimeout(() => {
        uploadToast.style.display = "none";
    }, 3000);
}

// 初始化
document.addEventListener("DOMContentLoaded", init);
