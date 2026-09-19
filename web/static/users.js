const userRoot = document.getElementById('users');
const userSummary = document.getElementById('user-summary');
const refreshUsers = document.getElementById('refresh-users');

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function dateLabel(epoch) {
  return new Date(epoch * 1000).toLocaleString();
}
function quotaLabel(user) {
  return user.quota_unlimited ? '∞' : String(user.quota_remaining);
}
function renderSummary(users) {
  const enabled = users.filter(user => !user.disabled).length;
  const test = users.filter(user => user.plan === 'TEST').length;
  userSummary.innerHTML = [
    ['总用户', users.length, '已注册账号'],
    ['启用中', enabled, '可以正常登录'],
    ['FREE', users.filter(user => user.plan === 'FREE').length, '免费体验用户'],
    ['TEST', test, '内部无限账号'],
  ].map(([label,value,note]) => '<article><small>'+label+'</small><strong>'+value+'</strong><span>'+note+'</span></article>').join('');
}
function renderUsers(users) {
  if (!users.length) {
    userRoot.innerHTML = '<div class="empty-state"><h3>暂无用户</h3></div>';
    return;
  }
  userRoot.innerHTML = users.map(user => {
    const disabled = user.disabled;
    return '<article class="admin-user-card'+(disabled?' is-disabled':'')+'" data-user="'+escapeHtml(user.id)+'">'+
      '<div class="admin-user-main"><strong>'+escapeHtml(user.email)+'</strong>'+
      '<span>注册时间 '+escapeHtml(dateLabel(user.created_at))+'</span></div>'+
      '<div class="admin-user-metric"><small>套餐</small><b>'+escapeHtml(user.plan)+'</b></div>'+
      '<div class="admin-user-metric"><small>剩余额度</small><b>'+quotaLabel(user)+'</b></div>'+
      '<div class="admin-user-metric"><small>已使用</small><b>'+escapeHtml(user.quota_used)+'</b></div>'+
      '<div class="admin-user-state '+(disabled?'disabled':'enabled')+'">'+(disabled?'已停用':'正常')+'</div>'+
      '<div class="admin-user-actions">'+
        '<div class="quota-editor">'+
          '<input type="number" min="0" max="1000000" step="1" value="'+(user.quota_unlimited?'':escapeHtml(user.quota_remaining))+'" placeholder="'+(user.quota_unlimited?'∞':'次数')+'" '+(user.quota_unlimited?'disabled':'')+' aria-label="设置剩余额度">'+
          '<button class="secondary compact-button" data-action="quota" '+(user.quota_unlimited?'disabled':'')+'>设置额度</button>'+
        '</div>'+
        '<button class="secondary compact-button" data-action="plan" data-plan="'+(user.plan==='TEST'?'FREE':'TEST')+'">'+(user.plan==='TEST'?'转为 FREE':'设为 TEST')+'</button>'+
        '<button class="secondary compact-button" data-action="reset">重置额度</button>'+
        '<button class="secondary compact-button danger-button" data-action="disabled" data-disabled="'+(!disabled)+'">'+(disabled?'启用账号':'停用账号')+'</button>'+
      '</div>'+
    '</article>';
  }).join('');
}
async function loadUsers() {
  try {
    const data = await api('/api/admin/users');
    renderSummary(data.users);
    renderUsers(data.users);
    document.getElementById('error').textContent = '';
  } catch (error) {
    document.getElementById('error').textContent = error.message;
  }
}
userRoot.addEventListener('click', async event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const card = button.closest('[data-user]');
  const userId = card.dataset.user;
  button.disabled = true;
  try {
    if (button.dataset.action === 'quota') {
      const input = card.querySelector('.quota-editor input');
      const remaining = Number(input.value);
      if (!Number.isInteger(remaining) || remaining < 0 || remaining > 1000000) {
        throw Error('请输入 0–1000000 的整数额度');
      }
      await api('/api/admin/users/'+encodeURIComponent(userId)+'/quota', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({remaining})
      });
    } else if (button.dataset.action === 'plan') {
      await api('/api/admin/users/'+encodeURIComponent(userId)+'/plan', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({plan:button.dataset.plan})
      });
    } else if (button.dataset.action === 'reset') {
      await api('/api/admin/users/'+encodeURIComponent(userId)+'/quota/reset', {method:'POST'});
    } else if (button.dataset.action === 'disabled') {
      await api('/api/admin/users/'+encodeURIComponent(userId)+'/disabled', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({disabled:button.dataset.disabled === 'true'})
      });
    }
    await loadUsers();
  } catch (error) {
    document.getElementById('error').textContent = error.message;
    button.disabled = false;
  }
});
refreshUsers.addEventListener('click', loadUsers);
loadUsers();
