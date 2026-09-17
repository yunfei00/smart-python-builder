let job, generation = 0;
const $ = id => document.getElementById(id);
const states = {READY:'等待开始', QUEUED:'排队中', BUILDING:'正在生成应用', AI_DIAGNOSING:'AI 正在分析构建问题', AI_REPAIRING:'AI 正在准备修复', REBUILDING:'正在重新生成应用', SUCCESS:'应用已生成', FAILED:'构建失败', NEEDS_MANUAL_REVIEW:'需要人工检查', EXPIRED:'文件已过期'};
async function api(url, options) {
  const response = await fetch(url, options), data = await response.json();
  if (!response.ok) throw Error(data.detail || '操作失败');
  return data;
}
function renderStatus(value) {
  const ready = value.status === 'SUCCESS' && value.terminal === true && value.artifact_available === true;
  $('download').disabled = !ready;
  $('download').textContent = ready ? '下载应用' : '下载应用（构建完成后可用）';
  $('download').onclick = ready ? () => { window.location.href = '/api/jobs/' + encodeURIComponent(value.id) + '/download'; } : null;
  $('status').textContent = ready ? '✓ Windows 应用生成成功' : (states[value.status] || value.status);
  $('status').classList.toggle('success', ready);
}
$('upload').onsubmit = async event => {
  event.preventDefault();
  const current = ++generation;
  $('error').textContent = ''; $('project').hidden = true;
  renderStatus({status:'READY'});
  try {
    const next = await api('/api/uploads', {method:'POST', body:new FormData(event.target)});
    if (current !== generation) return;
    job = next; $('ids').textContent = '任务 ID：' + job.id; $('log').textContent = '等待构建开始。';
    $('project').hidden = false; $('entry').replaceChildren();
    if (!job.entry) $('entry').add(new Option('请选择程序入口', ''));
    for (const value of job.entries) $('entry').add(new Option(value, value));
    $('dependencies').textContent = '检测到的依赖：' + (job.dependencies.join(', ') || '无需额外依赖');
    $('type').textContent = '应用类型：' + (job.plan?.app_type === 'gui' ? '图形界面' : '控制台 / 待选择入口');
    $('plan').textContent = JSON.stringify(job.plan, null, 2); $('build').disabled = false;
  } catch (error) { $('error').textContent = error.message; }
};
$('build').onclick = async () => {
  const current = generation; $('build').disabled = true;
  try {
    if (!$('entry').value) throw Error('请先选择程序入口');
    const form = new FormData(); form.set('entry', $('entry').value); form.set('mode', $('mode').value);
    await api('/api/jobs/' + job.id + '/build', {method:'POST', body:form});
    if (current !== generation) return;
    renderStatus({status:'QUEUED'});
    $('progress').scrollIntoView({behavior:'smooth', block:'start'});
    poll(job.id, current);
  } catch (error) { $('error').textContent = error.message; $('build').disabled = false; }
};
async function poll(id, current) {
  try {
    const value = await api('/api/jobs/' + encodeURIComponent(id));
    const log = await api('/api/jobs/' + encodeURIComponent(id) + '/log');
    if (current !== generation) return;
    renderStatus(value);
    $('ids').textContent = '任务 ID：' + value.id + ' / Build ID：' + (value.build_id || '准备中');
    $('plan').textContent = JSON.stringify(value.plan, null, 2); $('log').textContent = log.text;
    if (value.terminal && ['FAILED','NEEDS_MANUAL_REVIEW','EXPIRED'].includes(value.status)) $('error').textContent = value.error || states[value.status];
    if (!value.terminal && value.status !== 'READY') setTimeout(() => poll(id, current), 1500);
  } catch (error) { if (current === generation) $('error').textContent = error.message; }
}
async function preview() {
  if (!job || !$('entry').value) return;
  try {
    const plan = await api('/api/jobs/' + job.id + '/plan?entry=' + encodeURIComponent($('entry').value) + '&mode=' + $('mode').value);
    $('plan').textContent = JSON.stringify(plan, null, 2); $('type').textContent = '应用类型：' + (plan.app_type === 'gui' ? '图形界面' : '控制台');
  } catch (error) { $('error').textContent = error.message; }
}
$('entry').onchange = preview; $('mode').onchange = preview;
const existing = new URLSearchParams(location.search).get('job');
if (existing) { job = {id:existing}; poll(existing, generation); }
