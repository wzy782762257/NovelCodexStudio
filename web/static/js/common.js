// Novel Codex Studio - 公共前端框架
// 路由、状态管理、API、工具函数

const API = '/api';

// ─── State Management ─────────────────────────────────────
class AppState {
  constructor() {
    this.data = {
      project: {},
      engine: { status: 'idle', mode: 'auto', current_chapter: 0 },
      user: { name: '作者', role: 'owner' },
      notifications: [],
    };
    this.listeners = new Map();
  }

  get(key) {
    return key.split('.').reduce((obj, k) => obj?.[k], this.data);
  }

  set(key, value) {
    const keys = key.split('.');
    let obj = this.data;
    for (let i = 0; i < keys.length - 1; i++) {
      if (!obj[keys[i]]) obj[keys[i]] = {};
      obj = obj[keys[i]];
    }
    obj[keys[keys.length - 1]] = value;
    this.emit(key, value);
  }

  on(key, callback) {
    if (!this.listeners.has(key)) this.listeners.set(key, []);
    this.listeners.get(key).push(callback);
  }

  emit(key, value) {
    if (this.listeners.has(key)) {
      this.listeners.get(key).forEach(cb => cb(value));
    }
  }
}

const appState = new AppState();

// ─── API Client ───────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(API + path, opts);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error('API Error:', e);
    throw e;
  }
}

// ─── Navigation ───────────────────────────────────────────
function initNavigation() {
  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-item').forEach(item => {
    if (item.getAttribute('href')?.includes(currentPage)) {
      item.classList.add('active');
    }
  });
}

// ─── Toast System ─────────────────────────────────────────
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container') || createToastContainer();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function createToastContainer() {
  const container = document.createElement('div');
  container.id = 'toast-container';
  container.className = 'toast-container';
  document.body.appendChild(container);
  return container;
}

// ─── Modal System ─────────────────────────────────────────
function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add('active');
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.remove('active');
}

// ─── Engine Control ───────────────────────────────────────
async function startEngine(chapter) {
  try {
    const result = await api('POST', '/engine/start', { chapter, mode: appState.get('engine.mode') });
    appState.set('engine.status', 'running');
    appState.set('engine.current_chapter', chapter);
    showToast('引擎已启动', 'success');
    return result;
  } catch (e) {
    showToast(`启动失败: ${e.message}`, 'error');
    throw e;
  }
}

async function pauseEngine() {
  try {
    await api('POST', '/engine/pause');
    appState.set('engine.status', 'paused');
    showToast('引擎已暂停', 'info');
  } catch (e) {
    showToast(`暂停失败: ${e.message}`, 'error');
  }
}

async function resumeEngine() {
  try {
    await api('POST', '/engine/resume');
    appState.set('engine.status', 'running');
    showToast('引擎已继续', 'success');
  } catch (e) {
    showToast(`继续失败: ${e.message}`, 'error');
  }
}

async function stopEngine() {
  try {
    await api('POST', '/engine/stop');
    appState.set('engine.status', 'idle');
    showToast('引擎已停止', 'info');
  } catch (e) {
    showToast(`停止失败: ${e.message}`, 'error');
  }
}

// ─── Polling ──────────────────────────────────────────────
let _pollTimer = null;

function startPolling(interval = 3000) {
  if (_pollTimer) return;
  _pollTimer = setInterval(async () => {
    try {
      const status = await api('GET', '/engine/status');
      appState.set('engine', status);
      updateEngineStatusUI(status);
    } catch (e) {
      console.error('Poll error:', e);
    }
  }, interval);
}

function stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

function updateEngineStatusUI(status) {
  const el = document.getElementById('engine-status-badge');
  if (!el) return;
  el.className = `engine-status ${status.status}`;
  el.innerHTML = `<span class="dot"></span>${status.status === 'running' ? '运行中' : status.status === 'paused' ? '已暂停' : '待机'}`;
}

// ─── Helpers ────────────────────────────────────────────────
function qs(sel) { return document.querySelector(sel); }
function qsa(sel) { return document.querySelectorAll(sel); }
function on(el, ev, fn) { el.addEventListener(ev, fn); }

function formatDate(date) {
  return new Date(date).toLocaleString('zh-CN', { 
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ─── Init ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  startPolling();
});

// Export for page scripts
window.NCS = { api, appState, showToast, openModal, closeModal, startEngine, pauseEngine, resumeEngine, stopEngine, qs, qsa, on, formatDate, escapeHtml };
