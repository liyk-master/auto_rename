/**
 * Video Organizer Web 管理后台 - 前端脚本
 */

// API 基础路径
const API_BASE = '/api';

// 状态
const state = {
    config: null,
    tasks: {
        queued: [],
        processing: [],
        completed: [],
        failed: {}
    },
    status: null,
    currentTab: 'queued',
    currentLogTab: 'queued',
    logWebSocket: null,
    autoRefresh: null
};

// DOM 元素缓存
const elements = {};

// 初始化
document.addEventListener('DOMContentLoaded', async () => {
    initElements();
    initEventListeners();
    await loadInitialData();
    startAutoRefresh();
    // 连接上传进度 WebSocket
    connectUploadProgressWebSocket();
});

// 初始化 DOM 元素缓存
function initElements() {
    // 导航
    elements.navItems = document.querySelectorAll('.nav-item');
    elements.pages = document.querySelectorAll('.page');
    elements.statusDot = document.getElementById('statusDot');
    elements.statusText = document.getElementById('statusText');
    elements.queueCount = document.getElementById('queueCount');

    // 仪表盘
    elements.statQueue = document.getElementById('stat-queue');
    elements.statProcessing = document.getElementById('stat-processing');
    elements.statCompleted = document.getElementById('stat-completed');
    elements.statFailed = document.getElementById('stat-failed');
    elements.recentActivity = document.getElementById('recent-activity');

    // 任务管理
    elements.taskTabs = document.querySelectorAll('#page-tasks .tab');
    elements.taskList = document.getElementById('task-list');
    elements.refreshTasksBtn = document.getElementById('refreshTasksBtn');
    elements.clearFailedBtn = document.getElementById('clearFailedBtn');
    elements.retryAllBtn = document.getElementById('retryAllBtn');

    // 配置管理
    elements.configEditor = document.getElementById('config-editor');
    elements.reloadConfigBtn = document.getElementById('reloadConfigBtn');
    elements.saveConfigBtn = document.getElementById('saveConfigBtn');

    // 日志查看
    elements.logFileSelect = document.getElementById('logFileSelect');
    elements.logViewer = document.getElementById('logViewer');
    elements.autoScrollCheck = document.getElementById('autoScrollCheck');
    elements.liveLogCheck = document.getElementById('liveLogCheck');

    // 手动处理
    elements.manualFilePath = document.getElementById('manualFilePath');
    elements.browseFileBtn = document.getElementById('browseFileBtn');
    elements.forceProcessCheck = document.getElementById('forceProcessCheck');
    elements.processFileBtn = document.getElementById('processFileBtn');
    elements.previewFileBtn = document.getElementById('previewFileBtn');
    elements.previewResult = document.getElementById('previewResult');
    elements.previewContent = document.getElementById('previewContent');
    elements.scanDirPath = document.getElementById('scanDirPath');
    elements.recursiveScanCheck = document.getElementById('recursiveScanCheck');
    elements.scanDirBtn = document.getElementById('scanDirBtn');
    elements.scanResults = document.getElementById('scanResults');
    elements.scannedFilesList = document.getElementById('scannedFilesList');
    elements.selectAllFiles = document.getElementById('selectAllFiles');
    elements.processSelectedBtn = document.getElementById('processSelectedBtn');

    // 下载器
    elements.downloaderList = document.getElementById('downloader-list');
    elements.refreshDownloadersBtn = document.getElementById('refreshDownloadersBtn');

    // 上传进度
    elements.uploadProgressList = document.getElementById('upload-progress-list');
    elements.uploadStatusDot = document.getElementById('uploadStatusDot');

    // 模态框
    elements.modalOverlay = document.getElementById('modalOverlay');
    elements.modalTitle = document.getElementById('modalTitle');
    elements.modalBody = document.getElementById('modalBody');
    elements.modalClose = document.getElementById('modalClose');
    elements.modalCancelBtn = document.getElementById('modalCancelBtn');
    elements.modalConfirmBtn = document.getElementById('modalConfirmBtn');

    // Toast
    elements.toastContainer = document.getElementById('toastContainer');
}

// 初始化事件监听
function initEventListeners() {
    // 导航切换
    elements.navItems.forEach(item => {
        item.addEventListener('click', () => switchPage(item.dataset.page));
    });

    // 任务标签切换
    elements.taskTabs.forEach(tab => {
        tab.addEventListener('click', () => switchTaskTab(tab.dataset.tab));
    });

    // 任务管理按钮
    elements.refreshTasksBtn.addEventListener('click', loadTasks);
    elements.clearFailedBtn.addEventListener('click', clearAllFailedTasks);
    elements.retryAllBtn.addEventListener('click', retryAllFailedTasks);

    // 配置管理按钮
    elements.reloadConfigBtn.addEventListener('click', reloadConfig);
    elements.saveConfigBtn.addEventListener('click', saveConfig);

    // 日志查看
    elements.logFileSelect.addEventListener('change', loadLogContent);
    elements.liveLogCheck.addEventListener('change', toggleLiveLog);

    // 手动处理
    elements.browseFileBtn.addEventListener('click', browseFile);
    elements.processFileBtn.addEventListener('click', processFile);
    elements.previewFileBtn.addEventListener('click', previewFile);
    elements.scanDirBtn.addEventListener('click', scanDirectory);
    elements.selectAllFiles.addEventListener('change', toggleSelectAllFiles);
    elements.processSelectedBtn.addEventListener('click', processSelectedFiles);

    // 下载器
    elements.refreshDownloadersBtn.addEventListener('click', loadDownloaders);

    // 模态框
    elements.modalClose.addEventListener('click', hideModal);
    elements.modalCancelBtn.addEventListener('click', hideModal);
    elements.modalOverlay.addEventListener('click', (e) => {
        if (e.target === elements.modalOverlay) hideModal();
    });
}

// 加载初始数据
async function loadInitialData() {
    await Promise.all([
        loadStatus(),
        loadConfig(),
        loadLogFiles(),
        loadDownloaders()
    ]);
    loadTasks();
}

// 启动自动刷新
function startAutoRefresh() {
    state.autoRefresh = setInterval(() => {
        loadStatus();
        if (document.querySelector('#page-tasks.active')) {
            loadTasks();
        }
    }, 5000);
}

// 切换页面
function switchPage(pageName) {
    elements.navItems.forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageName);
    });
    elements.pages.forEach(page => {
        page.classList.toggle('active', page.id === `page-${pageName}`);
    });
}

// 切换任务标签
function switchTaskTab(tabName) {
    state.currentTab = tabName;
    elements.taskTabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    
    // 显示/隐藏按钮
    elements.clearFailedBtn.style.display = tabName === 'failed' ? 'inline-flex' : 'none';
    elements.retryAllBtn.style.display = tabName === 'failed' ? 'inline-flex' : 'none';
    
    updateTaskList();
}

// API 请求封装
async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || '请求失败');
        }

        return await response.json();
    } catch (error) {
        console.error('API 请求失败:', error);
        throw error;
    }
}

// 加载状态
async function loadStatus() {
    try {
        const status = await apiRequest('/status');
        state.status = status;
        updateStatusDisplay();
    } catch (error) {
        console.error('加载状态失败:', error);
    }
}

// 更新状态显示
function updateStatusDisplay() {
    const status = state.status;
    if (!status) return;

    // 状态点
    elements.statusDot.className = `status-dot ${status.is_running ? 'running' : 'stopped'}`;
    elements.statusText.textContent = status.is_running ? '运行中' : '已停止';

    // 队列数量
    elements.queueCount.textContent = status.queue_size;

    // 统计卡片
    elements.statQueue.textContent = status.queue_size;
    elements.statProcessing.textContent = status.processing_count;
    elements.statCompleted.textContent = status.completed_count;
    elements.statFailed.textContent = status.failed_count;
}

// 加载任务
async function loadTasks() {
    try {
        const [queued, processing, completed, failed] = await Promise.all([
            apiRequest('/tasks/queued'),
            apiRequest('/tasks/processing'),
            apiRequest('/tasks/completed'),
            apiRequest('/tasks/failed')
        ]);

        state.tasks = {
            queued: queued.files,
            processing: processing.files,
            completed: completed.files,
            failed: failed.files
        };

        updateTaskList();
    } catch (error) {
        console.error('加载任务失败:', error);
    }
}

// 更新任务列表
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
            files = state.tasks.completed.map(f => ({ path: f }));
            statusBadge = '<span class="badge badge-success">已完成</span>';
            break;
        case 'failed':
            files = Object.entries(state.tasks.failed).map(([path, error]) => ({ path, error }));
            statusBadge = '<span class="badge badge-danger">失败</span>';
            break;
    }

    if (files.length === 0) {
        elements.taskList.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">暂无数据</td></tr>`;
        return;
    }

    elements.taskList.innerHTML = files.map(file => `
        <tr>
            <td style="font-family: monospace; font-size: 0.8125rem;">${escapeHtml(file.path)}</td>
            <td>${statusBadge}${file.error ? `<br><small style="color: var(--accent-danger);">${escapeHtml(file.error)}</small>` : ''}</td>
            <td>
                ${tab === 'failed' ? `
                    <button class="btn btn-primary btn-sm" onclick="retryTask('${escapeHtml(file.path)}')">重试</button>
                    <button class="btn btn-danger btn-sm" onclick="clearFailedTask('${escapeHtml(file.path)}')">清除</button>
                ` : ''}
            </td>
        </tr>
    `).join('');
}

// 重试任务
async function retryTask(filePath) {
    try {
        await apiRequest('/tasks/retry', {
            method: 'POST',
            body: JSON.stringify({ file_path: filePath })
        });
        showToast('已重试任务', 'success');
        loadTasks();
    } catch (error) {
        showToast(`重试失败: ${error.message}`, 'error');
    }
}

// 清除失败任务
async function clearFailedTask(filePath) {
    try {
        await apiRequest(`/tasks/failed/${encodeURIComponent(filePath)}`, {
            method: 'DELETE'
        });
        showToast('已清除失败记录', 'success');
        loadTasks();
    } catch (error) {
        showToast(`清除失败: ${error.message}`, 'error');
    }
}

// 清除所有失败任务
async function clearAllFailedTasks() {
    try {
        await apiRequest('/tasks/failed', { method: 'DELETE' });
        showToast('已清除所有失败记录', 'success');
        loadTasks();
    } catch (error) {
        showToast(`清除失败: ${error.message}`, 'error');
    }
}

// 重试所有失败任务
async function retryAllFailedTasks() {
    try {
        const result = await apiRequest('/tasks/retry-all', { method: 'POST' });
        showToast(`已重试 ${result.retried_count} 个任务`, 'success');
        loadTasks();
    } catch (error) {
        showToast(`重试失败: ${error.message}`, 'error');
    }
}

// 加载配置
async function loadConfig() {
    try {
        const result = await apiRequest('/config');
        state.config = result.config;
        renderConfigEditor();
    } catch (error) {
        console.error('加载配置失败:', error);
    }
}

// 渲染配置编辑器
function renderConfigEditor() {
    const config = state.config;
    if (!config) return;

    const sections = {
        'monitoring': '监控配置',
        'tmdb': 'TMDB 配置',
        'logging': '日志配置',
        'naming': '命名规则',
        'processing': '处理配置',
        'p123': '123云盘配置',
        'cloud189': '天翼云盘配置',
        'yun139': '139云盘配置'
    };

    let html = '';
    for (const [key, label] of Object.entries(sections)) {
        if (!config[key]) continue;
        html += `
            <div class="config-section">
                <div class="config-section-title">${label}</div>
                ${Object.entries(config[key]).map(([k, v]) => `
                    <div class="form-group">
                        <label class="form-label">${k}</label>
                        ${renderConfigInput(key, k, v)}
                    </div>
                `).join('')}
            </div>
        `;
    }

    elements.configEditor.innerHTML = html;
}

// 渲染配置输入框
function renderConfigInput(section, key, value) {
    const inputId = `config-${section}-${key}`;
    const inputName = `${section}.${key}`;

    if (typeof value === 'boolean') {
        return `
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                <input type="checkbox" id="${inputId}" name="${inputName}" ${value ? 'checked' : ''}>
                <span>${value ? '是' : '否'}</span>
            </label>
        `;
    } else if (Array.isArray(value)) {
        return `<input type="text" class="form-input" id="${inputId}" name="${inputName}" value="${escapeHtml(value.join(', '))}">`;
    } else if (typeof value === 'object') {
        return `<textarea class="form-textarea" id="${inputId}" name="${inputName}">${escapeHtml(JSON.stringify(value, null, 2))}</textarea>`;
    } else {
        return `<input type="text" class="form-input" id="${inputId}" name="${inputName}" value="${escapeHtml(String(value))}">`;
    }
}

// 重新加载配置
async function reloadConfig() {
    try {
        await apiRequest('/config/reload', { method: 'POST' });
        await loadConfig();
        showToast('配置已重新加载', 'success');
    } catch (error) {
        showToast(`重新加载失败: ${error.message}`, 'error');
    }
}

// 保存配置
async function saveConfig() {
    showToast('配置保存功能开发中...', 'warning');
}

// 加载日志文件列表
async function loadLogFiles() {
    try {
        const result = await apiRequest('/logs/files');
        elements.logFileSelect.innerHTML = '<option value="">选择日志文件</option>' +
            result.files.map(f => `<option value="${f}">${f}</option>`).join('');
        
        if (result.current) {
            elements.logFileSelect.value = result.current;
            loadLogContent();
        }
    } catch (error) {
        console.error('加载日志文件列表失败:', error);
    }
}

// 加载日志内容
async function loadLogContent() {
    const filename = elements.logFileSelect.value;
    if (!filename) return;

    try {
        const content = await fetch(`${API_BASE}/logs/content/${encodeURIComponent(filename)}?lines=200`);
        if (!content.ok) throw new Error('加载失败');
        const text = await content.text();
        
        const lines = text.split('\n');
        elements.logViewer.innerHTML = lines.map(line => {
            let className = 'log-line';
            if (line.includes(' ERROR ')) className += ' error';
            else if (line.includes(' WARNING ')) className += ' warning';
            else if (line.includes(' INFO ')) className += ' info';
            return `<div class="${className}">${escapeHtml(line)}</div>`;
        }).join('');

        if (elements.autoScrollCheck.checked) {
            elements.logViewer.scrollTop = elements.logViewer.scrollHeight;
        }
    } catch (error) {
        showToast(`加载日志失败: ${error.message}`, 'error');
    }
}

// 切换实时日志
function toggleLiveLog() {
    const filename = elements.logFileSelect.value;
    if (!filename) return;

    if (elements.liveLogCheck.checked) {
        startLiveLog(filename);
    } else {
        stopLiveLog();
    }
}

// 启动实时日志
function startLiveLog(filename) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API_BASE}/logs/ws/${encodeURIComponent(filename)}`;
    
    state.logWebSocket = new WebSocket(wsUrl);
    
    state.logWebSocket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'log') {
            let className = 'log-line';
            if (data.content.includes(' ERROR ')) className += ' error';
            else if (data.content.includes(' WARNING ')) className += ' warning';
            else if (data.content.includes(' INFO ')) className += ' info';
            
            elements.logViewer.innerHTML += `<div class="${className}">${escapeHtml(data.content)}</div>`;
            
            if (elements.autoScrollCheck.checked) {
                elements.logViewer.scrollTop = elements.logViewer.scrollHeight;
            }
        }
    };

    state.logWebSocket.onerror = () => {
        showToast('WebSocket 连接失败', 'error');
        elements.liveLogCheck.checked = false;
    };
}

// 停止实时日志
function stopLiveLog() {
    if (state.logWebSocket) {
        state.logWebSocket.close();
        state.logWebSocket = null;
    }
}

// 浏览文件
async function browseFile() {
    const currentPath = elements.manualFilePath.value || '';
    try {
        const result = await apiRequest(`/manual/browse?path=${encodeURIComponent(currentPath)}`);
        showBrowseModal(result);
    } catch (error) {
        showToast(`浏览失败: ${error.message}`, 'error');
    }
}

// 显示浏览模态框
function showBrowseModal(data) {
    elements.modalTitle = '选择文件';
    
    let html = `
        <div class="file-browser">
            <div class="file-browser-header">
                ${data.parent ? `<button class="btn btn-secondary btn-sm" onclick="browsePath('${escapeHtml(data.parent)}')">..</button>` : ''}
                <div class="file-browser-path">${escapeHtml(data.path) || '根目录'}</div>
            </div>
            <div class="file-list">
    `;
    
    data.directories.forEach(dir => {
        html += `
            <div class="file-item" onclick="browsePath('${escapeHtml(data.path)}\\${escapeHtml(dir)}')">
                <svg class="file-icon folder" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M10 4H4a2 2 0 00-2 2v12a2 2 0 002 2h16a2 2 0 002-2V8a2 2 0 00-2-2h-8l-2-2z"/>
                </svg>
                <span>${escapeHtml(dir)}</span>
            </div>
        `;
    });
    
    data.files.forEach(file => {
        const isVideo = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv'].includes(file.extension);
        html += `
            <div class="file-item" onclick="selectFile('${escapeHtml(data.path)}\\${escapeHtml(file.name)}')">
                <svg class="file-icon ${isVideo ? 'video' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                </svg>
                <span>${escapeHtml(file.name)}</span>
                <small style="color: var(--text-muted); margin-left: auto;">${formatSize(file.size)}</small>
            </div>
        `;
    });
    
    html += '</div></div>';
    
    elements.modalBody.innerHTML = html;
    elements.modalFooter.style.display = 'none';
    showModal();
}

// 浏览路径
async function browsePath(path) {
    try {
        const result = await apiRequest(`/manual/browse?path=${encodeURIComponent(path)}`);
        showBrowseModal(result);
    } catch (error) {
        showToast(`浏览失败: ${error.message}`, 'error');
    }
}

// 选择文件
function selectFile(path) {
    elements.manualFilePath.value = path;
    hideModal();
}

// 处理文件
async function processFile() {
    const filePath = elements.manualFilePath.value.trim();
    if (!filePath) {
        showToast('请输入文件路径', 'warning');
        return;
    }

    try {
        const result = await apiRequest('/manual/process', {
            method: 'POST',
            body: JSON.stringify({
                file_path: filePath,
                force: elements.forceProcessCheck.checked
            })
        });
        showToast(result.message, result.success ? 'success' : 'warning');
        if (result.success) {
            elements.manualFilePath.value = '';
            loadTasks();
        }
    } catch (error) {
        showToast(`处理失败: ${error.message}`, 'error');
    }
}

// 预览文件
async function previewFile() {
    const filePath = elements.manualFilePath.value.trim();
    if (!filePath) {
        showToast('请输入文件路径', 'warning');
        return;
    }

    try {
        const result = await apiRequest('/manual/preview', {
            method: 'POST',
            body: JSON.stringify({ file_path: filePath })
        });

        if (result.success) {
            elements.previewResult.style.display = 'block';
            elements.previewContent.innerHTML = `
                <div class="form-group">
                    <label class="form-label">原始名称</label>
                    <div style="font-family: monospace;">${escapeHtml(result.original_name)}</div>
                </div>
                <div class="form-group">
                    <label class="form-label">建议名称</label>
                    <div style="font-family: monospace; color: var(--accent-primary);">${escapeHtml(result.suggested_name || '无法生成')}</div>
                </div>
                <div class="form-group">
                    <label class="form-label">媒体类型</label>
                    <span class="badge badge-info">${result.media_type || '未知'}</span>
                </div>
                <div class="form-group">
                    <label class="form-label">元数据</label>
                    <pre style="background: var(--bg-primary); padding: 12px; border-radius: 8px; overflow-x: auto;">${JSON.stringify(result.metadata, null, 2)}</pre>
                </div>
            `;
        } else {
            elements.previewResult.style.display = 'block';
            elements.previewContent.innerHTML = `<div style="color: var(--accent-danger);">${escapeHtml(result.error)}</div>`;
        }
    } catch (error) {
        showToast(`预览失败: ${error.message}`, 'error');
    }
}

// 扫描目录
async function scanDirectory() {
    const dirPath = elements.scanDirPath.value.trim();
    if (!dirPath) {
        showToast('请输入目录路径', 'warning');
        return;
    }

    try {
        const result = await apiRequest('/manual/scan', {
            method: 'POST',
            body: JSON.stringify({
                directory: dirPath,
                recursive: elements.recursiveScanCheck.checked
            })
        });

        if (result.files.length === 0) {
            showToast('未找到视频文件', 'warning');
            return;
        }

        elements.scanResults.style.display = 'block';
        elements.scannedFilesList.innerHTML = result.files.map((file, index) => {
            const path = new Path(file);
            return `
                <tr>
                    <td><input type="checkbox" class="file-checkbox" data-path="${escapeHtml(file)}"></td>
                    <td>${escapeHtml(path.basename || file)}</td>
                    <td>-</td>
                </tr>
            `;
        }).join('');

        showToast(`找到 ${result.files.length} 个视频文件`, 'success');
    } catch (error) {
        showToast(`扫描失败: ${error.message}`, 'error');
    }
}

// 全选/取消全选
function toggleSelectAllFiles() {
    const checkboxes = document.querySelectorAll('.file-checkbox');
    checkboxes.forEach(cb => cb.checked = elements.selectAllFiles.checked);
}

// 处理选中文件
async function processSelectedFiles() {
    const checkboxes = document.querySelectorAll('.file-checkbox:checked');
    if (checkboxes.length === 0) {
        showToast('请选择要处理的文件', 'warning');
        return;
    }

    const files = Array.from(checkboxes).map(cb => cb.dataset.path);

    try {
        const result = await apiRequest('/manual/process-batch', {
            method: 'POST',
            body: JSON.stringify(files)
        });
        showToast(result.message, 'success');
        loadTasks();
    } catch (error) {
        showToast(`批量处理失败: ${error.message}`, 'error');
    }
}

// 加载下载器
async function loadDownloaders() {
    try {
        const result = await apiRequest('/downloaders');
        
        if (result.downloaders.length === 0) {
            elements.downloaderList.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">暂无下载器</td></tr>`;
            return;
        }

        elements.downloaderList.innerHTML = result.downloaders.map(d => `
            <tr>
                <td>${escapeHtml(d.name)}</td>
                <td>${escapeHtml(d.type)}</td>
                <td>
                    <span class="badge ${d.connected ? 'badge-success' : 'badge-danger'}">
                        ${d.connected ? '已连接' : '未连接'}
                    </span>
                </td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('加载下载器失败:', error);
    }
}

// 显示模态框
function showModal() {
    elements.modalOverlay.classList.add('show');
}

// 隐藏模态框
function hideModal() {
    elements.modalOverlay.classList.remove('show');
}

// 显示 Toast
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            ${type === 'success' ? '<path d="M20 6L9 17l-5-5"/>' : 
              type === 'error' ? '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>' :
              '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'}
        </svg>
        <span>${escapeHtml(message)}</span>
    `;
    elements.toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// HTML 转义
function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// 格式化文件大小
function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Path polyfill for Windows paths
class Path {
    constructor(pathStr) {
        this.path = pathStr;
    }
    get basename() {
        const parts = this.path.split(/[/\\]/);
        return parts[parts.length - 1];
    }
    get dirname() {
        const parts = this.path.split(/[/\\]/);
        return parts.slice(0, -1).join('/');
    }
    get extname() {
        const idx = this.basename.lastIndexOf('.');
        return idx >= 0 ? this.basename.slice(idx) : '';
    }
}

// ==================== 上传进度 WebSocket ====================

const uploadProgressState = {
    progresses: {},  // { file_path: { filename, uploader, progress, ... } }
    ws: null,
    reconnectTimer: null,
    isConnected: false
};

// 连接 WebSocket
function connectUploadProgressWebSocket() {
    if (uploadProgressState.ws) {
        return;  // 已经连接
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/tasks/ws/progress`;

    try {
        uploadProgressState.ws = new WebSocket(wsUrl);

        uploadProgressState.ws.onopen = () => {
            console.log('[UploadProgress] WebSocket 已连接');
            uploadProgressState.isConnected = true;
            updateUploadStatusDot(true);
            // 连接后获取当前进度
            loadUploadProgress();
        };

        uploadProgressState.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'progress') {
                    handleUploadProgressUpdate(data);
                }
            } catch (e) {
                console.error('[UploadProgress] 解析消息失败:', e);
            }
        };

        uploadProgressState.ws.onclose = () => {
            console.log('[UploadProgress] WebSocket 已断开');
            uploadProgressState.isConnected = false;
            updateUploadStatusDot(false);
            uploadProgressState.ws = null;
            // 5秒后尝试重连
            if (!uploadProgressState.reconnectTimer) {
                uploadProgressState.reconnectTimer = setTimeout(() => {
                    uploadProgressState.reconnectTimer = null;
                    connectUploadProgressWebSocket();
                }, 5000);
            }
        };

        uploadProgressState.ws.onerror = (error) => {
            console.error('[UploadProgress] WebSocket 错误:', error);
        };
    } catch (e) {
        console.error('[UploadProgress] 连接失败:', e);
    }
}

// 断开 WebSocket
function disconnectUploadProgressWebSocket() {
    if (uploadProgressState.ws) {
        uploadProgressState.ws.close();
        uploadProgressState.ws = null;
    }
    if (uploadProgressState.reconnectTimer) {
        clearTimeout(uploadProgressState.reconnectTimer);
        uploadProgressState.reconnectTimer = null;
    }
}

// 加载当前上传进度
async function loadUploadProgress() {
    try {
        const result = await apiRequest('/tasks/progress');
        if (result.progresses) {
            uploadProgressState.progresses = result.progresses;
            updateUploadProgressList();
        }
    } catch (error) {
        console.error('[UploadProgress] 加载进度失败:', error);
    }
}

// 处理上传进度更新
function handleUploadProgressUpdate(data) {
    const { file_path, filename, uploader, progress, uploaded_bytes, total_bytes, speed, status, error } = data;

    // 更新状态
    uploadProgressState.progresses[file_path] = {
        filename,
        uploader,
        progress,
        uploaded_bytes,
        total_bytes,
        speed,
        status,
        error,
        timestamp: Date.now()
    };

    // 如果已完成或失败，5秒后移除
    if (status === 'completed' || status === 'failed') {
        setTimeout(() => {
            delete uploadProgressState.progresses[file_path];
            updateUploadProgressList();
        }, 5000);
    }

    updateUploadProgressList();
}

// 更新上传状态点
function updateUploadStatusDot(isActive) {
    const dot = document.getElementById('uploadStatusDot');
    if (dot) {
        dot.className = isActive ? 'upload-status-dot active' : 'upload-status-dot';
    }
}

// 更新上传进度列表
function updateUploadProgressList() {
    const listEl = document.getElementById('upload-progress-list');
    if (!listEl) return;

    const progresses = Object.values(uploadProgressState.progresses);
    const activeUploads = progresses.filter(p => p.status === 'uploading');

    // 更新状态点
    updateUploadStatusDot(activeUploads.length > 0);

    if (progresses.length === 0) {
        listEl.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">暂无上传任务</td></tr>`;
        return;
    }

    listEl.innerHTML = progresses.map(p => {
        // 状态标签
        let statusBadge = '';
        if (p.status === 'uploading') {
            statusBadge = '<span class="badge badge-warning">上传中</span>';
        } else if (p.status === 'completed') {
            statusBadge = '<span class="badge badge-success">已完成</span>';
        } else if (p.status === 'failed') {
            statusBadge = '<span class="badge badge-danger">失败</span>';
        }

        // 云盘标签
        const uploaderClass = `uploader-${p.uploader}`;
        const uploaderNames = {
            'cloud189': '天翼云盘',
            'yun139': '139云盘',
            'p123': '123云盘',
            'emos': 'Emos'
        };
        const uploaderName = uploaderNames[p.uploader] || p.uploader;

        // 进度条
        const progressPercent = Math.min(100, Math.max(0, p.progress || 0));
        const progressBar = `
            <div class="progress-bar-container">
                <div class="progress-bar" style="width: ${progressPercent}%"></div>
            </div>
            <div class="progress-text">${formatSize(p.uploaded_bytes || 0)} / ${formatSize(p.total_bytes || 0)}</div>
        `;

        return `
            <tr>
                <td style="font-family: monospace; font-size: 0.8125rem;">${escapeHtml(p.filename || '未知文件')}</td>
                <td><span class="uploader-badge ${uploaderClass}">${escapeHtml(uploaderName)}</span></td>
                <td style="min-width: 150px;">
                    ${progressBar}
                    <small style="color: var(--text-muted);">${progressPercent.toFixed(1)}%</small>
                </td>
                <td>${escapeHtml(p.speed || '-')}</td>
                <td>${statusBadge}${p.error ? `<br><small style="color: var(--accent-danger);">${escapeHtml(p.error)}</small>` : ''}</td>
            </tr>
        `;
    }).join('');
}
