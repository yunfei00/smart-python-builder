let job, generation = 0;
const $ = id => document.getElementById(id);
const states = {READY:'等待项目', QUEUED:'已进入构建队列', BUILDING:'正在生成 Windows 应用', AI_DIAGNOSING:'构建遇到问题，AI 正在诊断', AI_REPAIRING:'AI 已找到方案，正在准备修复', REBUILDING:'修复完成，正在重新构建', SUCCESS:'应用已生成', FAILED:'构建未完成', NEEDS_MANUAL_REVIEW:'需要进一步检查', EXPIRED:'构建文件已过期', CANCELING:'正在取消构建', CANCELED:'构建已取消'};
const progress = {READY:0, QUEUED:18, BUILDING:58, AI_DIAGNOSING:66, AI_REPAIRING:74, REBUILDING:84, SUCCESS:100, FAILED:100, NEEDS_MANUAL_REVIEW:100, EXPIRED:100, CANCELING:70, CANCELED:0};
function clearError() {
  $('error').textContent = '';
}
function showError(message) {
  $('error').textContent = message || '操作失败，请重试';
  $('error').scrollIntoView({behavior:'smooth', block:'nearest'});
}
function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
function renderSelectedFile() {
  const input = $('upload-file');
  const label = $('upload-file-label');
  if (!input || !label) return;
  const file = input.files?.[0];
  if (!file) {
    label.textContent = '选择 .py / .zip 文件';
    label.classList.remove('has-file');
    label.title = '';
    return;
  }
  label.textContent = file.name + ' · ' + formatFileSize(file.size);
  label.classList.add('has-file');
  label.title = file.name;
}
async function api(url, options = {}) {
  const csrf = document.querySelector('meta[name="user-csrf"]')?.content;
  const method = (options.method || 'GET').toUpperCase();
  if (csrf && !['GET','HEAD','OPTIONS'].includes(method)) {
    const headers = new Headers(options.headers || {});
    headers.set('X-CSRF-Token', csrf);
    options = {...options, headers};
  }
  const response = await fetch(url, options), data = await response.json();
  if (!response.ok) throw Error(data.detail || '操作失败');
  return data;
}
function renderStatus(value) {
  const ready = value.status === 'SUCCESS' && value.terminal === true && value.artifact_available === true;
  const failed = ['FAILED','NEEDS_MANUAL_REVIEW','EXPIRED'].includes(value.status);
  const active = ['QUEUED','BUILDING','AI_DIAGNOSING','AI_REPAIRING','REBUILDING','CANCELING'].includes(value.status);
  const cancel = $('cancel-build');
  if (cancel) {
    const loggedIn = Boolean(document.querySelector('meta[name="user-csrf"]')?.content);
    cancel.hidden = !active || !loggedIn;
    cancel.disabled = value.status === 'CANCELING';
    cancel.textContent = value.status === 'CANCELING' ? '正在取消…' : '取消当前构建';
  }
  $('download').disabled = !ready;
  $('download').textContent = ready ? '下载 Windows 应用 ↓' : '下载应用（构建完成后可用）';
  $('download').onclick = ready ? () => { window.location.href = '/api/jobs/' + encodeURIComponent(value.id) + '/download'; } : null;
  $('status').textContent = ready ? 'Windows 应用生成成功' : (states[value.status] || value.status);
  $('status').classList.toggle('success', ready);
  $('progress').classList.toggle('is-success', ready);
  $('progress').classList.toggle('is-failed', failed);
  const bar = document.querySelector('.build-track span');
  if (bar) bar.style.width = (progress[value.status] ?? 12) + '%';
}
function renderCurrentProject(value) {
  const card = $('current-project');
  if (!card || !value) return;
  const github = value.source_type === 'github';
  const projectName = value.project_name || (github ? 'GitHub project' : 'Python project');
  const source = github
    ? 'GitHub · ' + (value.repository_url || '公开仓库') + (value.repository_ref ? ' · ' + value.repository_ref : ' · 默认分支')
    : '本地上传 · ' + (value.upload_filename || projectName);
  const entryCount = Array.isArray(value.entries) ? value.entries.length : 0;
  const depCount = Array.isArray(value.dependencies) ? value.dependencies.length : 0;
  $('current-project-icon').textContent = github ? 'GH' : 'PY';
  $('current-project-name').textContent = projectName;
  $('current-project-source').textContent = source;
  $('current-project-entry').textContent = value.entry ? '入口：' + value.entry : '检测到可运行入口：' + entryCount + ' 个';
  $('current-project-deps').textContent = '依赖：' + depCount + ' 项';
  card.hidden = false;
  if ($('builder-step-title')) $('builder-step-title').textContent = '当前 Python 项目';
  if ($('builder-step-subtitle')) $('builder-step-subtitle').textContent = '项目已导入并完成分析，可以继续确认构建配置。';
  if ($('import-options')) $('import-options').hidden = true;
  if ($('import-note')) $('import-note').hidden = true;
}
function showProject(next, current) {
  if (current !== generation) return;
  clearError();
  renderCurrentProject(next);
  job = next; $('ids').textContent = '项目分析完成 · 任务 ' + job.id; $('log').textContent = '等待构建开始。';
  $('project').hidden = false; $('progress').hidden = false; $('entry').replaceChildren();
  const details = Array.isArray(job.entry_details) ? job.entry_details : [];
  const recommended = details.filter(item => item.recommended);
  const others = details.filter(item => !item.recommended);
  const entryList = $('entry-list');
  if (entryList) {
    entryList.replaceChildren();
    const addEntries = (label, items, checked) => {
      if (!items.length) return;
      const group = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = label;
      group.appendChild(title);
      for (const item of items) {
        const row = document.createElement('label');
        row.className = 'entry-choice';
        const input = document.createElement('input');
        input.type = 'checkbox'; input.name = 'build-entry'; input.value = item.path; input.checked = checked;
        input.addEventListener('change', preview);
        row.append(input, document.createTextNode(' ' + item.path + (item.app_type === 'gui' ? ' · GUI' : ' · CLI')));
        group.appendChild(row);
      }
      entryList.appendChild(group);
    };
    if (details.length) {
      addEntries('推荐构建程序（' + recommended.length + '）', recommended, true);
      addEntries('其他可运行脚本（' + others.length + '）', others, false);
    } else {
      addEntries('程序入口', job.entries.map(path => ({path, app_type:'cli'})), job.entries.length === 1);
    }
  }
  $('entry').replaceChildren();
  for (const value of job.entries) $('entry').add(new Option(value, value));
  $('dependencies').textContent = '✓ 依赖：' + (job.dependencies.join(', ') || '无需额外依赖');
  if (details.length > 1) $('type').textContent = '✓ 检测到 ' + recommended.length + ' 个推荐构建程序，另有 ' + others.length + ' 个辅助/内部入口';
  else if (job.entries.length <= 1) $('type').textContent = '✓ 应用类型：' + (job.plan?.app_type === 'gui' ? '图形界面应用' : '控制台应用 / 待选择入口');
  $('plan').textContent = JSON.stringify(job.plan, null, 2); $('build').disabled = false;
  const loggedIn = Boolean(document.querySelector('meta[name="user-csrf"]')?.content);
  $('build').textContent = loggedIn ? '生成 Windows 应用 →' : '登录后生成 Windows 应用 →';
  if ($('build-auth-note')) $('build-auth-note').hidden = loggedIn;
  $('project').scrollIntoView({behavior:'smooth', block:'center'});
}
function beginImport() {
  const current = ++generation;
  clearError(); $('project').hidden = true; $('progress').hidden = true;
  if ($('current-project')) $('current-project').hidden = true;
  if ($('builder-step-title')) $('builder-step-title').textContent = '导入你的 Python 项目';
  if ($('builder-step-subtitle')) $('builder-step-subtitle').textContent = '选择本地项目，或直接从公开 GitHub 仓库导入。';
  if ($('import-options')) $('import-options').hidden = false;
  if ($('import-note')) $('import-note').hidden = false;
  $('progress').classList.remove('is-success', 'is-failed');
  $('ids').textContent = '正在分析项目结构和依赖…';
  renderStatus({status:'READY'});
  return current;
}
$('upload').onsubmit = async event => {
  event.preventDefault();
  const current = beginImport();
  try { showProject(await api('/api/uploads', {method:'POST', body:new FormData(event.target)}), current); }
  catch (error) {
    if (current !== generation) return;
    $('ids').textContent = '项目导入失败 · 请修改后重试';
    showError(error.message);
  }
};
$('github-import').onsubmit = async event => {
  event.preventDefault();
  const current = beginImport();
  const form = $('github-import');
  const button = $('github-import-button');
  const status = $('github-import-status');
  const url = $('github-url');
  const ref = $('github-ref');
  form.classList.add('is-loading');
  button.disabled = true;
  button.textContent = '正在导入…';
  url.readOnly = true;
  ref.readOnly = true;
  status.hidden = false;
  try {
    const payload = {url:url.value, ref:ref.value || null};
    showProject(await api('/api/repositories', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}), current);
  } catch (error) {
    if (current !== generation) return;
    $('ids').textContent = 'GitHub 导入失败 · 请查看下方诊断信息';
    showError(error.message);
  } finally {
    if (current === generation) {
      form.classList.remove('is-loading');
      button.disabled = false;
      button.textContent = '导入并分析';
      url.readOnly = false;
      ref.readOnly = false;
      status.hidden = true;
    }
  }
};
$('build').onclick = async () => {
  const current = generation;
  clearError();
  const selectedEntries = [...document.querySelectorAll('input[name="build-entry"]:checked')].map(input => input.value);
  if (!selectedEntries.length) {
    showError('请至少选择一个程序入口');
    return;
  }
  const loggedIn = Boolean(document.querySelector('meta[name="user-csrf"]')?.content);
  if (!loggedIn) {
    const next = '/?job=' + encodeURIComponent(job.id) + '#project';
    location.href = '/account/login?next=' + encodeURIComponent(next);
    return;
  }
  $('build').disabled = true;
  try {
    const form = new FormData(); form.set('entries', selectedEntries.join('|')); form.set('mode', $('mode').value);
    await api('/api/jobs/' + job.id + '/build', {method:'POST', body:form});
    if (current !== generation) return;
    renderStatus({status:'QUEUED'});
    $('progress').scrollIntoView({behavior:'smooth', block:'center'});
    poll(job.id, current);
  } catch (error) { showError(error.message); $('build').disabled = false; }
};
async function poll(id, current) {
  try {
    const value = await api('/api/jobs/' + encodeURIComponent(id));
    const log = await api('/api/jobs/' + encodeURIComponent(id) + '/log');
    if (current !== generation) return;
    renderStatus(value);
    $('ids').textContent = value.status === 'SUCCESS' ? '构建已完成 · 可以安全下载产物' : '任务 ' + value.id + ' · Build ' + (value.build_id || '准备中');
    $('plan').textContent = JSON.stringify(value.plan, null, 2); $('log').textContent = log.text;
    if (value.terminal && ['FAILED','NEEDS_MANUAL_REVIEW','EXPIRED'].includes(value.status)) {
      showError(value.error || states[value.status]);
    } else {
      clearError();
    }
    if (!value.terminal && value.status !== 'READY') setTimeout(() => poll(id, current), 1500);
  } catch (error) { if (current === generation) showError(error.message); }
}
async function preview() {
  if (!job) return;
  const selected = [...document.querySelectorAll('input[name="build-entry"]:checked')].map(input => input.value);
  if (!selected.length) return;
  try {
    const plan = await api('/api/jobs/' + job.id + '/plan?entry=' + encodeURIComponent(selected[0]) + '&mode=' + $('mode').value);
    clearError();
    $('plan').textContent = JSON.stringify(plan, null, 2); $('type').textContent = '✓ 应用类型：' + (plan.app_type === 'gui' ? '图形界面应用' : '控制台应用');
  } catch (error) { showError(error.message); }
}
$('cancel-build')?.addEventListener('click', async () => {
  if (!job?.id || !confirm('确定取消当前构建吗？正在执行的打包进程会被终止。')) return;
  const button = $('cancel-build');
  button.disabled = true;
  button.textContent = '正在取消…';
  try {
    const result = await api('/api/jobs/' + encodeURIComponent(job.id) + '/cancel', {method:'POST'});
    renderStatus({...result, terminal:false, artifact_available:false});
    poll(job.id, generation);
  } catch (error) {
    showError(error.message);
    button.disabled = false;
    button.textContent = '取消当前构建';
  }
});
$('mode').onchange = preview;
$('upload-file')?.addEventListener('change', renderSelectedFile);
renderSelectedFile();
renderStatus({status:'READY'});
async function resumeExisting(id) {
  try {
    let value = await api('/api/jobs/' + encodeURIComponent(id));
    renderCurrentProject(value);
    const loggedIn = Boolean(document.querySelector('meta[name="user-csrf"]')?.content);
    if (value.status === 'READY' && !value.owner_id && loggedIn) {
      value = await api('/api/jobs/' + encodeURIComponent(id) + '/claim', {method:'POST'});
    }
    if (value.status === 'READY') {
      showProject(value, generation);
      renderStatus(value);
      return;
    }
    $('progress').hidden = false;
    job = value;
    poll(id, generation);
  } catch (error) {
    showError(error.message);
  }
}
const existing = new URLSearchParams(location.search).get('job');
if (existing) resumeExisting(existing);
