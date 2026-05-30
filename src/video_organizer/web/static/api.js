const API_BASE = '/api';

const AUTH_KEY = 'auth_token';

function getAuthToken() { return localStorage.getItem(AUTH_KEY); }
function setAuthToken(token) { localStorage.setItem(AUTH_KEY, token); }
function clearAuthToken() { localStorage.removeItem(AUTH_KEY); }
function isAuthenticated() { return !!getAuthToken(); }

async function apiRequest(endpoint, options = {}) {
    const token = getAuthToken();
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE}${endpoint}`, {
        headers,
        ...options
    });
    if (response.status === 401) {
        clearAuthToken();
        showLoginPage();
        throw new Error('登录已过期，请重新登录');
    }
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || error.message || '请求失败');
    }
    const ct = response.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
        return await response.json();
    }
    return await response.text();
}

// ===== 认证 API =====

async function loginApi(username, password) {
    return await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    });
}

async function checkAuthApi() {
    const token = getAuthToken();
    if (!token) return false;
    try {
        await apiRequest('/auth/me');
        return true;
    } catch {
        clearAuthToken();
        return false;
    }
}

// ===== 业务 API =====

async function loadStatusFromApi() {
    return await apiRequest('/status');
}

async function loadTasksFromApi() {
    const [queued, processing, completed, failed] = await Promise.all([
        apiRequest('/tasks/queued'),
        apiRequest('/tasks/processing'),
        apiRequest('/tasks/completed'),
        apiRequest('/tasks/failed')
    ]);
    return { queued: queued.files, processing: processing.files, completed: completed.files, failed: failed.files };
}

async function loadConfigFromApi() {
    const result = await apiRequest('/config');
    return result.config;
}

async function reloadConfigViaApi() {
    return await apiRequest('/config/reload', { method: 'POST' });
}

async function saveConfigToApi(section, values) {
    return await apiRequest('/config/section', {
        method: 'PUT',
        body: JSON.stringify({ section, values })
    });
}

async function loadLogFilesFromApi() {
    return await apiRequest('/logs/files');
}

async function loadLogContentFromApi(filename) {
    const token = getAuthToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch(`${API_BASE}/logs/content/${encodeURIComponent(filename)}?lines=200`, { headers });
    if (!resp.ok) throw new Error('加载日志失败');
    return await resp.text();
}

async function browsePathFromApi(path) {
    return await apiRequest(`/manual/browse?path=${encodeURIComponent(path || '')}`);
}

async function processFileViaApi(filePath, force) {
    return await apiRequest('/manual/process', {
        method: 'POST',
        body: JSON.stringify({ file_path: filePath, force })
    });
}

async function previewFileViaApi(filePath) {
    return await apiRequest('/manual/preview', {
        method: 'POST',
        body: JSON.stringify({ file_path: filePath })
    });
}

async function scanDirectoryViaApi(directory, recursive) {
    return await apiRequest('/manual/scan', {
        method: 'POST',
        body: JSON.stringify({ directory, recursive })
    });
}

async function validateScrapeViaApi(filePath) {
    return await apiRequest('/manual/validate', {
        method: 'POST',
        body: JSON.stringify({ file_path: filePath })
    });
}

async function processBatchViaApi(files) {
    return await apiRequest('/manual/process-batch', {
        method: 'POST',
        body: JSON.stringify(files)
    });
}

async function loadDownloadersFromApi() {
    return await apiRequest('/downloaders');
}

async function retryTaskViaApi(filePath) {
    return await apiRequest('/tasks/retry', {
        method: 'POST',
        body: JSON.stringify({ file_path: filePath })
    });
}

async function clearFailedTaskViaApi(filePath) {
    return await apiRequest(`/tasks/failed/${encodeURIComponent(filePath)}`, { method: 'DELETE' });
}

async function clearAllFailedViaApi() {
    return await apiRequest('/tasks/failed', { method: 'DELETE' });
}

async function retryAllFailedViaApi() {
    return await apiRequest('/tasks/retry-all', { method: 'POST' });
}

async function loadUploadProgressFromApi() {
    return await apiRequest('/tasks/progress');
}
