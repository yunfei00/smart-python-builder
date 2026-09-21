function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return bytes + ' B';
  const units = ['KB','MB','GB','TB'];
  let size = bytes, index = -1;
  do { size /= 1024; index += 1; } while (size >= 1024 && index < units.length - 1);
  return size.toFixed(size >= 10 ? 1 : 2) + ' ' + units[index];
}

function detail(label, value, note='') {
  return '<article><small>'+label+'</small><strong>'+value+'</strong>'+(note?'<span>'+note+'</span>':'')+'</article>';
}

async function loadOverview() {
  try {
    const data = await api('/api/admin/overview');
    $('stat-total-builds').textContent = data.builds.total;
    $('stat-today-builds').textContent = data.builds.today;
    $('stat-success-rate').textContent = data.builds.success_rate == null ? '--' : data.builds.success_rate + '%';
    $('stat-ai-repairs').textContent = data.builds.ai_repairs;
    $('stat-users').textContent = data.users.total;
    $('stat-users-note').textContent = 'FREE ' + data.users.free + ' · TEST ' + data.users.test + ' · 启用 ' + data.users.enabled;
    $('stat-feedback').textContent = data.feedback.new;
    $('stat-disk').textContent = formatBytes(data.disk.total_bytes);
    $('stat-disk-note').textContent = '上传 ' + formatBytes(data.disk.uploads_bytes) + ' · 工作区 ' + formatBytes(data.disk.workspace_bytes);
    $('stat-queue').textContent = data.queue.running + ' 运行 / ' + data.queue.queued + ' 排队';
    $('stat-queue-note').textContent = data.queue.workers + ' worker · 活跃槽位 ' + data.queue.active_slots + '/' + data.queue.limit;

    $('queue-details').innerHTML = [
      detail('运行中', data.queue.running, 'BUILDING / AI / REBUILDING'),
      detail('排队中', data.queue.queued, 'QUEUED'),
      detail('取消中', data.queue.canceling, 'CANCELING'),
      detail('Future 数', data.queue.futures),
      detail('活动 Builder', data.queue.active_builders),
      detail('并发 Worker', data.queue.workers),
    ].join('');

    $('disk-details').innerHTML = [
      detail('总占用', formatBytes(data.disk.total_bytes)),
      detail('上传文件', formatBytes(data.disk.uploads_bytes)),
      detail('构建工作区', formatBytes(data.disk.workspace_bytes)),
      detail('数据库', formatBytes(data.disk.database_bytes)),
      detail('任务元数据', formatBytes(data.disk.metadata_bytes)),
    ].join('');

    $('retention-label').textContent = data.retention_days + ' 天';
    await loadCleanupPreview();
    $('error').textContent = '';
  } catch (error) {
    $('error').textContent = error.message;
  }
}

async function loadCleanupPreview() {
  const preview = await api('/api/admin/maintenance/cleanup-preview');
  $('cleanup-count').textContent = preview.count;
  $('cleanup-bytes').textContent = formatBytes(preview.bytes);
}

$('refresh-overview').onclick = loadOverview;
$('cleanup-now').onclick = async () => {
  const count = Number($('cleanup-count').textContent || 0);
  if (!count) {
    $('cleanup-message').className = 'message';
    $('cleanup-message').textContent = '当前没有超过保留期限的数据需要清理。';
    return;
  }
  if (!confirm('确定清理 ' + count + ' 条过期构建记录吗？\n关联上传文件、工作区和产物将被删除，无法恢复。')) return;
  const button = $('cleanup-now');
  button.disabled = true;
  $('cleanup-message').className = 'message';
  $('cleanup-message').textContent = '正在清理…';
  try {
    const result = await api('/api/admin/maintenance/cleanup', {method:'POST'});
    $('cleanup-message').className = 'message success';
    $('cleanup-message').textContent = result.message + '，预计释放 ' + formatBytes(result.bytes) + '。';
    await loadOverview();
  } catch (error) {
    $('cleanup-message').className = 'message error';
    $('cleanup-message').textContent = error.message;
  } finally {
    button.disabled = false;
  }
};

loadOverview();
