const state = {
    config: null,
    tasks: { queued: [], processing: [], completed: [], failed: {} },
    status: null,
    currentTab: 'queued',
    logWebSocket: null,
    autoRefresh: null,
    initialized: false
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
    el.uploadProgressList = document.getElementById('upload-progress-list');
    el.uploadStatusDot = document.getElementById('uploadStatusDot');
    el.modalOverlay = document.getElementById('modalOverlay');
    el.modalTitle = document.getElementById('modalTitle');
    el.modalBody = document.getElementById('modalBody');
    el.modalClose = document.getElementById('modalClose');
    el.modalCancelBtn = document.getElementById('modalCancelBtn');
    el.modalConfirmBtn = document.getElementById('modalConfirmBtn');
    el.toastContainer = document.getElementById('toastContainer');
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
    el.modalClose.addEventListener('click', hideModal);
    el.modalCancelBtn.addEventListener('click', hideModal);
    el.modalOverlay.addEventListener('click', (e) => {
        if (e.target === el.modalOverlay) hideModal();
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
    await Promise.all([loadStatus(), loadConfig(), loadLogFiles(), loadDownloaders()]);
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
}

function switchTaskTab(tabName) {
    state.currentTab = tabName;
    el.taskTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.tab === tabName));
    el.clearFailedBtn.style.display = tabName === 'failed' ? 'inline-flex' : 'none';
    el.retryAllBtn.style.display = tabName === 'failed' ? 'inline-flex' : 'none';
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

function updateTaskList() {
    const tab = state.currentTab;
    let files = [];
    let statusBadge = '';
    switch (tab) {
        case 'queued':
            files = state.tasks.queued.map(f => ({ path: f }));
            statusBadge = '<span class="badge badge-info">队列中</span>';
            break;
        case 'processing':
            files = state.tasks.processing.map(f => ({ path: f }));
            statusBadge = '<span class="badge badge-warning">处理中</span>';
            break;
        case 'completed':
            files = (state.tasks._completed || []).map(f => ({ path: f.path, time: f.time }));
            statusBadge = '<span class="badge badge-success">已完成</span>';
            break;
        case 'failed':
            files = Object.entries(state.tasks.failed).map(([p, err]) => ({ path: p, error: err }));
            // 合并时间信息
            if (state.tasks._failed) {
                for (const f of files) {
                    const ft = state.tasks._failed[f.path];
                    if (ft) f.time = ft.time;
                }
            }
            statusBadge = '<span class="badge badge-danger">失败</span>';
            break;
    }
    if (files.length === 0) {
        el.taskList.innerHTML = `<tr><td colspan="4"><div class="empty-state"><p>暂无数据</p></div></td></tr>`;
        return;
    }
    const showTime = tab === 'completed' || tab === 'failed';
    el.taskList.innerHTML = files.map(file => `<tr>
        <td style="font-family:monospace;font-size:0.8125rem">${escapeHtml(file.path)}</td>
        <td>${statusBadge}${file.error ? `<br><small style="color:var(--accent-danger)">${escapeHtml(file.error)}</small>` : ''}</td>
        ${showTime ? `<td style="color:var(--text-muted);white-space:nowrap;font-size:0.8125rem">${formatRelativeTime(file.time)}</td>` : ''}
        <td>${tab === 'failed' ? `<button class="btn btn-primary btn-sm" onclick="retryTask('${escapeHtml(file.path)}')">重试</button>
            <button class="btn btn-danger btn-sm" onclick="confirmClearFailed('${escapeHtml(file.path)}')">清除</button>` : ''}</td>
    </tr>`).join('');
    // 更新表头列数
    const headers = el.taskList.closest('table')?.querySelector('thead tr');
    if (headers && showTime && headers.children.length < 4) {
        const th = document.createElement('th');
        th.textContent = '时间';
        headers.insertBefore(th, headers.lastElementChild);
    }
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

function updateRecentActivity() {
    apiRequest('/tasks/recent').then(data => {
        const items = data.items || [];
        if (items.length === 0) {
            el.recentActivity.innerHTML = `<tr><td colspan="3"><div class="empty-state"><p>暂无数据</p></div></td></tr>`;
            return;
        }
        el.recentActivity.innerHTML = items.map(t => `<tr>
            <td style="font-family:monospace;font-size:0.8125rem">${escapeHtml(t.path)}</td>
            <td><span class="badge ${t.status === 'completed' ? 'badge-success' : 'badge-danger'}">${t.status === 'completed' ? '已完成' : '失败'}</span></td>
            <td style="color:var(--text-muted);white-space:nowrap">${formatRelativeTime(t.time)}</td>
        </tr>`).join('');
    }).catch(() => {
        // fallback: 兼容旧格式
    });
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

async function loadConfig() {
    try {
        state.config = await loadConfigFromApi();
        renderConfigEditor();
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载配置失败:', e); }
}

function renderConfigEditor() {
    const config = state.config;
    if (!config) return;

    const sections = {
        'monitoring': '监控配置', 'tmdb': 'TMDB 配置', 'logging': '日志配置',
        'naming': '命名规则', 'processing': '处理配置',
        'p123': '123云盘配置', 'cloud189': '天翼云盘配置', 'yun139': '139云盘配置'
    };

    let html = '';
    for (const [key, label] of Object.entries(sections)) {
        if (!config[key]) continue;
        html += `<div class="config-section"><div class="config-section-title">${label}</div>`;
        for (const [k, v] of Object.entries(config[key])) {
            html += `<div class="form-group"><label class="form-label">${escapeHtml(k)}</label>${renderConfigInput(key, k, v)}</div>`;
        }
        html += `</div>`;
    }
    el.configEditor.innerHTML = html;

    // 绑定 checkbox 标签同步
    document.querySelectorAll('#config-editor input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', () => {
            const label = document.getElementById(`${cb.id}-label`);
            if (label) label.textContent = cb.checked ? '是' : '否';
        });
    });
}

function renderConfigInput(section, key, value) {
    const inputId = `config-${section}-${key}`;
    const inputName = `${section}.${key}`;
    const isPassword = key.toLowerCase().includes('password') || key.toLowerCase().includes('token') || key.toLowerCase().includes('secret') || key.toLowerCase().includes('api_key');
    if (typeof value === 'boolean') {
        return `<label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="${inputId}" name="${inputName}" ${value ? 'checked' : ''}>
            <span id="${inputId}-label">${value ? '是' : '否'}</span>
        </label>`;
    }
    if (Array.isArray(value)) {
        return `<input type="text" class="form-input" id="${inputId}" name="${inputName}" value="${escapeHtml(value.join(', '))}">`;
    }
    if (typeof value === 'object' && value !== null) {
        return `<textarea class="form-textarea" id="${inputId}" name="${inputName}">${escapeHtml(JSON.stringify(value, null, 2))}</textarea>`;
    }
    if (isPassword) {
        return `<input type="password" class="form-input" id="${inputId}" name="${inputName}" value="${escapeHtml(String(value))}">`;
    }
    return `<input type="text" class="form-input" id="${inputId}" name="${inputName}" value="${escapeHtml(String(value))}">`;
}

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
            if (Object.keys(changed).length === 0) {
                successCount++;
                continue;
            }
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
        if (!result.downloaders || result.downloaders.length === 0) {
            el.downloaderList.innerHTML = `<tr><td colspan="3"><div class="empty-state"><p>暂无下载器</p></div></td></tr>`;
            return;
        }
        el.downloaderList.innerHTML = result.downloaders.map(d => `<tr>
            <td>${escapeHtml(d.name)}</td>
            <td>${escapeHtml(d.type)}</td>
            <td><span class="badge ${d.connected ? 'badge-success' : 'badge-danger'}">${d.connected ? '已连接' : '未连接'}</span></td>
        </tr>`).join('');
    } catch (e) { if (!e.message.includes('登录已过期')) console.error('加载下载器失败:', e); }
}

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
