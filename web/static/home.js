let job, generation = 0;
const $ = id => document.getElementById(id);
const states = {READY:'等待项目', QUEUED:'已进入构建队列', BUILDING:'正在生成 Windows 应用', AI_DIAGNOSING:'构建遇到问题，AI 正在诊断', AI_REPAIRING:'AI 已找到方案，正在准备修复', REBUILDING:'修复完成，正在重新构建', SUCCESS:'应用已生成', FAILED:'构建未完成', NEEDS_MANUAL_REVIEW:'需要进一步检查', EXPIRED:'构建文件已过期'};
const progress = {READY:0, QUEUED:18, BUILDING:58, AI_DIAGNOSING:66, AI_REPAIRING:74, REBUILDING:84, SUCCESS:100, FAILED:100, NEEDS_MANUAL_REVIEW:100, EXPIRED:100};
function clearError() {
  $('error').textContent = '';
}
function showError(message) {
  $('error').textContent = message || '操作失败，请重试';
  $('error').scrollIntoView({behavior:'smooth', block:'nearest'});
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
function showProject(next, current) {
  if (current !== generation) return;
  clearError();
  job = next; $('ids').textContent = '项目分析完成 · 任务 ' + job.id; $('log').textContent = '等待构建开始。';
  $('project').hidden = false; $('entry').replaceChildren();
  if (!job.entry) $('entry').add(new Option('请选择程序入口', ''));
  for (const value of job.entries) $('entry').add(new Option(value, value));
  $('dependencies').textContent = '✓ 依赖：' + (job.dependencies.join(', ') || '无需额外依赖');
  $('type').textContent = '✓ 应用类型：' + (job.plan?.app_type === 'gui' ? '图形界面应用' : '控制台应用 / 待选择入口');
  $('plan').textContent = JSON.stringify(job.plan, null, 2); $('build').disabled = false;
  $('project').scrollIntoView({behavior:'smooth', block:'center'});
}
function beginImport() {
  const current = ++generation;
  clearError(); $('project').hidden = true;
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
  try {
    const payload = {url:$('github-url').value, ref:$('github-ref').value || null};
    showProject(await api('/api/repositories', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}), current);
  } catch (error) {
    if (current !== generation) return;
    $('ids').textContent = 'GitHub 导入失败 · 请查看下方诊断信息';
    showError(error.message);
  }
};
$('build').onclick = async () => {
  const current = generation; $('build').disabled = true;
  clearError();
  try {
    if (!$('entry').value) throw Error('请先选择程序入口');
    const form = new FormData(); form.set('entry', $('entry').value); form.set('mode', $('mode').value);
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
  if (!job || !$('entry').value) return;
  try {
    const plan = await api('/api/jobs/' + job.id + '/plan?entry=' + encodeURIComponent($('entry').value) + '&mode=' + $('mode').value);
    clearError();
    $('plan').textContent = JSON.stringify(plan, null, 2); $('type').textContent = '✓ 应用类型：' + (plan.app_type === 'gui' ? '图形界面应用' : '控制台应用');
  } catch (error) { showError(error.message); }
}
$('entry').onchange = preview; $('mode').onchange = preview;
const existing = new URLSearchParams(location.search).get('job');
if (existing) { job = {id:existing}; poll(existing, generation); }
