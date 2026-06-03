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

async function fetchFirstRunCredentials() {
    try {
        const resp = await fetch(`${API_BASE}/auth/first-run-credentials`);
        const data = await resp.json();
        return data;
    } catch {
        return { has_credentials: false };
    }
}

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
    // completed.files 现在是数组对象 [{path, time}]
    const completedPaths = (completed.files || []).map(f => f.path);
    // failed.files 现在是字典 {path: {error, time}}
    const failedDict = {};
    for (const [p, v] of Object.entries(failed.files || {})) {
        failedDict[p] = v.error || '';
    }
    return {
        queued: queued.files,
        processing: processing.files,
        completed: completedPaths,
        failed: failedDict,
        _completed: completed.files,
        _failed: failed.files,
    };
}

async function loadTaskListPaginated(page = 1, pageSize = 20, status = '', search = '') {
    const params = new URLSearchParams();
    params.set('page', page);
    params.set('page_size', pageSize);
    if (status) params.set('status', status);
    if (search) params.set('search', search);
    return await apiRequest(`/tasks/list?${params.toString()}`);
}

async function loadRecentActivityPaginated(page = 1, pageSize = 20, search = '') {
    const params = new URLSearchParams();
    params.set('page', page);
    params.set('page_size', pageSize);
    if (search) params.set('search', search);
    return await apiRequest(`/tasks/recent?${params.toString()}`);
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

async function deleteConfigSectionApi(section) {
    return await apiRequest(`/config/section/${encodeURIComponent(section)}`, { method: 'DELETE' });
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

// ===== 数据库配置 API =====

async function loadManualRulesFromApi() {
    return await apiRequest('/config/db/manual-rules');
}
async function createManualRuleViaApi(data) {
    return await apiRequest('/config/db/manual-rules', { method: 'POST', body: JSON.stringify(data) });
}
async function updateManualRuleViaApi(id, data) {
    return await apiRequest(`/config/db/manual-rules/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}
async function deleteManualRuleViaApi(id) {
    return await apiRequest(`/config/db/manual-rules/${id}`, { method: 'DELETE' });
}

async function loadReleaseGroupsFromApi() {
    return await apiRequest('/config/db/release-groups');
}
async function createReleaseGroupViaApi(data) {
    return await apiRequest('/config/db/release-groups', { method: 'POST', body: JSON.stringify(data) });
}
async function updateReleaseGroupViaApi(id, data) {
    return await apiRequest(`/config/db/release-groups/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}
async function deleteReleaseGroupViaApi(id) {
    return await apiRequest(`/config/db/release-groups/${id}`, { method: 'DELETE' });
}

async function loadLlmProvidersFromApi() {
    return await apiRequest('/config/db/llm-providers');
}
async function createLlmProviderViaApi(data) {
    return await apiRequest('/config/db/llm-providers', { method: 'POST', body: JSON.stringify(data) });
}
async function updateLlmProviderViaApi(id, data) {
    return await apiRequest(`/config/db/llm-providers/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}
async function deleteLlmProviderViaApi(id) {
    return await apiRequest(`/config/db/llm-providers/${id}`, { method: 'DELETE' });
}

async function loadRuntimeConfigFromApi() {
    return await apiRequest('/config/db/runtime');
}
async function updateRuntimeConfigViaApi(key, data) {
    return await apiRequest(`/config/db/runtime/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify(data) });
}

// ===== 用户管理 API =====

async function loadUsersFromApi() {
    const r = await apiRequest('/auth/users');
    return r.users || [];
}
async function createUserViaApi(data) {
    return await apiRequest('/auth/users', { method: 'POST', body: JSON.stringify(data) });
}
async function updateUserViaApi(id, data) {
    return await apiRequest(`/auth/users/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}
async function deleteUserViaApi(id) {
    return await apiRequest(`/auth/users/${id}`, { method: 'DELETE' });
}
