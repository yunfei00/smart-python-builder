const jobList = document.querySelector('.job-list');
const csrf = document.querySelector('meta[name="user-csrf"]')?.content || '';

async function requestJob(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (csrf) headers.set('X-CSRF-Token', csrf);
  const response = await fetch(path, {...options, headers});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.detail || '操作失败');
  return data;
}

async function handleJobAction(button) {
  const row = button.closest('[data-job]');
  const jobId = row?.dataset.job;
  if (!jobId) return;
  const action = button.dataset.action;
  const project = row.querySelector('.job-main strong')?.textContent || '该项目';

  if (action === 'delete') {
    if (!confirm('确定删除“' + project + '”吗？\n项目源码、构建记录和产物将被清理，此操作不可恢复。')) return;
  }
  if (action === 'cancel') {
    if (!confirm('确定取消“' + project + '”的当前构建吗？')) return;
  }

  button.disabled = true;
  const original = button.textContent;
  button.textContent = action === 'delete' ? '删除中…' : '取消中…';

  try {
    if (action === 'delete') {
      await requestJob('/api/jobs/' + encodeURIComponent(jobId), {method:'DELETE'});
      row.remove();
      location.reload();
      return;
    }
    await requestJob('/api/jobs/' + encodeURIComponent(jobId) + '/cancel', {method:'POST'});
    location.reload();
  } catch (error) {
    alert(error.message);
    button.disabled = false;
    button.textContent = original;
  }
}

jobList?.addEventListener('click', event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  event.preventDefault();
  handleJobAction(button);
});
