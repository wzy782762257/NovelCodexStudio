// Novel Codex Studio Control Panel Frontend
// Pure JS, no frameworks. API-driven.

const API = '/api';

// ─── State ───────────────────────────────────────────────
let state = {
  activeChapter: 1,
  chapters: [],
  project: {},
  isPaused: false,
  isRunning: false,
  pollTimer: null,
  viewMode: 'write',
  direction: '',
};

// ─── Helpers ─────────────────────────────────────────────
function qs(sel) { return document.querySelector(sel); }
function qsa(sel) { return document.querySelectorAll(sel); }
function on(el, ev, fn) { el.addEventListener(ev, fn); }

function flash(msg) {
  const t = qs('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  setTimeout(() => t.classList.add('hidden'), 2400);
}

function showError(msg) {
  const existing = qs('.api-error');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.className = 'api-error';
  div.textContent = msg;
  qs('.workspace').insertBefore(div, qs('.workspace').firstChild);
  setTimeout(() => div.remove(), 5000);
}

async function api(method, path, body) {
  const opts = { method };
  if (body) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(API + path, opts);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    showError(`API 错误: ${e.message}`);
    throw e;
  }
}

// ─── Loaders ─────────────────────────────────────────────
async function loadProject() {
  state.project = await api('GET', '/project/status');
  const p = state.project;
  qs('#project-title').textContent = p.title || '未命名项目';
  qs('#project-genre').textContent = p.genre || '';
  qs('#project-target').textContent = `${p.latest_accepted_chapter || 0}章 / 约${((p.target_chapter || 0) * 2250 / 10000).toFixed(1)}万字`;
  qs('#batch-name').textContent = `批次：${p.title || '未命名'}`;
  qs('#batch-range').textContent = `1–${p.target_chapter || 10}章`;
  
  state.isPaused = p.paused;
  state.isRunning = p.running;
  updatePauseUI();
}

async function loadChapters() {
  state.chapters = await api('GET', '/chapters');
  renderChapterTrack();
  renderOutlineTree();
  updateRuntimeStats();
}

async function loadChapterContent(chapter) {
  const data = await api('GET', `/chapter/${chapter}/content`);
  qs('#chapter-title').textContent = data.content ? data.content.split('\n')[0].replace('#', '').trim() : `第${chapter}章`;
  qs('#chapter-subtitle').textContent = `第${chapter}章`;
  
  const prose = qs('#prose');
  prose.innerHTML = '';
  
  if (data.content) {
    const paragraphs = data.content.split('\n').filter(l => l.trim() && !l.trim().startsWith('#'));
    paragraphs.forEach((text, i) => {
      const row = document.createElement('div');
      row.className = 'paragraph-row';
      row.innerHTML = `<span class="paragraph-number">¶${i + 1}</span><p contenteditable="true" data-paragraph="${i + 1}">${text}</p>`;
      prose.appendChild(row);
    });
    
    // Word count (Chinese chars only)
    const chineseChars = (data.content.match(/[\u3400-\u9fff]/g) || []).length;
    qs('#word-count').textContent = chineseChars.toLocaleString();
  } else {
    prose.innerHTML = '<p style="color:#999;padding:20px">本章尚未生成。点击"生成本章"开始写作。</p>';
    qs('#word-count').textContent = '0';
  }
  
  qs('#editor-title').textContent = `第 ${chapter} 章 · ${getChapterTitle(chapter)}`;
  
  // Update buttons based on status
  updateActionButtons(chapter);
  
  // Load issues for this chapter
  await loadIssues(chapter);
  
  // Load trace
  await loadTrace(chapter);
}

function getChapterTitle(n) {
  const ch = state.chapters.find(c => c.number === n);
  return ch ? ch.title : `第${n}章`;
}

function updateActionButtons(chapter) {
  const ch = state.chapters.find(c => c.number === chapter);
  if (!ch) return;
  
  const genBtn = qs('#btn-generate');
  const regenBtn = qs('#btn-regenerate');
  
  if (ch.status === 'committed') {
    genBtn.classList.add('hidden');
    regenBtn.classList.remove('hidden');
  } else if (ch.status === 'pending') {
    genBtn.classList.remove('hidden');
    regenBtn.classList.add('hidden');
  } else {
    genBtn.classList.remove('hidden');
    regenBtn.classList.remove('hidden');
  }
}

async function loadIssues(chapter) {
  try {
    const issues = await api('GET', `/chapter/${chapter}/issues`);
    renderIssues(issues);
  } catch (e) {
    renderIssues([]);
  }
}

async function loadTrace(chapter) {
  const rows = qs('#trace-rows');
  rows.innerHTML = '';
  
  try {
    const logs = await api('GET', '/logs');
    let chapterEvents = [];
    
    logs.forEach(log => {
      if (log.file.includes(`chapter-${chapter.toString().padStart(4, '0')}`)) {
        log.entries.forEach(entry => {
          chapterEvents.push({
            step: entry.step,
            status: entry.status,
            time: entry.at,
            data: entry.data,
          });
        });
      }
    });
    
    // Sort by time
    chapterEvents.sort((a, b) => new Date(a.time) - new Date(b.time));
    
    const stepDefinitions = [
      { key: 'contracts', name: '契约提取', desc: '从大纲提取章节契约', color: 'green' },
      { key: 'context_packet', name: '上下文打包', desc: '构建章节上下文包', color: 'green' },
      { key: 'prewrite', name: 'Prewrite 门禁', desc: '章节契约与前置状态校验', color: 'cyan' },
      { key: 'write', name: '正文生成', desc: 'AI 生成章节正文', color: 'green' },
      { key: 'review', name: '质量审查', desc: 'Nacharium 5角色审查 + AI痕迹检查', color: 'violet' },
      { key: 'revise', name: '修订', desc: '对抗性编辑修订', color: 'cyan' },
      { key: 'elevate', name: 'Elevate', desc: '提升质量到统一水平', color: 'violet' },
      { key: 'fulfillment', name: 'Fulfillment 检查', desc: '节点覆盖验证', color: 'cyan' },
      { key: 'save_chapter', name: '保存正文', desc: '保存章节到文件', color: 'blue' },
      { key: 'artifacts', name: '产物生成', desc: '审查产物与提取', color: 'blue' },
      { key: 'precommit', name: 'Precommit 门禁', desc: '提交前状态校验', color: 'cyan' },
      { key: 'commit', name: 'Chapter Commit', desc: '状态更新与事实库同步', color: 'blue' },
      { key: 'postcommit', name: 'Postcommit 门禁', desc: '提交后验证', color: 'blue' },
    ];
    
    if (chapterEvents.length === 0) {
      rows.innerHTML = '<div style="color: #5f7380; padding: 12px; font-size: 10px;">暂无生产轨迹数据</div>';
      return;
    }
    
    stepDefinitions.forEach(step => {
      const event = chapterEvents.find(e => e.step === step.key);
      const icon = event ? (event.status === 'ok' || event.status === 'pass' ? '✓' : event.status === 'fail' ? '✗' : '⟳') : '○';
      const color = event ? (event.status === 'ok' || event.status === 'pass' ? step.color : event.status === 'fail' ? 'red' : 'amber') : 'muted';
      const time = event ? new Date(event.time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '--';
      
      const row = document.createElement('div');
      row.className = 'trace-row';
      row.innerHTML = `
        <span class="trace-icon ${color}">${icon}</span>
        <div><strong>${step.name}</strong><small>${step.desc}</small></div>
        <span>${time}</span><span>${event ? event.status : '--'}</span>
      `;
      rows.appendChild(row);
    });
    
  } catch (e) {
    rows.innerHTML = '<div style="color: #5f7380; padding: 12px; font-size: 10px;">暂无生产轨迹数据</div>';
  }
}

async function loadDirection() {
  const data = await api('GET', '/direction');
  qs('#direction-text').value = data.direction || '';
  qs('#direction-count').textContent = `${data.direction.length}/1000`;
}

// ─── Renderers ───────────────────────────────────────────
function renderChapterTrack() {
  const track = qs('#chapter-track');
  track.innerHTML = '';
  
  state.chapters.forEach(ch => {
    const btn = document.createElement('button');
    btn.className = `chapter-step ${ch.status} ${state.activeChapter === ch.number ? 'selected' : ''}`;
    btn.innerHTML = `
      <span class="chapter-index">${ch.number}</span>
      <span class="chapter-name">${ch.title}</span>
      <span class="chapter-state">${statusIcon(ch.status)} ${statusText(ch.status)}</span>
    `;
    on(btn, 'click', () => selectChapter(ch.number));
    track.appendChild(btn);
  });
}

function statusIcon(status) {
  if (status === 'committed') return '✓';
  if (status === 'active') return '◎';
  if (status === 'working') return '⟳';
  return '○';
}

function statusText(status) {
  if (status === 'committed') return '已批准';
  if (status === 'active') return '终审中';
  if (status === 'working') return '生成中';
  if (status === 'draft') return '草稿';
  return '排队中';
}

function renderOutlineTree() {
  const tree = qs('#outline-tree');
  tree.innerHTML = '';
  
  const heading = document.createElement('div');
  heading.className = 'tree-heading';
  heading.innerHTML = '▼ 第一卷';
  tree.appendChild(heading);
  
  state.chapters.forEach(ch => {
    const item = document.createElement('button');
    item.className = `tree-item ${state.activeChapter === ch.number ? 'active' : ''}`;
    item.innerHTML = `<span>${ch.number}</span>${ch.title}`;
    on(item, 'click', () => selectChapter(ch.number));
    tree.appendChild(item);
  });
}

function renderIssues(issues) {
  const list = qs('#issue-list');
  const empty = qs('#empty-issues');
  const count = qs('#issue-count');
  
  count.textContent = issues.length;
  
  if (issues.length === 0) {
    list.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  
  empty.classList.add('hidden');
  list.innerHTML = '';
  
  issues.forEach(issue => {
    const article = document.createElement('article');
    article.className = `issue ${issue.tone}`;
    article.innerHTML = `
      <div class="issue-top">
        <span>⚠</span>
        <h3>${issue.title}</h3>
        <span>${issue.level}</span>
      </div>
      <p class="anchor">关联段落：${issue.paragraph}</p>
      <p>${issue.body}</p>
      <div class="issue-actions">
        <button>跳到正文</button>
        <button>允许自动修复</button>
        <button>修改方向</button>
      </div>
    `;
    list.appendChild(article);
  });
}

function updatePauseUI() {
  const status = qs('#pause-status');
  const desc = qs('#pause-desc');
  const sw = qs('#pause-switch');
  
  if (state.isPaused) {
    status.textContent = '批次已暂停';
    desc.textContent = '不会继续生成后续章节';
    sw.classList.add('off');
  } else {
    status.textContent = state.isRunning ? '批量生成已启动' : '批量生成就绪';
    desc.textContent = state.isRunning ? '正在生成中...' : '可随时启动';
    sw.classList.remove('off');
  }
}

function updateRuntimeStats() {
  const committed = state.chapters.filter(c => c.status === 'committed').length;
  const total = state.chapters.length;
  const pct = Math.round((committed / total) * 100);
  
  qs('#runtime-stats').innerHTML = `
    <span>已批准：${committed} 章</span>
    <span>总计：${total} 章</span>
    <span>进度：${committed}/${total}章（${pct}%）</span>
  `;
  
  qs('#cost-summary').innerHTML = `💰 <span>本批总消耗 <strong>--</strong></span>`;
}

// ─── Actions ─────────────────────────────────────────────
async function selectChapter(n) {
  state.activeChapter = n;
  renderChapterTrack();
  renderOutlineTree();
  await loadChapterContent(n);
}

async function generateChapter() {
  const n = state.activeChapter;
  flash(`正在生成第 ${n} 章...`);
  
  try {
    const result = await api('POST', `/chapter/${n}/generate`);
    if (result.ok) {
      flash(`第 ${n} 章生成任务已启动 (PID: ${result.pid})`);
      state.isRunning = true;
      updatePauseUI();
      startPolling();
    } else {
      flash(`生成失败: ${result.error}`);
    }
  } catch (e) {
    flash(`生成失败: ${e.message}`);
  }
}

async function approveChapter() {
  const n = state.activeChapter;
  try {
    await api('POST', `/chapter/${n}/approve`);
    flash(`第 ${n} 章已批准`);
    await loadChapters();
    await loadChapterContent(n);
  } catch (e) {
    flash(`批准失败: ${e.message}`);
  }
}

async function rejectChapter() {
  const n = state.activeChapter;
  try {
    await api('POST', `/chapter/${n}/reject`);
    flash(`第 ${n} 章已退回`);
    await loadChapters();
  } catch (e) {
    flash(`退回失败: ${e.message}`);
  }
}

async function togglePause() {
  if (state.isPaused) {
    await api('POST', '/batch/resume');
    state.isPaused = false;
    flash('批次已继续');
  } else {
    await api('POST', '/batch/pause');
    state.isPaused = true;
    flash('批次已暂停');
  }
  updatePauseUI();
}

async function saveDirection() {
  const text = qs('#direction-text').value;
  await api('POST', '/direction', { direction: text });
  flash('方向已保存');
}

async function emergencyStop() {
  try {
    const result = await api('POST', '/batch/stop');
    if (result.killed) {
      flash('已强制停止运行中的引擎');
    } else {
      flash('已停止（无运行中的引擎）');
    }
    state.isRunning = false;
    state.isPaused = false;
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    updatePauseUI();
    await loadChapters();
  } catch (e) {
    flash(`停止失败: ${e.message}`);
  }
}

async function fetchLiveLog() {
  try {
    const data = await api('GET', '/engine/log');
    const logPanel = qs('#live-log');
    if (logPanel && data.lines) {
      logPanel.innerHTML = data.lines.map(l => `<div>${escapeHtml(l)}</div>`).join('');
      logPanel.scrollTop = logPanel.scrollHeight;
    }
  } catch (e) {
    // Silently ignore log fetch errors
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function saveContent() {
  const n = state.activeChapter;
  const paragraphs = qsa('#prose p');
  const content = Array.from(paragraphs).map(p => p.textContent).join('\n');
  
  await api('PUT', `/chapter/${n}/content`, { content });
  qs('#save-status').textContent = '✓ 已保存';
  setTimeout(() => qs('#save-status').textContent = '✓ 已自动保存', 2000);
  
  // Update word count
  const chineseChars = (content.match(/[\u3400-\u9fff]/g) || []).length;
  qs('#word-count').textContent = chineseChars.toLocaleString();
}

// ─── Polling ─────────────────────────────────────────────
function startPolling() {
  if (state.pollTimer) return;
  
  state.pollTimer = setInterval(async () => {
    // Poll chapter status
    const st = await api('GET', `/chapter/${state.activeChapter}/status`);
    
    // Poll live log
    await fetchLiveLog();
    
    if (!st.running) {
      state.isRunning = false;
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      updatePauseUI();
      await loadChapters();
      await loadChapterContent(state.activeChapter);
      flash('生成完成');
    } else {
      // Still running, show progress
      qs('#save-status').textContent = `⟳ 生成中... (PID: ${st.engine_pid || '--'}, ${st.engine_elapsed || 0}s)`;
    }
  }, 3000);  // Poll every 3 seconds
}

// ─── Event Bindings ──────────────────────────────────────
function bindEvents() {
  on(qs('#pause-switch'), 'click', togglePause);
  on(qs('#btn-stop-all'), 'click', emergencyStop);
  
  on(qs('#btn-generate'), 'click', generateChapter);
  on(qs('#btn-regenerate'), 'click', generateChapter);
  
  on(qs('#btn-approve'), 'click', approveChapter);
  on(qs('#btn-approve-batch'), 'click', () => flash('批量批准功能开发中'));
  on(qs('#btn-return'), 'click', rejectChapter);
  on(qs('#btn-replan'), 'click', () => flash('重新规划功能开发中'));
  
  on(qs('#btn-save-direction'), 'click', saveDirection);
  on(qs('#btn-clear-direction'), 'click', () => {
    qs('#direction-text').value = '';
    qs('#direction-count').textContent = '0/1000';
  });
  
  on(qs('#direction-text'), 'input', (e) => {
    qs('#direction-count').textContent = `${e.target.value.length}/1000`;
  });
  
  // View tabs
  qsa('.view-tabs button').forEach(btn => {
    on(btn, 'click', () => {
      qsa('.view-tabs button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.viewMode = btn.dataset.view;
      qs('#manuscript').classList.toggle('reading', state.viewMode === 'read');
    });
  });
  
  // Trace toggle
  on(qs('#trace-toggle'), 'click', () => {
    qs('#trace-section').classList.toggle('collapsed');
    const arrow = qs('#trace-toggle');
    arrow.innerHTML = arrow.innerHTML.includes('▼') 
      ? '<span>生产轨迹 <small>已折叠</small></span>▶' 
      : '<span>生产轨迹 <small>可折叠</small></span>▼';
  });
  
  // Top buttons
  on(qs('#btn-global-settings'), 'click', showGlobalSettings);
  on(qs('#btn-batch-settings'), 'click', showBatchSettings);
  on(qs('#btn-export'), 'click', showExport);
  
  // Clear log
  on(qs('#btn-clear-log'), 'click', () => {
    qs('#live-log').innerHTML = '<div style="color: #3b5a7a;">日志已清空</div>';
  });
  
  // Auto-save on content edit (debounced)
  let saveTimer;
  on(qs('#prose'), 'input', () => {
    qs('#save-status').textContent = '... 保存中';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveContent, 2000);
  });
  
  // Keyboard shortcuts
  on(document, 'keydown', (e) => {
    if (e.ctrlKey && e.key === 's') {
      e.preventDefault();
      saveContent();
    }
  });
}

async function loadCharacters() {
  try {
    const chars = await api('GET', '/characters');
    const container = qs('#characters');
    container.innerHTML = '';
    
    if (chars.length === 0) {
      container.innerHTML = '<p style="color: #5f7380; font-size: 10px; padding: 8px;">暂无角色数据</p>';
      return;
    }
    
    chars.forEach(ch => {
      const div = document.createElement('div');
      div.className = 'character';
      div.innerHTML = `
        <span class="sigil ${ch.color}">${ch.name.charAt(0)}</span>
        <div>
          <strong>${ch.name}</strong>
          <small>${ch.role}</small>
        </div>
      `;
      container.appendChild(div);
    });
  } catch (e) {
    qs('#characters').innerHTML = '<p style="color: #5f7380; font-size: 10px; padding: 8px;">加载角色失败</p>';
  }
}

async function loadClues() {
  try {
    const clues = await api('GET', '/clues');
    const container = qs('#clues');
    container.innerHTML = '';
    
    if (clues.length === 0) {
      container.innerHTML = '<li>暂无伏笔数据</li>';
      return;
    }
    
    clues.forEach(c => {
      const li = document.createElement('li');
      li.textContent = c.chapter > 0 ? `[第${c.chapter}章] ${c.text}` : c.text;
      container.appendChild(li);
    });
  } catch (e) {
    qs('#clues').innerHTML = '<li>加载伏笔失败</li>';
  }
}

// ─── Settings Modals ─────────────────────────────────────
function createModal(id, title, content) {
  if (qs(`#${id}`)) return;
  
  const modal = document.createElement('div');
  modal.id = id;
  modal.style.cssText = `
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,.6); z-index: 50; display: flex;
    align-items: center; justify-content: center;
  `;
  modal.innerHTML = `
    <div style="background: #0d171e; border: 1px solid #24313a; border-radius: 6px; width: 480px; max-height: 70vh; overflow: auto;">
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #24313a;">
        <strong style="color: #dce5ed; font-size: 13px;">${title}</strong>
        <button onclick="this.closest('#${id}').remove()" style="background: transparent; border: 0; color: #7f919e; cursor: pointer; font-size: 16px;">×</button>
      </div>
      <div style="padding: 16px; color: #aab8c2; font-size: 12px; line-height: 1.6;">
        ${content}
      </div>
    </div>
  `;
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });
  document.body.appendChild(modal);
}

function showGlobalSettings() {
  createModal('modal-global', '全局设置', `
    <p>全局配置通过编辑 <code style="background: #111d25; padding: 2px 6px; border-radius: 3px;">config.json</code> 修改。</p>
    <p style="margin-top: 12px; color: #7f919e;">关键配置项：</p>
    <ul style="margin: 8px 0; padding-left: 18px; color: #7f919e;">
      <li>model_name: 模型名称</li>
      <li>max_tokens: 最大生成token数</li>
      <li>batch_size: 批量生成章节数</li>
      <li>api_key: API密钥</li>
    </ul>
    <p style="margin-top: 12px; color: #5f7380;">修改后重启引擎生效。</p>
  `);
}

function showBatchSettings() {
  createModal('modal-batch', '批次设置', `
    <p>批次配置同样通过 <code style="background: #111d25; padding: 2px 6px; border-radius: 3px;">config.json</code> 管理。</p>
    <p style="margin-top: 12px; color: #7f919e;">当前批次参数：</p>
    <ul style="margin: 8px 0; padding-left: 18px; color: #7f919e;">
      <li>起始章节：第 ${state.activeChapter} 章</li>
      <li>目标章节：${state.project.target_chapter || 10} 章</li>
      <li>生成模式：单章连续</li>
    </ul>
  `);
}

function showExport() {
  createModal('modal-export', '导出报告', `
    <p>导出功能将生成项目完整报告，包括：</p>
    <ul style="margin: 8px 0; padding-left: 18px; color: #7f919e;">
      <li>全部章节正文（Markdown）</li>
      <li>角色设定汇总</li>
      <li>生产轨迹记录</li>
      <li>质量评分统计</li>
    </ul>
    <p style="margin-top: 12px; color: #5f7380;">功能开发中，敬请期待。</p>
  `);
}

// ─── Init ────────────────────────────────────────────────
async function init() {
  bindEvents();
  await loadProject();
  await loadChapters();
  await loadDirection();
  await loadCharacters();
  await loadClues();
  await loadChapterContent(state.activeChapter);
  
  // Start live log polling (always runs)
  setInterval(fetchLiveLog, 3000);
  
  // Check if engine is running
  if (state.isRunning) {
    startPolling();
  }
}

init();
