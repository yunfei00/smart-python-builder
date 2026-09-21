const feedbackRoot = $('feedback-items');

function escapeFeedback(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function feedbackDate(epoch) {
  return new Date(Number(epoch) * 1000).toLocaleString();
}
function categoryLabel(value) {
  return ({SUGGESTION:'功能建议',BUG:'问题反馈',EXPERIENCE:'使用体验',OTHER:'其他'})[value] || value;
}
function statusLabel(value) {
  return ({NEW:'待处理',READ:'已查看',RESOLVED:'已解决'})[value] || value;
}
function renderFeedback(data) {
  $('feedback-total').textContent = data.summary.total;
  $('feedback-new').textContent = data.summary.new;
  $('feedback-resolved').textContent = data.summary.resolved;
  if (!data.items.length) {
    feedbackRoot.innerHTML = '<div class="empty-state"><h3>没有匹配的反馈</h3><p>调整筛选条件后再试。</p></div>';
    return;
  }
  feedbackRoot.innerHTML = data.items.map(item =>
    '<article class="feedback-admin-item" data-feedback="'+escapeFeedback(item.id)+'">'+
      '<div class="feedback-admin-head">'+
        '<div><strong>'+escapeFeedback(item.username)+'</strong><span>'+escapeFeedback(categoryLabel(item.category))+' · '+escapeFeedback(feedbackDate(item.created_at))+'</span></div>'+
        '<span class="feedback-status-badge status-'+escapeFeedback(item.status.toLowerCase())+'">'+escapeFeedback(statusLabel(item.status))+'</span>'+
      '</div>'+
      '<p>'+escapeFeedback(item.message)+'</p>'+
      '<div class="feedback-admin-actions">'+
        '<span>'+(item.notified ? '通知已发送' : (item.notification_error ? '通知失败' : '未发送通知'))+'</span>'+
        '<button class="secondary compact-button" data-status="READ">标记已查看</button>'+
        '<button class="secondary compact-button" data-status="RESOLVED">标记已解决</button>'+
      '</div>'+
    '</article>'
  ).join('');
}

async function loadFeedback() {
  const params = new URLSearchParams();
  const search = $('feedback-search').value.trim();
  const category = $('feedback-category').value;
  const status = $('feedback-status').value;
  if (search) params.set('search', search);
  if (category) params.set('category', category);
  if (status) params.set('status', status);
  try {
    const data = await api('/api/admin/feedback?' + params.toString());
    renderFeedback(data);
    $('error').textContent = '';
  } catch (error) {
    $('error').textContent = error.message;
  }
}

$('apply-feedback-filter').onclick = loadFeedback;
$('refresh-feedback').onclick = loadFeedback;
$('feedback-search').addEventListener('keydown', event => {
  if (event.key === 'Enter') loadFeedback();
});
feedbackRoot.addEventListener('click', async event => {
  const button = event.target.closest('button[data-status]');
  if (!button) return;
  const card = button.closest('[data-feedback]');
  button.disabled = true;
  try {
    await api('/api/admin/feedback/' + encodeURIComponent(card.dataset.feedback) + '/status', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({status:button.dataset.status}),
    });
    await loadFeedback();
  } catch (error) {
    $('error').textContent = error.message;
    button.disabled = false;
  }
});
loadFeedback();
