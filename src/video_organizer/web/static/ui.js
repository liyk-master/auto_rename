function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function formatSize(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

class Path {
    constructor(pathStr) { this.path = pathStr; }
    get basename() { const p = this.path.split(/[/\\]/); return p[p.length - 1]; }
    get dirname() { const p = this.path.split(/[/\\]/); return p.slice(0, -1).join('/'); }
    get extname() { const idx = this.basename.lastIndexOf('.'); return idx >= 0 ? this.basename.slice(idx) : ''; }
}

function classifyLogLine(line) {
    let cls = 'log-line';
    if (line.includes(' ERROR ')) cls += ' error';
    else if (line.includes(' WARNING ')) cls += ' warning';
    else if (line.includes(' INFO ')) cls += ' info';
    return cls;
}

// ===== 登录页面 =====

async function checkFirstRunCredentials() {
    const banner = document.getElementById('firstRunBanner');
    if (!banner) return;
    try {
        const data = await fetchFirstRunCredentials();
        if (data.has_credentials) {
            document.getElementById('frUsername').textContent = data.username;
            document.getElementById('frPassword').textContent = data.password;
            banner.style.display = 'flex';
        }
    } catch {}
}

function dismissFirstRun() {
    const banner = document.getElementById('firstRunBanner');
    if (banner) banner.style.display = 'none';
}

function showLoginPage(errorMsg) {
    const appEl = document.getElementById('app');
    const loginEl = document.getElementById('login-page');
    if (appEl) appEl.style.display = 'none';
    if (loginEl) {
        loginEl.style.display = 'flex';
        const errorEl = loginEl.querySelector('.login-error');
        if (errorEl) {
            errorEl.textContent = errorMsg || '';
            errorEl.style.display = errorMsg ? 'block' : 'none';
        }
        const pwdInput = loginEl.querySelector('#loginPassword');
        if (pwdInput) pwdInput.value = '';
    }
    checkFirstRunCredentials();
}

function hideLoginPage() {
    const appEl = document.getElementById('app');
    const loginEl = document.getElementById('login-page');
    if (appEl) appEl.style.display = '';
    if (loginEl) loginEl.style.display = 'none';
}

async function handleLogin(event) {
    event.preventDefault();
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const btn = document.getElementById('loginBtn');
    const errorEl = document.querySelector('.login-error');

    if (!username || !password) {
        if (errorEl) { errorEl.textContent = '请输入用户名和密码'; errorEl.style.display = 'block'; }
        return;
    }

    btn.disabled = true;
    btn.textContent = '登录中...';

    try {
        const resp = await loginApi(username, password);
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || '登录失败');
        }
        setAuthToken(data.access_token);
        dismissFirstRun();
        hideLoginPage();
        initApp();
    } catch (e) {
        if (errorEl) { errorEl.textContent = e.message; errorEl.style.display = 'block'; }
    } finally {
        btn.disabled = false;
        btn.textContent = '登 录';
    }
}

async function handleLogout() {
    clearAuthToken();
    showLoginPage('已退出登录');
}

// ===== Toast 队列机制 =====
const toastQueue = { queue: [], isProcessing: false };

function showToast(message, type = 'info') {
    toastQueue.queue.push({ message, type });
    if (!toastQueue.isProcessing) processToastQueue();
}

function processToastQueue() {
    if (toastQueue.queue.length === 0) {
        toastQueue.isProcessing = false;
        return;
    }
    toastQueue.isProcessing = true;
    const { message, type } = toastQueue.queue.shift();

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = {
        success: '<path d="M20 6L9 17l-5-5"/>',
        error: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
        warning: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
        info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'
    };
    toast.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${icons[type] || icons.info}</svg><span>${escapeHtml(message)}</span>`;

    const container = document.getElementById('toastContainer');
    if (container) {
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('removing');
            setTimeout(() => { toast.remove(); processToastQueue(); }, 300);
        }, 3000);
    } else {
        processToastQueue();
    }
}

// ===== 模态框 =====
let modalConfirmCallback = null;

function showModal() {
    const overlay = document.getElementById('modalOverlay');
    if (overlay) overlay.classList.add('show');
}

function hideModal() {
    const overlay = document.getElementById('modalOverlay');
    if (overlay) overlay.classList.remove('show');
    modalConfirmCallback = null;
}

function showConfirm(title, message, onConfirm, confirmText) {
    const elTitle = document.getElementById('modalTitle');
    const elBody = document.getElementById('modalBody');
    const elFooter = document.getElementById('modalFooter');
    const elConfirm = document.getElementById('modalConfirmBtn');
    const elCancel = document.getElementById('modalCancelBtn');

    if (elTitle) elTitle.textContent = title;
    if (elBody) elBody.innerHTML = `<p>${escapeHtml(message)}</p>`;
    if (elFooter) elFooter.style.display = 'flex';
    if (elConfirm) {
        elConfirm.textContent = confirmText || '确认';
        elConfirm.onclick = () => { hideModal(); if (onConfirm) onConfirm(); };
    }
    if (elCancel) elCancel.onclick = hideModal;
    showModal();
}

// ===== 加载状态指示器 =====
function showLoading(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (container.querySelector('.loading-overlay')) return;
    const overlay = document.createElement('div');
    overlay.className = 'loading-overlay';
    overlay.innerHTML = '<div class="spinner"></div>';
    container.appendChild(overlay);
}

function hideLoading(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const overlay = container.querySelector('.loading-overlay');
    if (overlay) overlay.remove();
}

function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        btn.disabled = true;
        btn.dataset.origText = btn.textContent;
        btn.innerHTML = '<span class="btn-spinner"></span> 处理中...';
    } else {
        btn.disabled = false;
        if (btn.dataset.origText) btn.textContent = btn.dataset.origText;
    }
}

// ===== 主题切换系统 =====
const THEME_KEY = 'app_theme';

function getSavedTheme() {
    return localStorage.getItem(THEME_KEY) || 'midnight';
}

function applyTheme(themeName) {
    document.documentElement.setAttribute('data-theme', themeName);
    localStorage.setItem(THEME_KEY, themeName);
    document.querySelectorAll('.theme-dot').forEach(dot => {
        dot.classList.toggle('active', dot.dataset.theme === themeName);
    });
}

function initThemeSwitcher() {
    const saved = getSavedTheme();
    applyTheme(saved);
    document.querySelectorAll('.theme-dot').forEach(dot => {
        dot.addEventListener('click', () => applyTheme(dot.dataset.theme));
    });
}

function initThemeOnLoginPage() {
    const saved = getSavedTheme();
    document.documentElement.setAttribute('data-theme', saved);
}
