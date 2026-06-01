const state = {
    config: null,
    tasks: { queued: [], processing: [], completed: [], failed: {} },
    status: null,
    currentTab: 'queued',
    logWebSocket: null,
    autoRefresh: null,
    initialized: false,
    recentPage: 1,
    recentSearch: '',
    recentTotal: 0,
    taskPage: 1,
    taskSearch: '',
    taskTotal: 0
};

const el = {};

document.addEventListener('DOMContentLoaded', async () => {
    initThemeOnLoginPage();
    bindLoginEvents();
    const authed = await checkAuthApi();
    if (authed) {
        hideLoginPage();
        initApp();
    } else {
        showLoginPage();
    }
});

function bindLoginEvents() {
    const form = document.getElementById('loginForm');
    if (form) form.addEventListener('submit', handleLogin);
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) logoutBtn.addEventListener('click', handleLogout);
}

async function initApp() {
    if (state.initialized) return;
    state.initialized = true;
    cacheElements();
    bindEvents();
    await loadInitialData();
    startAutoRefresh();
    connectUploadProgressWebSocket();
    initKeyboardShortcuts();
    initMobileMenu();
    initThemeSwitcher();
}

function cacheElements() {
    el.navItems = document.querySelectorAll('.nav-item');
    el.pages = document.querySelectorAll('.page');
    el.statusDot = document.getElementById('statusDot');
    el.statusText = document.getElementById('statusText');
    el.queueCount = document.getElementById('queueCount');
    el.statQueue = document.getElementById('stat-queue');
    el.statProcessing = document.getElementById('stat-processing');
    el.statCompleted = document.getElementById('stat-completed');
    el.statFailed = document.getElementById('stat-failed');
    el.recentActivity = document.getElementById('recent-activity');
    el.taskTabs = document.querySelectorAll('#page-tasks .tab');
    el.taskList = document.getElementById('task-list');
    el.refreshTasksBtn = document.getElementById('refreshTasksBtn');
    el.clearFailedBtn = document.getElementById('clearFailedBtn');
    el.retryAllBtn = document.getElementById('retryAllBtn');
    el.configEditor = document.getElementById('config-editor');
    el.reloadConfigBtn = document.getElementById('reloadConfigBtn');
    el.saveConfigBtn = document.getElementById('saveConfigBtn');
    el.logFileSelect = document.getElementById('logFileSelect');
    el.logViewer = document.getElementById('logViewer');
    el.autoScrollCheck = document.getElementById('autoScrollCheck');
    el.liveLogCheck = document.getElementById('liveLogCheck');
    el.manualFilePath = document.getElementById('manualFilePath');
    el.browseFileBtn = document.getElementById('browseFileBtn');
    el.forceProcessCheck = document.getElementById('forceProcessCheck');
    el.processFileBtn = document.getElementById('processFileBtn');
    el.previewFileBtn = document.getElementById('previewFileBtn');
    el.previewResult = document.getElementById('previewResult');
    el.previewContent = document.getElementById('previewContent');
    el.validateScrapeBtn = document.getElementById('validateScrapeBtn');
    el.validateResult = document.getElementById('validateResult');
    el.validateContent = document.getElementById('validateContent');
    el.scanDirPath = document.getElementById('scanDirPath');
    el.recursiveScanCheck = document.getElementById('recursiveScanCheck');
    el.scanDirBtn = document.getElementById('scanDirBtn');
    el.scanResults = document.getElementById('scanResults');
    el.scannedFilesList = document.getElementById('scannedFilesList');
    el.selectAllFiles = document.getElementById('selectAllFiles');
    el.processSelectedBtn = document.getElementById('processSelectedBtn');
    el.downloaderList = document.getElementById('downloader-list');
    el.refreshDownloadersBtn = document.getElementById('refreshDownloadersBtn');
    el.downloaderConfigList = document.getElementById('downloader-config-list');
    el.addDownloaderConfigBtn = document.getElementById('addDownloaderConfigBtn');
    el.userList = document.getElementById('user-list');
    el.addUserBtn = document.getElementById('addUserBtn');
    el.uploadProgressList = document.getElementById('upload-progress-list');
    el.uploadStatusDot = document.getElementById('uploadStatusDot');
    el.modalOverlay = document.getElementById('modalOverlay');
    el.modalTitle = document.getElementById('modalTitle');
    el.modalBody = document.getElementById('modalBody');
    el.modalClose = document.getElementById('modalClose');
    el.modalCancelBtn = document.getElementById('modalCancelBtn');
    el.modalConfirmBtn = document.getElementById('modalConfirmBtn');
    el.toastContainer = document.getElementById('toastContainer');
    el.recentSearchInput = document.getElementById('recentSearchInput');
    el.recentSearchBtn = document.getElementById('recentSearchBtn');
    el.recentPrevBtn = document.getElementById('recentPrevBtn');
    el.recentNextBtn = document.getElementById('recentNextBtn');
    el.recentPage = document.getElementById('recentPage');
    el.recentTotalPages = document.getElementById('recentTotalPages');
    el.recentTotal = document.getElementById('recentTotal');
    el.recentPagination = document.getElementById('recentPagination');
    el.taskSearchInput = document.getElementById('taskSearchInput');
    el.taskSearchBtn = document.getElementById('taskSearchBtn');
    el.taskPrevBtn = document.getElementById('taskPrevBtn');
    el.taskNextBtn = document.getElementById('taskNextBtn');
    el.taskPage = document.getElementById('taskPage');
    el.taskTotalPages = document.getElementById('taskTotalPages');
    el.taskTotal = document.getElementById('taskTotal');
    el.taskPagination = document.getElementById('taskPagination');
}

function bindEvents() {
    el.navItems.forEach(item => {
        item.addEventListener('click', () => switchPage(item.dataset.page));
    });
    el.taskTabs.forEach(tab => {
        tab.addEventListener('click', () => switchTaskTab(tab.dataset.tab));
    });
    el.refreshTasksBtn.addEventListener('click', loadTasks);
    el.clearFailedBtn.addEventListener('click', () => {
        showConfirm('清除失败记录', '确定要清除所有失败记录吗？此操作不可撤销。', clearAllFailedTasks);
    });
    el.retryAllBtn.addEventListener('click', () => {
        showConfirm('重试全部', '确定要重试所有失败的任务吗？', retryAllFailedTasks);
    });
    el.reloadConfigBtn.addEventListener('click', reloadConfig);
    el.saveConfigBtn.addEventListener('click', saveConfig);
    el.logFileSelect.addEventListener('change', loadLogContent);
    el.liveLogCheck.addEventListener('change', toggleLiveLog);
    el.browseFileBtn.addEventListener('click', browseFile);
    el.processFileBtn.addEventListener('click', processFile);
    el.previewFileBtn.addEventListener('click', previewFile);
    el.scanDirBtn.addEventListener('click', scanDirectory);
    el.validateScrapeBtn.addEventListener('click', validateScrape);
    el.selectAllFiles.addEventListener('change', toggleSelectAllFiles);
    el.processSelectedBtn.addEventListener('click', processSelectedFiles);
    el.refreshDownloadersBtn.addEventListener('click', loadDownloaders);
    if (el.addDownloaderConfigBtn) el.addDownloaderConfigBtn.addEventListener('click', showAddDownloaderModal);
    if (el.addUserBtn) el.addUserBtn.addEventListener('click', showAddUserModal);
    el.modalClose.addEventListener('click', hideModal);
    el.modalCancelBtn.addEventListener('click', hideModal);
    el.modalOverlay.addEventListener('click', (e) => {
        if (e.target === el.modalOverlay) hideModal();
    });
    // 最近活动分页
    if (el.recentPrevBtn) el.recentPrevBtn.addEventListener('click', () => { state.recentPage--; updateRecentActivity(); });
    if (el.recentNextBtn) el.recentNextBtn.addEventListener('click', () => { state.recentPage++; updateRecentActivity(); });
    if (el.recentSearchBtn) el.recentSearchBtn.addEventListener('click', () => {
        state.recentSearch = el.recentSearchInput.value.trim();
        state.recentPage = 1;
        updateRecentActivity();
    });
    if (el.recentSearchInput) el.recentSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            state.recentSearch = el.recentSearchInput.value.trim();
            state.recentPage = 1;
            updateRecentActivity();
        }
    });
    // 任务列表分页与搜索
    if (el.taskPrevBtn) el.taskPrevBtn.addEventListener('click', () => { state.taskPage--; updateTaskList(); });
    if (el.taskNextBtn) el.taskNextBtn.addEventListener('click', () => { state.taskPage++; updateTaskList(); });
    if (el.taskSearchBtn) el.taskSearchBtn.addEventListener('click', () => {
        state.taskSearch = el.taskSearchInput.value.trim();
        state.taskPage = 1;
        updateTaskList();
    });
    if (el.taskSearchInput) el.taskSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            state.taskSearch = el.taskSearchInput.value.trim();
            state.taskPage = 1;
            updateTaskList();
        }
    });
}

function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') hideModal();
        if ((e.ctrlKey || e.metaKey) && e.key === 'r' && document.querySelector('#page-tasks.active')) {
            e.preventDefault();
            loadTasks();
        }
    });
}

function initMobileMenu() {
    const toggle = document.querySelector('.menu-toggle');
    const sidebar = document.querySelector('.sidebar');
    if (toggle && sidebar) {
        toggle.addEventListener('click', () => sidebar.classList.toggle('show'));
        document.addEventListener('click', (e) => {
            if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
                sidebar.classList.remove('show');
            }
        });
    }
}

async function loadInitialData() {
    await Promise.all([loadStatus(), loadConfig(), loadLogFiles(), loadDownloaders(), loadDownloaderConfigs(), loadUsers()]);
    loadTasks();
}

function startAutoRefresh() {
    state.autoRefresh = setInterval(() => {
        loadStatus();
        if (document.querySelector('#page-tasks.active')) loadTasks();
        if (document.querySelector('#page-dashboard.active')) updateRecentActivity();
    }, 5000);
}

function switchPage(pageName) {
    el.navItems.forEach(item => item.classList.toggle('active', item.dataset.page === pageName));
    el.pages.forEach(page => {
        const isActive = page.id === `page-${pageName}`;
        if (isActive) {
            page.classList.remove('active');
            void page.offsetWidth;
        }
        page.classList.toggle('active', isActive);
    });
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) sidebar.classList.remove('show');
    if (pageName === 'downloaders') loadDownloaderConfigs();
    if (pageName === 'users') loadUsers();
}

function switchTaskTab(tabName) {
    state.currentTab = tabName;
    el.taskTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.tab === tabName));
    el.clearFailedBtn.style.display = tabName === 'failed' ? 'inline-flex' : 'none';
    el.retryAllBtn.style.display = tabName === 'failed' ? 'inline-flex' : 'none';
    state.taskPage = 1;
    state.taskSearch = '';
    if (el.taskSearchInput) el.taskSearchInput.value = '';
    updateTaskList();
}

// ===== 状态 =====

async function loadStatus() {
    try {
        state.status = await loadStatusFromApi();
        updateStatusDisplay();
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载状态失败:', e); }
}

function updateStatusDisplay() {
    const s = state.status;
    if (!s) return;
    el.statusDot.className = `status-dot ${s.is_running ? 'running' : 'stopped'}`;
    el.statusText.textContent = s.is_running ? '运行中' : '已停止';
    el.queueCount.textContent = s.queue_size;
    el.statQueue.textContent = s.queue_size;
    el.statProcessing.textContent = s.processing_count;
    el.statCompleted.textContent = s.completed_count;
    el.statFailed.textContent = s.failed_count;
}

// ===== 任务 =====

async function loadTasks() {
    try {
        state.tasks = await loadTasksFromApi();
        updateTaskList();
        updateRecentActivity();
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载任务失败:', e); }
}

async function updateTaskList() {
    const tab = state.currentTab;
    const isLiveTab = tab === 'queued' || tab === 'processing';

    if (isLiveTab) {
        // 实时标签页（队列中/处理中）：使用 state 数据，无分页
        let files = [];
        let statusBadge = '';
        if (tab === 'queued') {
            files = state.tasks.queued.map(f => ({ path: f }));
            statusBadge = '<span class="badge badge-info">队列中</span>';
        } else {
            files = state.tasks.processing.map(f => ({ path: f }));
            statusBadge = '<span class="badge badge-warning">处理中</span>';
        }
        if (files.length === 0) {
            el.taskList.innerHTML = `<tr><td colspan="4"><div class="empty-state"><p>暂无数据</p></div></td></tr>`;
        } else {
            el.taskList.innerHTML = files.map(file => `<tr>
                <td style="font-family:monospace;font-size:0.8125rem">${escapeHtml(file.path)}</td>
                <td>${statusBadge}</td>
                <td style="color:var(--text-muted)">-</td>
                <td></td>
            </tr>`).join('');
        }
        if (el.taskPagination) el.taskPagination.style.display = 'none';
        return;
    }

    // 已完成/失败：使用分页 API
    try {
        const data = await loadTaskListPaginated(state.taskPage, 20, tab === 'failed' ? 'failed' : 'completed', state.taskSearch);
        const items = data.items || [];
        state.taskTotal = data.total || 0;

        if (items.length === 0) {
            el.taskList.innerHTML = `<tr><td colspan="4"><div class="empty-state"><p>暂无数据</p></div></td></tr>`;
        } else {
            const statusBadge = tab === 'completed'
                ? '<span class="badge badge-success">已完成</span>'
                : '<span class="badge badge-danger">失败</span>';
            el.taskList.innerHTML = items.map(file => `<tr>
                <td style="font-family:monospace;font-size:0.8125rem">${escapeHtml(file.path)}</td>
                <td>${statusBadge}${file.error ? `<br><small style="color:var(--accent-danger)">${escapeHtml(file.error)}</small>` : ''}</td>
                <td style="color:var(--text-muted);white-space:nowrap;font-size:0.8125rem">${formatRelativeTime(file.time)}</td>
                <td>${tab === 'failed' ? `<button class="btn btn-primary btn-sm" onclick="retryTask('${escapeHtml(file.path)}')">重试</button>
                    <button class="btn btn-danger btn-sm" onclick="confirmClearFailed('${escapeHtml(file.path)}')">清除</button>` : ''}</td>
            </tr>`).join('');
        }
        updateTaskPagination(data);
    } catch (e) {
        if (!e.message.includes('登录已过期')) {
            el.taskList.innerHTML = `<tr><td colspan="4"><div class="empty-state"><p>加载失败</p></div></td></tr>`;
        }
    }
}

function updateTaskPagination(data) {
    const total = data.total || 0;
    const page = data.page || 1;
    const pageSize = data.page_size || 20;
    const totalPages = Math.ceil(total / pageSize) || 1;
    if (el.taskTotal) el.taskTotal.textContent = total;
    if (el.taskPage) el.taskPage.textContent = page;
    if (el.taskTotalPages) el.taskTotalPages.textContent = totalPages;
    if (el.taskPrevBtn) el.taskPrevBtn.disabled = page <= 1;
    if (el.taskNextBtn) el.taskNextBtn.disabled = page >= totalPages;
    if (el.taskPagination) el.taskPagination.style.display = total > 0 ? 'flex' : 'none';
    state.taskPage = page;
}

function formatRelativeTime(isoTime) {
    if (!isoTime) return '';
    const now = Date.now();
    const then = new Date(isoTime).getTime();
    const diffMs = now - then;
    if (diffMs < 0) return '刚刚';
    const seconds = Math.floor(diffMs / 1000);
    if (seconds < 60) return '刚刚';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}分钟前`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}小时前`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}天前`;
    const months = Math.floor(days / 30);
    if (months < 12) return `${months}个月前`;
    return `${Math.floor(months / 12)}年前`;
}

async function updateRecentActivity() {
    try {
        const data = await loadRecentActivityPaginated(state.recentPage, 20, state.recentSearch);
        const items = data.items || [];
        state.recentTotal = data.total || 0;
        if (items.length === 0) {
            el.recentActivity.innerHTML = `<tr><td colspan="3"><div class="empty-state"><p>暂无数据</p></div></td></tr>`;
        } else {
            el.recentActivity.innerHTML = items.map(t => `<tr>
                <td style="font-family:monospace;font-size:0.8125rem">${escapeHtml(t.path)}</td>
                <td><span class="badge ${t.status === 'completed' ? 'badge-success' : 'badge-danger'}">${t.status === 'completed' ? '已完成' : '失败'}</span></td>
                <td style="color:var(--text-muted);white-space:nowrap">${formatRelativeTime(t.time)}</td>
            </tr>`).join('');
        }
        updateRecentPagination(data);
    } catch (e) {
        if (!e.message.includes('登录已过期')) {
            el.recentActivity.innerHTML = `<tr><td colspan="3"><div class="empty-state"><p>加载失败</p></div></td></tr>`;
        }
    }
}

function updateRecentPagination(data) {
    const total = data.total || 0;
    const page = data.page || 1;
    const pageSize = data.page_size || 20;
    const totalPages = Math.ceil(total / pageSize) || 1;
    if (el.recentTotal) el.recentTotal.textContent = total;
    if (el.recentPage) el.recentPage.textContent = page;
    if (el.recentTotalPages) el.recentTotalPages.textContent = totalPages;
    if (el.recentPrevBtn) el.recentPrevBtn.disabled = page <= 1;
    if (el.recentNextBtn) el.recentNextBtn.disabled = page >= totalPages;
    if (el.recentPagination) el.recentPagination.style.display = total > 0 ? 'flex' : 'none';
    state.recentPage = page;
}

async function retryTask(filePath) {
    try {
        await retryTaskViaApi(filePath);
        showToast('已重试任务', 'success');
        loadTasks();
    } catch (e) { showToast(`重试失败: ${e.message}`, 'error'); }
}

function confirmClearFailed(filePath) {
    showConfirm('清除失败记录', `确定要清除该失败记录吗？`, async () => {
        try {
            await clearFailedTaskViaApi(filePath);
            showToast('已清除失败记录', 'success');
            loadTasks();
        } catch (e) { showToast(`清除失败: ${e.message}`, 'error'); }
    });
}

async function clearAllFailedTasks() {
    try {
        await clearAllFailedViaApi();
        showToast('已清除所有失败记录', 'success');
        loadTasks();
    } catch (e) { showToast(`清除失败: ${e.message}`, 'error'); }
}

async function retryAllFailedTasks() {
    try {
        const result = await retryAllFailedViaApi();
        showToast(`已重试 ${result.retried_count} 个任务`, 'success');
        loadTasks();
    } catch (e) { showToast(`重试失败: ${e.message}`, 'error'); }
}

// ===== 配置 =====

let _configCurrentSection = 'monitoring';
let _dbManualRules = [];
let _dbReleaseGroups = [];
let _dbLlmProviders = [];
let _dbRuntimeConfig = [];

async function loadConfig() {
    try {
        state.config = await loadConfigFromApi();
        await loadDbConfigs();
        renderConfigEditor();
    setupConfigNav();
    setupConfigSearch();
    updateConfigBadges();
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载配置失败:', e); }
}

async function loadDbConfigs() {
    try {
        const [mr, rg, lp, rt] = await Promise.all([
            loadManualRulesFromApi(),
            loadReleaseGroupsFromApi(),
            loadLlmProvidersFromApi(),
            loadRuntimeConfigFromApi(),
        ]);
        _dbManualRules = mr.rules || [];
        _dbReleaseGroups = rg.groups || [];
        _dbLlmProviders = lp.providers || [];
        _dbRuntimeConfig = rt.configs || [];
        updateConfigBadges();
    } catch (e) { console.error('加载数据库配置失败:', e); }
}

function updateConfigBadges() {
    const mr = document.getElementById('mrCount');
    const rg = document.getElementById('rgCount');
    const lp = document.getElementById('lpCount');
    const rt = document.getElementById('rtCount');
    if (mr) mr.textContent = _dbManualRules.length;
    if (rg) rg.textContent = _dbReleaseGroups.length;
    if (lp) lp.textContent = _dbLlmProviders.length;
    if (rt) rt.textContent = _dbRuntimeConfig.length;
}

function setupConfigNav() {
    document.querySelectorAll('.cnav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.cnav-item').forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            _configCurrentSection = item.dataset.section;
            renderConfigEditor();
        });
    });
}

function setupConfigSearch() {
    const input = document.getElementById('configSearchInput');
    if (!input) return;
    input.addEventListener('input', () => {
        const q = input.value.toLowerCase().trim();
        if (!q) {
            document.querySelectorAll('.config-field').forEach(f => f.style.display = '');
            return;
        }
        document.querySelectorAll('.config-field').forEach(f => {
            const label = f.querySelector('.config-field-label')?.textContent?.toLowerCase() || '';
            f.style.display = label.includes(q) ? '' : 'none';
        });
    });
}

function renderConfigEditor() {
    const section = _configCurrentSection;
    if (section.startsWith('__')) {
        renderDbConfigEditor(section);
        return;
    }
    renderIniConfigEditor(section);
}

function renderIniConfigEditor(section) {
    const config = state.config;
    if (!config || !config[section]) {
        el.configEditor.innerHTML = '<div class="config-empty"><span class="empty-icon">⌀</span><span>该配置节无数据</span></div>';
        return;
    }

    let html = `<div class="config-section"><div class="config-section-title">${getSectionLabel(section)}</div><div class="config-grid">`;
    for (const [k, v] of Object.entries(config[section])) {
        html += renderConfigField(section, k, v);
    }
    html += `</div></div>`;
    el.configEditor.innerHTML = html;

    document.querySelectorAll('#config-editor .toggle-track').forEach(track => {
        track.addEventListener('click', () => {
            const cb = document.getElementById(track.dataset.for);
            if (!cb) return;
            cb.checked = !cb.checked;
            track.classList.toggle('on', cb.checked);
            const label = document.getElementById(`${cb.id}-label`);
            if (label) label.textContent = cb.checked ? '是' : '否';
        });
    });
}

function getSectionLabel(section) {
    const labels = {
        'monitoring': '监控配置', 'tmdb': 'TMDB 配置', 'naming': '命名规则',
        'processing': '处理配置', 'logging': '日志配置',
        'p123': '123云盘', 'cloud189': '天翼云盘', 'yun139': '139云盘',
        'emos': 'Emby 云盘', 'telegram': 'Telegram', 'guessit': 'GuessIt 解析',
        'emya_db': 'Emby 数据库', 'downloaders': '下载器列表',
    };
    return labels[section] || section;
}

function renderConfigField(section, key, value) {
    const inputId = `cfg-${section}-${key}`;
    const inputName = `${section}.${key}`;
    const isSecret = ['password','token','secret','api_key','apikey'].some(s => key.toLowerCase().includes(s));

    let inputHtml;
    if (typeof value === 'boolean') {
        inputHtml = `<div class="toggle-wrap">
            <div class="toggle-track ${value ? 'on' : ''}" data-for="${inputId}">
                <div class="toggle-thumb"></div>
            </div>
            <input type="checkbox" id="${inputId}" name="${inputName}" ${value ? 'checked' : ''} style="display:none">
            <span class="toggle-label" id="${inputId}-label">${value ? '启用' : '禁用'}</span>
        </div>`;
    } else if (Array.isArray(value)) {
        inputHtml = `<input type="text" id="${inputId}" name="${inputName}" value="${escapeHtml(value.join(', '))}">`;
    } else if (typeof value === 'object' && value !== null) {
        inputHtml = `<textarea id="${inputId}" name="${inputName}">${escapeHtml(JSON.stringify(value, null, 2))}</textarea>`;
    } else if (isSecret) {
        inputHtml = `<input type="password" id="${inputId}" name="${inputName}" value="${escapeHtml(String(value))}" spellcheck="false">`;
    } else {
        inputHtml = `<input type="text" id="${inputId}" name="${inputName}" value="${escapeHtml(String(value))}" spellcheck="false">`;
    }

    return `<div class="config-field">
        <div class="config-field-label">${escapeHtml(key)} <code>${section}.${key}</code></div>
        ${inputHtml}
    </div>`;
}

function renderDbConfigEditor(section) {
    switch (section) {
        case '__manual_rules': return renderManualRules();
        case '__release_groups': return renderReleaseGroups();
        case '__llm_providers': return renderLlmProviders();
        case '__runtime': return renderRuntimeConfig();
    }
}

// ===== 手动规则 =====

function renderManualRules() {
    const rules = _dbManualRules;
    let html = `<div class="config-section"><div class="config-section-title">手动规则</div>`;
    if (rules.length === 0) {
        html += `<div class="config-empty"><span class="empty-icon">⌀</span><span>暂无规则</span></div>`;
    } else {
        html += `<div class="config-table-wrap"><table class="config-table">
            <thead><tr><th style="width:36px">#</th><th>规则内容</th><th style="width:60px">启用</th><th style="width:140px">操作</th></tr></thead><tbody>`;
        rules.forEach((r, i) => {
            html += `<tr>
                <td style="color:var(--text-muted);font-size:0.75rem">${i + 1}</td>
                <td><input type="text" class="mr-text" data-id="${r.id}" value="${escapeHtml(r.rule_text)}" style="font-family:monospace"></td>
                <td><input type="checkbox" class="mr-enabled" data-id="${r.id}" ${r.enabled ? 'checked' : ''} style="width:auto"></td>
                <td><div class="btn-cell">
                    <button class="save-btn" onclick="saveManualRule(${r.id})">保存</button>
                    <button class="del-btn" onclick="deleteManualRule(${r.id})">删除</button>
                </div></td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
    }
    html += `<div class="add-row-bar">
        <input type="text" id="newMrText" placeholder="新规则内容..." style="flex:1;font-family:monospace">
        <button class="add-btn" onclick="addManualRule()">+ 添加</button>
    </div></div>`;
    el.configEditor.innerHTML = html;
}

async function addManualRule() {
    const input = document.getElementById('newMrText');
    const text = input?.value.trim();
    if (!text) return showToast('请输入规则内容', 'warning');
    try {
        await createManualRuleViaApi({ rule_text: text, enabled: true, sort_order: _dbManualRules.length });
        showToast('规则已添加', 'success');
        await loadDbConfigs();
        renderManualRules();
    } catch (e) { showToast(`添加失败: ${e.message}`, 'error'); }
}

window.addManualRule = addManualRule;

async function saveManualRule(id) {
    const textInput = document.querySelector(`.mr-text[data-id="${id}"]`);
    const enabledInput = document.querySelector(`.mr-enabled[data-id="${id}"]`);
    if (!textInput) return;
    try {
        await updateManualRuleViaApi(id, {
            rule_text: textInput.value,
            enabled: enabledInput?.checked ?? true,
            sort_order: 0,
        });
        showToast('规则已保存', 'success');
        await loadDbConfigs();
        renderManualRules();
    } catch (e) { showToast(`保存失败: ${e.message}`, 'error'); }
}

window.saveManualRule = saveManualRule;

async function deleteManualRule(id) {
    if (!confirm('确定删除此规则？')) return;
    try {
        await deleteManualRuleViaApi(id);
        showToast('规则已删除', 'success');
        await loadDbConfigs();
        renderManualRules();
    } catch (e) { showToast(`删除失败: ${e.message}`, 'error'); }
}

window.deleteManualRule = deleteManualRule;

// ===== 字幕组映射 =====

function renderReleaseGroups() {
    const groups = _dbReleaseGroups;
    let html = `<div class="config-section"><div class="config-section-title">字幕组映射</div>`;
    if (groups.length === 0) {
        html += `<div class="config-empty"><span class="empty-icon">⌀</span><span>暂无映射</span></div>`;
    } else {
        html += `<div class="config-table-wrap"><table class="config-table">
            <thead><tr><th>字幕组名称</th><th>类型</th><th style="width:140px">操作</th></tr></thead><tbody>`;
        groups.forEach(g => {
            html += `<tr>
                <td><input type="text" class="rg-name" data-id="${g.id}" value="${escapeHtml(g.group_name)}"></td>
                <td><select class="rg-type" data-id="${g.id}">
                    <option value="anime" ${g.content_type === 'anime' ? 'selected' : ''}>动画</option>
                    <option value="drama" ${g.content_type === 'drama' ? 'selected' : ''}>剧集</option>
                    <option value="movie" ${g.content_type === 'movie' ? 'selected' : ''}>电影</option>
                </select></td>
                <td><div class="btn-cell">
                    <button class="save-btn" onclick="saveReleaseGroup(${g.id})">保存</button>
                    <button class="del-btn" onclick="deleteReleaseGroup(${g.id})">删除</button>
                </div></td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
    }
    html += `<div class="add-row-bar">
        <input type="text" id="newRgName" placeholder="字幕组名称..." style="flex:1">
        <select id="newRgType">
            <option value="anime">动画</option>
            <option value="drama">剧集</option>
            <option value="movie">电影</option>
        </select>
        <button class="add-btn" onclick="addReleaseGroup()">+ 添加</button>
    </div></div>`;
    el.configEditor.innerHTML = html;
}

async function addReleaseGroup() {
    const name = document.getElementById('newRgName')?.value.trim();
    const type = document.getElementById('newRgType')?.value;
    if (!name) return showToast('请输入字幕组名称', 'warning');
    try {
        await createReleaseGroupViaApi({ group_name: name, content_type: type });
        showToast('映射已添加', 'success');
        await loadDbConfigs();
        renderReleaseGroups();
    } catch (e) { showToast(`添加失败: ${e.message}`, 'error'); }
}

window.addReleaseGroup = addReleaseGroup;

async function saveReleaseGroup(id) {
    const nameInput = document.querySelector(`.rg-name[data-id="${id}"]`);
    const typeSelect = document.querySelector(`.rg-type[data-id="${id}"]`);
    if (!nameInput) return;
    try {
        await updateReleaseGroupViaApi(id, {
            group_name: nameInput.value,
            content_type: typeSelect.value,
        });
        showToast('映射已保存', 'success');
        await loadDbConfigs();
        renderReleaseGroups();
    } catch (e) { showToast(`保存失败: ${e.message}`, 'error'); }
}

window.saveReleaseGroup = saveReleaseGroup;

async function deleteReleaseGroup(id) {
    if (!confirm('确定删除此映射？')) return;
    try {
        await deleteReleaseGroupViaApi(id);
        showToast('映射已删除', 'success');
        await loadDbConfigs();
        renderReleaseGroups();
    } catch (e) { showToast(`删除失败: ${e.message}`, 'error'); }
}

window.deleteReleaseGroup = deleteReleaseGroup;

// ===== LLM 提供商 =====

function renderLlmProviders() {
    const providers = _dbLlmProviders;
    let html = `<div class="config-section"><div class="config-section-title">LLM 提供商</div>`;
    if (providers.length === 0) {
        html += `<div class="config-empty"><span class="empty-icon">⌀</span><span>暂无提供商</span></div>`;
    } else {
        html += `<div class="config-table-wrap"><table class="config-table">
            <thead><tr><th>名称</th><th>API URL</th><th>API Key</th><th>模型</th><th>权重</th><th>超时</th><th>启用</th><th style="width:110px">操作</th></tr></thead><tbody>`;
        providers.forEach(p => {
            const keyPlaceholder = p.has_key ? '已设置，留空不变' : '未设置';
            html += `<tr>
                <td><input class="lp-name" data-id="${p.id}" value="${escapeHtml(p.name)}" style="width:80px"></td>
                <td><input class="lp-url" data-id="${p.id}" value="${escapeHtml(p.api_url)}" style="width:160px;font-family:monospace"></td>
                <td><input class="lp-apikey" data-id="${p.id}" value="" placeholder="${keyPlaceholder}" type="password" style="width:110px"></td>
                <td><input class="lp-model" data-id="${p.id}" value="${escapeHtml(p.model || '')}" style="width:100px"></td>
                <td><input class="lp-weight" data-id="${p.id}" value="${p.weight}" type="number" min="0" style="width:48px"></td>
                <td><input class="lp-timeout" data-id="${p.id}" value="${p.timeout}" type="number" min="1" style="width:48px"></td>
                <td><input class="lp-enabled" data-id="${p.id}" type="checkbox" ${p.enabled ? 'checked' : ''} style="width:auto"></td>
                <td><div class="btn-cell">
                    <button class="save-btn" onclick="saveLlmProvider(${p.id})">保存</button>
                    <button class="del-btn" onclick="deleteLlmProvider(${p.id})">删除</button>
                </div></td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
    }
    html += `<div class="add-row-bar" style="flex-wrap:wrap">
        <input type="text" id="newLpName" placeholder="名称..." style="width:100px">
        <input type="text" id="newLpUrl" placeholder="API URL..." style="width:180px;font-family:monospace">
        <input type="password" id="newLpApiKey" placeholder="API Key..." style="width:130px">
        <input type="text" id="newLpModel" placeholder="模型..." style="width:100px">
        <button class="add-btn" onclick="addLlmProvider()">+ 添加</button>
    </div></div>`;
    el.configEditor.innerHTML = html;
}

async function addLlmProvider() {
    const name = document.getElementById('newLpName')?.value.trim();
    const url = document.getElementById('newLpUrl')?.value.trim();
    const key = document.getElementById('newLpApiKey')?.value.trim();
    if (!name || !url) return showToast('请填写名称和 API URL', 'warning');
    try {
        await createLlmProviderViaApi({ name, api_url: url, api_key: key || '', model: document.getElementById('newLpModel')?.value.trim() || '' });
        showToast('提供商已添加', 'success');
        await loadDbConfigs();
        renderLlmProviders();
    } catch (e) { showToast(`添加失败: ${e.message}`, 'error'); }
}

window.addLlmProvider = addLlmProvider;

async function saveLlmProvider(id) {
    const g = (cls) => document.querySelector(`.${cls}[data-id="${id}"]`);
    try {
        await updateLlmProviderViaApi(id, {
            name: g('lp-name')?.value || '',
            api_url: g('lp-url')?.value || '',
            api_key: g('lp-apikey')?.value || '',
            model: g('lp-model')?.value || '',
            enabled: g('lp-enabled')?.checked ?? true,
            weight: parseInt(g('lp-weight')?.value) || 1,
            timeout: parseInt(g('lp-timeout')?.value) || 30,
            max_retries: 2,
        });
        showToast('提供商已保存', 'success');
        await loadDbConfigs();
        renderLlmProviders();
    } catch (e) { showToast(`保存失败: ${e.message}`, 'error'); }
}

window.saveLlmProvider = saveLlmProvider;

async function deleteLlmProvider(id) {
    if (!confirm('确定删除此提供商？')) return;
    try {
        await deleteLlmProviderViaApi(id);
        showToast('提供商已删除', 'success');
        await loadDbConfigs();
        renderLlmProviders();
    } catch (e) { showToast(`删除失败: ${e.message}`, 'error'); }
}

window.deleteLlmProvider = deleteLlmProvider;

// ===== 运行时配置 =====

function renderRuntimeConfig() {
    const configs = _dbRuntimeConfig;
    let html = `<div class="config-section"><div class="config-section-title">运行时配置</div>`;
    if (configs.length === 0) {
        html += `<div class="config-empty"><span class="empty-icon">⌀</span><span>暂无配置项</span></div>`;
    } else {
        html += `<div class="config-table-wrap"><table class="config-table">
            <thead><tr><th>配置键</th><th>值</th><th>说明</th><th style="width:90px">操作</th></tr></thead><tbody>`;
        configs.forEach(c => {
            html += `<tr>
                <td style="font-family:monospace;font-size:0.75rem;color:var(--text-muted)">${escapeHtml(c.key)}</td>
                <td><input class="rt-value" data-key="${escapeHtml(c.key)}" value="${escapeHtml(c.value || '')}" style="font-family:monospace"></td>
                <td style="font-size:0.75rem;color:var(--text-muted)">${escapeHtml(c.description || '')}</td>
                <td><div class="btn-cell"><button class="save-btn" onclick="saveRuntimeConfig('${escapeHtml(c.key)}')">保存</button></div></td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
    }
    html += `</div>`;
    el.configEditor.innerHTML = html;
}

async function saveRuntimeConfig(key) {
    const input = document.querySelector(`.rt-value[data-key="${CSS.escape(key)}"]`);
    if (!input) return;
    try {
        await updateRuntimeConfigViaApi(key, { value: input.value });
        showToast('配置已保存', 'success');
        await loadDbConfigs();
        renderRuntimeConfig();
    } catch (e) { showToast(`保存失败: ${e.message}`, 'error'); }
}

window.saveRuntimeConfig = saveRuntimeConfig;

// ===== 保存 / 重新加载 INI 配置 =====

async function reloadConfig() {
    try {
        await reloadConfigViaApi();
        await loadConfig();
        showToast('配置已重新加载', 'success');
    } catch (e) { showToast(`重新加载失败: ${e.message}`, 'error'); }
}

async function saveConfig() {
    const inputs = el.configEditor.querySelectorAll('[name]');
    const sections = {};

    inputs.forEach(input => {
        const [section, ...keyParts] = input.name.split('.');
        const key = keyParts.join('.');
        if (!sections[section]) sections[section] = {};
        let value = input.value;
        if (input.type === 'checkbox') {
            value = input.checked;
        } else if (!isNaN(Number(value)) && value.trim() !== '') {
            const num = Number(value);
            if (Number.isFinite(num)) value = num;
        }
        sections[section][key] = value;
    });

    let successCount = 0;
    let failCount = 0;
    for (const [section, data] of Object.entries(sections)) {
        try {
            const current = state.config[section] || {};
            const changed = {};
            for (const k of Object.keys(data)) {
                if (JSON.stringify(data[k]) !== JSON.stringify(current[k])) {
                    changed[k] = data[k];
                }
            }
            if (Object.keys(changed).length === 0) { successCount++; continue; }
            await saveConfigToApi(section, changed);
            await loadConfig();
            successCount++;
        } catch (e) {
            console.error(`保存配置节 ${section} 失败:`, e);
            failCount++;
        }
    }

    if (failCount === 0) {
        showToast(`配置已保存（${successCount} 节）`, 'success');
    } else {
        showToast(`保存完成: ${successCount} 节成功, ${failCount} 节失败`, 'warning');
    }
}

// ===== 日志 =====

async function loadLogFiles() {
    try {
        const result = await loadLogFilesFromApi();
        el.logFileSelect.innerHTML = '<option value="">选择日志文件</option>' +
            (result.files || []).map(f => `<option value="${f}">${f}</option>`).join('');
        if (result.current) {
            el.logFileSelect.value = result.current;
            loadLogContent();
        }
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载日志文件列表失败:', e); }
}

async function loadLogContent() {
    const filename = el.logFileSelect.value;
    if (!filename) return;
    try {
        const text = await loadLogContentFromApi(filename);
        el.logViewer.innerHTML = text.split('\n').map(line =>
            `<div class="${classifyLogLine(line)}">${escapeHtml(line)}</div>`
        ).join('');
        if (el.autoScrollCheck.checked) el.logViewer.scrollTop = el.logViewer.scrollHeight;
    } catch (e) { showToast(`加载日志失败: ${e.message}`, 'error'); }
}

function toggleLiveLog() {
    const filename = el.logFileSelect.value;
    if (!filename) return;
    if (el.liveLogCheck.checked) startLiveLog(filename);
    else stopLiveLog();
}

function startLiveLog(filename) {
    const token = getAuthToken();
    const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/logs/ws/${encodeURIComponent(filename)}`;
    state.logWebSocket = new WebSocket(wsUrl);
    state.logWebSocket.onopen = () => {
        if (token) state.logWebSocket.send(JSON.stringify({ type: 'auth', token }));
    };
    state.logWebSocket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'log') {
            el.logViewer.innerHTML += `<div class="${classifyLogLine(data.content)}">${escapeHtml(data.content)}</div>`;
            if (el.autoScrollCheck.checked) el.logViewer.scrollTop = el.logViewer.scrollHeight;
        }
    };
    state.logWebSocket.onerror = () => {
        showToast('WebSocket 连接失败', 'error');
        el.liveLogCheck.checked = false;
    };
    state.logWebSocket.onclose = () => { state.logWebSocket = null; };
}

function stopLiveLog() {
    if (state.logWebSocket) { state.logWebSocket.close(); state.logWebSocket = null; }
}

// ===== 手动处理 =====

async function browseFile() {
    try {
        const result = await browsePathFromApi(el.manualFilePath.value);
        showBrowseModal(result);
    } catch (e) { showToast(`浏览失败: ${e.message}`, 'error'); }
}

function showBrowseModal(data) {
    const titleEl = document.getElementById('modalTitle');
    if (titleEl) titleEl.textContent = '选择文件';

    let html = `<div class="file-browser"><div class="file-browser-header">
        ${data.parent ? `<button class="btn btn-secondary btn-sm" data-path="${escapeHtml(data.parent)}" data-type="parent">..</button>` : ''}
        <div class="file-browser-path">${escapeHtml(data.path) || '根目录'}</div>
    </div><div class="file-list">`;

    (data.directories || []).forEach(dir => {
        const fullPath = data.path ? `${data.path}\\${dir}` : dir;
        html += `<div class="file-item" data-path="${escapeHtml(fullPath)}" data-type="dir">
            <svg class="file-icon folder" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4a2 2 0 00-2 2v12a2 2 0 002 2h16a2 2 0 002-2V8a2 2 0 00-2-2h-8l-2-2z"/></svg>
            <span>${escapeHtml(dir)}</span>
        </div>`;
    });

    (data.files || []).forEach(file => {
        const isVideo = ['.mp4','.mkv','.avi','.mov','.wmv','.flv'].includes(file.extension);
        const fullPath = data.path ? `${data.path}\\${file.name}` : file.name;
        html += `<div class="file-item" data-path="${escapeHtml(fullPath)}" data-type="file">
            <svg class="file-icon ${isVideo ? 'video' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/>
            </svg>
            <span>${escapeHtml(file.name)}</span>
            <small style="color:var(--text-muted);margin-left:auto">${formatSize(file.size)}</small>
        </div>`;
    });

    html += '</div></div>';
    const body = document.getElementById('modalBody');
    if (body) {
        body.innerHTML = html;
        const fileList = body.querySelector('.file-list');
        if (fileList) {
            fileList.addEventListener('click', onFileListClick);
        }
        const parentBtn = body.querySelector('[data-type="parent"]');
        if (parentBtn) {
            parentBtn.addEventListener('click', () => browsePath(parentBtn.dataset.path));
        }
    }
    const footer = document.getElementById('modalFooter');
    if (footer) footer.style.display = 'none';
    showModal();
}

function onFileListClick(e) {
    const item = e.target.closest('.file-item');
    if (!item || !item.dataset.path) return;
    const path = item.dataset.path;
    if (item.dataset.type === 'dir') {
        browsePath(path);
    } else {
        selectFile(path);
    }
}

async function browsePath(path) {
    try {
        const result = await browsePathFromApi(path);
        showBrowseModal(result);
    } catch (e) { showToast(`浏览失败: ${e.message}`, 'error'); }
}

function selectFile(path) {
    el.manualFilePath.value = path;
    hideModal();
}

async function processFile() {
    const filePath = el.manualFilePath.value.trim();
    if (!filePath) { showToast('请输入文件路径', 'warning'); return; }
    setButtonLoading(el.processFileBtn, true);
    try {
        const result = await processFileViaApi(filePath, el.forceProcessCheck.checked);
        showToast(result.message, result.success ? 'success' : 'warning');
        if (result.success) { el.manualFilePath.value = ''; loadTasks(); }
    } catch (e) { showToast(`处理失败: ${e.message}`, 'error'); }
    finally { setButtonLoading(el.processFileBtn, false); }
}

async function previewFile() {
    const filePath = el.manualFilePath.value.trim();
    if (!filePath) { showToast('请输入文件路径', 'warning'); return; }
    setButtonLoading(el.previewFileBtn, true);
    try {
        const result = await previewFileViaApi(filePath);
        if (result.success) {
            el.previewResult.style.display = 'block';
            el.previewContent.innerHTML = `
                <div class="form-group"><label class="form-label">原始名称</label>
                    <div style="font-family:monospace">${escapeHtml(result.original_name)}</div></div>
                <div class="form-group"><label class="form-label">建议名称</label>
                    <div style="font-family:monospace;color:var(--accent-primary)">${escapeHtml(result.suggested_name || '无法生成')}</div></div>
                <div class="form-group"><label class="form-label">媒体类型</label>
                    <span class="badge badge-info">${result.media_type || '未知'}</span></div>
                <div class="form-group"><label class="form-label">元数据</label>
                    <pre style="background:var(--bg-primary);padding:12px;border-radius:8px;overflow-x:auto">${JSON.stringify(result.metadata, null, 2)}</pre></div>`;
        } else {
            el.previewResult.style.display = 'block';
            el.previewContent.innerHTML = `<div style="color:var(--accent-danger)">${escapeHtml(result.error)}</div>`;
        }
    } catch (e) { showToast(`预览失败: ${e.message}`, 'error'); }
    finally { setButtonLoading(el.previewFileBtn, false); }
}

async function validateScrape() {
    const filePath = el.manualFilePath.value.trim();
    if (!filePath) { showToast('请输入文件路径', 'warning'); return; }
    setButtonLoading(el.validateScrapeBtn, true);
    el.validateResult.style.display = 'none';
    try {
        const result = await validateScrapeViaApi(filePath);
        el.validateResult.style.display = 'block';
        if (result.success) {
            const icon = result.tmdb_matched ? '✅' : '❌';
            const typeLabel = { tv: '电视剧', movie: '电影' }[result.media_type] || result.media_type || '未知';
            el.validateContent.innerHTML = `
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                    <div class="form-group"><label class="form-label">原始文件名</label>
                        <div style="font-family:monospace;word-break:break-all">${escapeHtml(result.original_name)}</div></div>
                    <div class="form-group"><label class="form-label">识别标题</label>
                        <div style="font-size:16px;font-weight:600">${icon} ${escapeHtml(result.title || '未能识别')}</div></div>
                    <div class="form-group"><label class="form-label">年份</label>
                        <div>${result.year || '-'}</div></div>
                    <div class="form-group"><label class="form-label">媒体类型</label>
                        <span class="badge badge-info">${typeLabel}</span></div>
                    ${result.season ? `<div class="form-group"><label class="form-label">季</label><div>${result.season}</div></div>` : ''}
                    ${result.episode ? `<div class="form-group"><label class="form-label">集</label><div>${result.episode}</div></div>` : ''}
                    ${result.episode_title ? `<div class="form-group" style="grid-column:1/-1"><label class="form-label">集标题</label><div>${escapeHtml(result.episode_title)}</div></div>` : ''}
                    ${result.quality_tags ? `<div class="form-group"><label class="form-label">质量标签</label><div>${escapeHtml(result.quality_tags)}</div></div>` : ''}
                    ${result.release_group ? `<div class="form-group"><label class="form-label">发布组</label><div>${escapeHtml(result.release_group)}</div></div>` : ''}
                    <div class="form-group"><label class="form-label">TMDB刮削</label>
                        <span class="badge ${result.tmdb_matched ? 'badge-success' : 'badge-danger'}">${result.tmdb_matched ? '成功' : '失败'}</span></div>
                    ${result.confidence ? `<div class="form-group"><label class="form-label">匹配分数</label><div>${(result.confidence * 100).toFixed(1)}%</div></div>` : ''}
                    ${result.suggested_name ? `<div class="form-group" style="grid-column:1/-1">
                        <label class="form-label">建议命名</label>
                        <div style="font-family:monospace;color:var(--accent-primary);word-break:break-all">${escapeHtml(result.suggested_name)}</div></div>` : ''}
                    ${result.suggested_path ? `<div class="form-group" style="grid-column:1/-1">
                        <label class="form-label">建议路径</label>
                        <div style="font-family:monospace;color:var(--text-muted);font-size:13px;word-break:break-all">${escapeHtml(result.suggested_path)}</div></div>` : ''}
                </div>
                ${result.tmdb_info ? `
                <div style="margin-top:16px;padding:12px;background:var(--bg-primary);border-radius:8px">
                    <div style="font-weight:600;margin-bottom:8px">TMDB 匹配详情</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px">
                        <div><label style="color:var(--text-muted)">ID</label><div>${result.tmdb_info.id}</div></div>
                        <div><label style="color:var(--text-muted)">原始标题</label><div>${escapeHtml(result.tmdb_info.original_title || '-')}</div></div>
                        <div style="grid-column:1/-1"><label style="color:var(--text-muted)">简介</label>
                            <div>${escapeHtml(result.tmdb_info.overview || '暂无')}</div></div>
                    </div>
                </div>` : ''}`;
        } else {
            el.validateContent.innerHTML = `<div style="color:var(--accent-danger)">${escapeHtml(result.error)}</div>`;
        }
    } catch (e) { showToast(`验证失败: ${e.message}`, 'error'); }
    finally { setButtonLoading(el.validateScrapeBtn, false); }
}

async function scanDirectory() {
    const dirPath = el.scanDirPath.value.trim();
    if (!dirPath) { showToast('请输入目录路径', 'warning'); return; }
    setButtonLoading(el.scanDirBtn, true);
    try {
        const result = await scanDirectoryViaApi(dirPath, el.recursiveScanCheck.checked);
        if (!result.files || result.files.length === 0) {
            showToast('未找到视频文件', 'warning');
            el.scanResults.style.display = 'none';
            return;
        }
        el.scanResults.style.display = 'block';
        el.scannedFilesList.innerHTML = result.files.map((file, i) =>
            `<tr><td><input type="checkbox" class="file-checkbox" data-path="${escapeHtml(file)}"></td>
            <td>${escapeHtml(new Path(file).basename || file)}</td><td>-</td></tr>`
        ).join('');
        showToast(`找到 ${result.files.length} 个视频文件`, 'success');
    } catch (e) { showToast(`扫描失败: ${e.message}`, 'error'); }
    finally { setButtonLoading(el.scanDirBtn, false); }
}

function toggleSelectAllFiles() {
    document.querySelectorAll('.file-checkbox').forEach(cb => cb.checked = el.selectAllFiles.checked);
}

async function processSelectedFiles() {
    const checked = document.querySelectorAll('.file-checkbox:checked');
    if (checked.length === 0) { showToast('请选择要处理的文件', 'warning'); return; }
    const files = Array.from(checked).map(cb => cb.dataset.path);
    setButtonLoading(el.processSelectedBtn, true);
    try {
        const result = await processBatchViaApi(files);
        showToast(result.message, 'success');
        loadTasks();
    } catch (e) { showToast(`批量处理失败: ${e.message}`, 'error'); }
    finally { setButtonLoading(el.processSelectedBtn, false); }
}

// ===== 下载器 =====

async function loadDownloaders() {
    try {
        const result = await loadDownloadersFromApi();
        const config = await loadConfigFromApi();
        const nameMap = {};
        if (config) {
            Object.keys(config)
                .filter(k => k.startsWith('downloader.'))
                .forEach(k => {
                    const sec = config[k];
                    const type = sec.type || k.replace('downloader.', '');
                    if (sec.name) nameMap[type] = sec.name;
                });
        }
        if (!result.downloaders || result.downloaders.length === 0) {
            el.downloaderList.innerHTML = `<tr><td colspan="3"><div class="empty-state"><p>暂无下载器</p></div></td></tr>`;
            return;
        }
        el.downloaderList.innerHTML = result.downloaders.map(d => `<tr>
            <td>${escapeHtml(nameMap[d.type] || d.name)}</td>
            <td>${escapeHtml(d.type)}</td>
            <td><span class="badge ${d.connected ? 'badge-success' : 'badge-danger'}">${d.connected ? '已连接' : '未连接'}</span></td>
        </tr>`).join('');
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载下载器失败:', e); }
    try {
        await loadDownloaderConfigs();
    } catch (e) { /* ignore */ }
}

// ===== 下载器配置管理（INI 中的 downloader.* 节）=====

async function loadDownloaderConfigs() {
    try {
        const config = await loadConfigFromApi();
        const downloaders = Object.keys(config || {})
            .filter(k => k.startsWith('downloader.'))
            .map(k => ({ section: k, type: k.replace('downloader.', ''), ...config[k] }));
        renderDownloaderConfigs(downloaders);
    } catch (e) {
        if (!e.message.includes('登录已过期')) console.error('加载下载器配置失败:', e);
    }
}

const RPC_PATHS = { aria2:'/jsonrpc', qbittorrent:'/api/v2', transmission:'/transmission/rpc', rtorrent:'/RPC2', deluge:'/json' };

function renderDownloaderConfigs(downloaders) {
    if (!downloaders.length) {
        el.downloaderConfigList.innerHTML = `<tr><td colspan="7"><div class="empty-state"><p>暂无配置</p></div></td></tr>`;
        return;
    }
    el.downloaderConfigList.innerHTML = downloaders.map(d => {
        const name = d.name || d.type || d.section.replace('downloader.', '');
        const type = d.type || d.section.replace('downloader.', '');
        const host = d.host || '-';
        const port = d.port || '-';
        const user = d.username || '-';
        const rpc = d.rpc_url || (host !== '-' && port !== '-' ? `http://${host}:${port}${RPC_PATHS[type] || ''}` : '-');
        return `<tr>
            <td><strong>${escapeHtml(name)}</strong></td>
            <td>${escapeHtml(type)}</td>
            <td>${escapeHtml(host)}</td>
            <td>${escapeHtml(port)}</td>
            <td>${escapeHtml(user)}</td>
            <td style="font-size:0.75rem;font-family:monospace;max-width:220px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(rpc)}</td>
            <td><div class="btn-cell">
                <button class="save-btn" onclick='editDownloaderConfig(${JSON.stringify(d).replace(/'/g,"&#39;")})'>编辑</button>
                <button class="del-btn" onclick="deleteDownloaderConfig('${escapeHtml(d.section)}')">删除</button>
            </div></td>
        </tr>`;
    }).join('');
}

function editDownloaderConfig(data) {
    const section = data.section;
    const type = data.type || section.replace('downloader.', '');
    el.modalTitle.textContent = '编辑下载器 — ' + type;
    el.modalBody.innerHTML = `
        <form id="downloaderForm" onsubmit="return false">
            <div class="form-group">
                <label class="form-label">类型</label>
                <select id="dlType" class="form-input">
                    <option value="aria2" ${type==='aria2'?'selected':''}>Aria2</option>
                    <option value="qbittorrent" ${type==='qbittorrent'?'selected':''}>qBittorrent</option>
                    <option value="transmission" ${type==='transmission'?'selected':''}>Transmission</option>
                    <option value="rtorrent" ${type==='rtorrent'?'selected':''}>rTorrent</option>
                    <option value="deluge" ${type==='deluge'?'selected':''}>Deluge</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">名称（标识）</label>
                <input type="text" id="dlName" class="form-input" value="${escapeHtml(data.name||'')}" placeholder="My QBit">
            </div>
            <div class="form-group">
                <label class="form-label">主机地址</label>
                <input type="text" id="dlHost" class="form-input" value="${escapeHtml(data.host||'')}" placeholder="localhost">
            </div>
            <div class="form-group">
                <label class="form-label">端口</label>
                <input type="text" id="dlPort" class="form-input" value="${escapeHtml(data.port||'')}" placeholder="6800">
            </div>
            <div class="form-group">
                <label class="form-label">用户名</label>
                <input type="text" id="dlUser" class="form-input" value="${escapeHtml(data.username||'')}" placeholder="">
            </div>
            <div class="form-group">
                <label class="form-label">密码</label>
                <input type="password" id="dlPass" class="form-input" value="${escapeHtml(data.password||'')}" placeholder="">
            </div>
            <div class="form-group">
                <label class="form-label">RPC URL（可选，留空自动拼接）</label>
                <input type="text" id="dlRpcUrl" class="form-input" value="${escapeHtml(data.rpc_url||'')}" placeholder="">
            </div>
        </form>
    `;
    el.modalConfirmBtn.textContent = '保存';
    el.modalConfirmBtn.onclick = async () => {
        const newType = document.getElementById('dlType').value;
        const values = {};
        const name = document.getElementById('dlName').value.trim();
        const host = document.getElementById('dlHost').value.trim();
        const port = document.getElementById('dlPort').value.trim();
        const user = document.getElementById('dlUser').value.trim();
        const pass = document.getElementById('dlPass').value.trim();
        const rpc = document.getElementById('dlRpcUrl').value.trim();
        if (name) values.name = name;
        if (host) values.host = host;
        if (port) values.port = port;
        if (user) values.username = user;
        if (pass) values.password = pass;
        if (rpc) { values.rpc_url = rpc; }
        else if (host && port) { values.rpc_url = `http://${host}:${port}${RPC_PATHS[newType] || ''}`; }
        try {
            await saveConfigToApi('downloader.' + newType, values);
            if (newType !== type) await deleteConfigSectionApi(section);
            showToast('下载器配置已保存', 'success');
            hideModal();
            await loadDownloaderConfigs();
        } catch (e) { showToast(`保存失败: ${e.message}`, 'error'); }
    };
    showModal();
}
window.editDownloaderConfig = editDownloaderConfig;

function showAddDownloaderModal() {
    editDownloaderConfig({ section: '', type: 'aria2' });
    el.modalTitle.textContent = '添加下载器';
    el.modalConfirmBtn.textContent = '添加';
}
window.showAddDownloaderModal = showAddDownloaderModal;

async function deleteDownloaderConfig(section) {
    if (!confirm(`确定删除下载器配置「${section}」？`)) return;
    try {
        await deleteConfigSectionApi(section);
        showToast('下载器配置已删除', 'success');
        await loadDownloaderConfigs();
    } catch (e) { showToast(`删除失败: ${e.message}`, 'error'); }
}
window.deleteDownloaderConfig = deleteDownloaderConfig;

// ===== 上传进度 WebSocket（带指数退避重连）=====

const uploadState = { progresses: {}, ws: null, reconnectTimer: null, reconnectAttempt: 0, isConnected: false };
const WS_BASE_DELAY = 1000;
const WS_MAX_DELAY = 30000;

function connectUploadProgressWebSocket() {
    if (uploadState.ws) return;
    try {
        uploadState.ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/tasks/ws/progress`);
        uploadState.ws.onopen = () => {
            const token = getAuthToken();
            if (token) uploadState.ws.send(JSON.stringify({ type: 'auth', token }));
            uploadState.isConnected = true;
            uploadState.reconnectAttempt = 0;
            updateUploadStatusDot(true);
            loadUploadProgress();
        };
        uploadState.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'progress') handleUploadProgressUpdate(data);
            } catch (e) { console.error('[Upload] 解析消息失败:', e); }
        };
        uploadState.ws.onclose = () => {
            uploadState.isConnected = false;
            updateUploadStatusDot(false);
            uploadState.ws = null;
            scheduleReconnect();
        };
        uploadState.ws.onerror = () => {};
    } catch (e) { console.error('[Upload] 连接失败:', e); scheduleReconnect(); }
}

function scheduleReconnect() {
    if (uploadState.reconnectTimer) return;
    const delay = Math.min(WS_BASE_DELAY * Math.pow(2, uploadState.reconnectAttempt), WS_MAX_DELAY);
    uploadState.reconnectAttempt++;
    uploadState.reconnectTimer = setTimeout(() => {
        uploadState.reconnectTimer = null;
        connectUploadProgressWebSocket();
    }, delay);
}

function disconnectUploadProgressWebSocket() {
    if (uploadState.ws) { uploadState.ws.close(); uploadState.ws = null; }
    if (uploadState.reconnectTimer) { clearTimeout(uploadState.reconnectTimer); uploadState.reconnectTimer = null; }
}

async function loadUploadProgress() {
    try {
        const result = await loadUploadProgressFromApi();
        if (result && result.progresses) {
            uploadState.progresses = result.progresses;
            updateUploadProgressList();
        }
    } catch (e) { console.error('[Upload] 加载进度失败:', e); }
}

function handleUploadProgressUpdate(data) {
    const { file_path, filename, uploader, progress, uploaded_bytes, total_bytes, speed, status, error } = data;
    uploadState.progresses[file_path] = { filename, uploader, progress, uploaded_bytes, total_bytes, speed, status, error, timestamp: Date.now() };
    if (status === 'completed' || status === 'failed') {
        setTimeout(() => { delete uploadState.progresses[file_path]; updateUploadProgressList(); }, 5000);
    }
    updateUploadProgressList();
}

function updateUploadStatusDot(isActive) {
    if (el.uploadStatusDot) {
        el.uploadStatusDot.className = isActive ? 'upload-status-dot active' : 'upload-status-dot';
    }
}

function updateUploadProgressList() {
    if (!el.uploadProgressList) return;
    const progresses = Object.values(uploadState.progresses);
    const activeUploads = progresses.filter(p => p.status === 'uploading');
    updateUploadStatusDot(activeUploads.length > 0);

    if (progresses.length === 0) {
        el.uploadProgressList.innerHTML = `<tr><td colspan="5"><div class="empty-state"><p>暂无上传任务</p></div></td></tr>`;
        return;
    }

    el.uploadProgressList.innerHTML = progresses.map(p => {
        const statusBadge = p.status === 'uploading' ? '<span class="badge badge-warning">上传中</span>'
            : p.status === 'completed' ? '<span class="badge badge-success">已完成</span>'
            : p.status === 'failed' ? '<span class="badge badge-danger">失败</span>' : '';
        const uploaderNames = { 'cloud189': '天翼云盘', 'yun139': '139云盘', 'p123': '123云盘', 'emos': 'Emos' };
        const pct = Math.min(100, Math.max(0, p.progress || 0));
        return `<tr>
            <td style="font-family:monospace;font-size:0.8125rem">${escapeHtml(p.filename || '未知文件')}</td>
            <td><span class="uploader-badge uploader-${p.uploader}">${escapeHtml(uploaderNames[p.uploader] || p.uploader)}</span></td>
            <td style="min-width:150px">
                <div class="progress-bar-container"><div class="progress-bar-fill" style="width:${pct}%"></div></div>
                <div class="progress-text">${formatSize(p.uploaded_bytes || 0)} / ${formatSize(p.total_bytes || 0)}</div>
                <small style="color:var(--text-muted)">${pct.toFixed(1)}%</small>
            </td>
            <td>${escapeHtml(p.speed || '-')}</td>
            <td>${statusBadge}${p.error ? `<br><small style="color:var(--accent-danger)">${escapeHtml(p.error)}</small>` : ''}</td>
        </tr>`;
    }).join('');
}

// ===== 用户管理 =====

let _users = [];

async function loadUsers() {
    try {
        _users = await loadUsersFromApi();
        renderUsers();
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载用户失败:', e); }
}

function renderUsers() {
    if (!_users.length) {
        el.userList.innerHTML = `<tr><td colspan="6"><div class="empty-state"><p>暂无用户</p></div></td></tr>`;
        return;
    }
    el.userList.innerHTML = _users.map(u => `<tr>
        <td>${u.id}</td>
        <td><strong>${escapeHtml(u.username)}</strong></td>
        <td><span class="badge ${u.role === 'admin' ? 'badge-success' : 'badge-info'}">${escapeHtml(u.role)}</span></td>
        <td><span class="badge ${u.enabled ? 'badge-success' : 'badge-danger'}">${u.enabled ? '启用' : '禁用'}</span></td>
        <td style="font-size:0.8125rem;color:var(--text-muted)">${u.created_at ? new Date(u.created_at).toLocaleString() : '-'}</td>
        <td><div class="btn-cell">
            <button class="save-btn" onclick="editUser('${u.id}')">编辑</button>
            <button class="del-btn" onclick="deleteUser('${u.id}')">删除</button>
        </div></td>
    </tr>`).join('');
}

function showAddUserModal() {
    el.modalTitle.textContent = '添加用户';
    el.modalBody.innerHTML = `
        <form id="userForm" onsubmit="return false">
            <div class="form-group">
                <label class="form-label">用户名</label>
                <input type="text" id="ufUsername" class="form-input" placeholder="请输入用户名" autocomplete="off">
            </div>
            <div class="form-group">
                <label class="form-label">密码</label>
                <input type="password" id="ufPassword" class="form-input" placeholder="请输入密码" autocomplete="new-password">
            </div>
            <div class="form-group">
                <label class="form-label">角色</label>
                <select id="ufRole" class="form-input">
                    <option value="user">普通用户</option>
                    <option value="admin">管理员</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label"><input type="checkbox" id="ufEnabled" checked> 启用</label>
            </div>
        </form>
    `;
    el.modalConfirmBtn.textContent = '添加';
    el.modalConfirmBtn.onclick = async () => {
        const username = document.getElementById('ufUsername').value.trim();
        const password = document.getElementById('ufPassword').value.trim();
        const role = document.getElementById('ufRole').value;
        const enabled = document.getElementById('ufEnabled').checked;
        if (!username) { showToast('请输入用户名', 'error'); return; }
        if (!password) { showToast('请输入密码', 'error'); return; }
        try {
            await createUserViaApi({ username, password, role, enabled });
            showToast('用户已创建', 'success');
            hideModal();
            await loadUsers();
        } catch (e) { showToast('创建失败: ' + e.message, 'error'); }
    };
    showModal();
}
window.showAddUserModal = showAddUserModal;

async function editUser(userId) {
    const u = _users.find(x => x.id == userId);
    if (!u) return;
    el.modalTitle.textContent = '编辑用户 — ' + u.username;
    el.modalBody.innerHTML = `
        <form id="userForm" onsubmit="return false">
            <div class="form-group">
                <label class="form-label">用户名</label>
                <input type="text" id="ufUsername" class="form-input" value="${escapeHtml(u.username)}" autocomplete="off">
            </div>
            <div class="form-group">
                <label class="form-label">密码（留空不修改）</label>
                <input type="password" id="ufPassword" class="form-input" placeholder="留空则保持原密码" autocomplete="new-password">
            </div>
            <div class="form-group">
                <label class="form-label">角色</label>
                <select id="ufRole" class="form-input">
                    <option value="user" ${u.role === 'user' ? 'selected' : ''}>普通用户</option>
                    <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>管理员</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label"><input type="checkbox" id="ufEnabled" ${u.enabled ? 'checked' : ''}> 启用</label>
            </div>
        </form>
    `;
    el.modalConfirmBtn.textContent = '保存';
    el.modalConfirmBtn.onclick = async () => {
        const data = {};
        const username = document.getElementById('ufUsername').value.trim();
        const password = document.getElementById('ufPassword').value.trim();
        const role = document.getElementById('ufRole').value;
        const enabled = document.getElementById('ufEnabled').checked;
        if (!username) { showToast('请输入用户名', 'error'); return; }
        data.username = username;
        if (password) data.password = password;
        data.role = role;
        data.enabled = enabled;
        try {
            await updateUserViaApi(userId, data);
            showToast('用户已更新', 'success');
            hideModal();
            await loadUsers();
        } catch (e) { showToast('更新失败: ' + e.message, 'error'); }
    };
    showModal();
}
window.editUser = editUser;

async function deleteUser(userId) {
    const u = _users.find(x => x.id == userId);
    if (!confirm('确定删除用户「' + (u ? u.username : userId) + '」？')) return;
    try {
        await deleteUserViaApi(userId);
        showToast('用户已删除', 'success');
        await loadUsers();
    } catch (e) { showToast('删除失败: ' + e.message, 'error'); }
}
window.deleteUser = deleteUser;
