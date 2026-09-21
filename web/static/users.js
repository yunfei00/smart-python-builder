const userRoot = document.getElementById('users');
const userSummary = document.getElementById('user-summary');
const refreshUsers = document.getElementById('refresh-users');
const createUserForm = document.getElementById('create-user-form');
const createUserMessage = document.getElementById('create-user-message');
const newUserPlan = document.getElementById('new-user-plan');
const newUserQuota = document.getElementById('new-user-quota');
const passwordModal = document.getElementById('password-modal');
const passwordResetForm = document.getElementById('password-reset-form');
const passwordResetMessage = document.getElementById('password-reset-message');
const userSearch = document.getElementById('user-search');
const userPlanFilter = document.getElementById('user-plan-filter');
const userStateFilter = document.getElementById('user-state-filter');
let passwordResetUserId = null;
let defaultFreeQuota = 10000;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function dateLabel(epoch) {
  return new Date(epoch * 1000).toLocaleString();
}
function quotaLabel(user) {
  return user.quota_unlimited ? '∞' : String(user.quota_remaining);
}
function renderSummary(summary) {
  userSummary.innerHTML = [
    ['总用户', summary.total, '已注册账号'],
    ['启用中', summary.enabled, '可以正常登录'],
    ['FREE', summary.free, '免费账号'],
    ['TEST', summary.test, '内部无限账号'],
  ].map(([label,value,note]) => '<article><small>'+label+'</small><strong>'+value+'</strong><span>'+note+'</span></article>').join('');
}
function renderUsers(users) {
  if (!users.length) {
    userRoot.innerHTML = '<div class="empty-state"><h3>暂无用户</h3></div>';
    return;
  }
  userRoot.innerHTML = users.map(user => {
    const disabled = user.disabled;
    return '<article class="admin-user-card'+(disabled?' is-disabled':'')+'" data-user="'+escapeHtml(user.id)+'" data-username="'+escapeHtml(user.username)+'">'+
      '<div class="admin-user-main"><strong>'+escapeHtml(user.username)+'</strong>'+
      '<span>'+escapeHtml(user.email || '未绑定邮箱')+'</span>'+
      '<span>注册时间 '+escapeHtml(dateLabel(user.created_at))+'</span></div>'+
      '<div class="admin-user-metric"><small>套餐</small><b>'+escapeHtml(user.plan)+'</b></div>'+
      '<div class="admin-user-metric"><small>剩余额度</small><b>'+quotaLabel(user)+'</b></div>'+
      '<div class="admin-user-metric"><small>已使用</small><b>'+escapeHtml(user.quota_used)+'</b></div>'+
      '<div class="admin-user-metric"><small>构建次数</small><b>'+escapeHtml(user.build_count || 0)+'</b></div>'+
      '<div class="admin-user-state '+(disabled?'disabled':'enabled')+'">'+(disabled?'已停用':'正常')+'</div>'+
      '<div class="admin-user-actions">'+
        '<div class="quota-editor">'+
          '<input type="number" min="0" max="1000000" step="1" value="'+(user.quota_unlimited?'':escapeHtml(user.quota_remaining))+'" placeholder="'+(user.quota_unlimited?'∞':'次数')+'" '+(user.quota_unlimited?'disabled':'')+' aria-label="设置剩余额度">'+
          '<button class="secondary compact-button" data-action="quota" '+(user.quota_unlimited?'disabled':'')+'>设置额度</button>'+
        '</div>'+
        '<button class="secondary compact-button" data-action="password">重置密码</button>'+
        '<button class="secondary compact-button" data-action="plan" data-plan="'+(user.plan==='TEST'?'FREE':'TEST')+'">'+(user.plan==='TEST'?'转为 FREE':'设为 TEST')+'</button>'+
        '<button class="secondary compact-button" data-action="reset">重置额度</button>'+
        '<button class="secondary compact-button danger-button" data-action="disabled" data-disabled="'+(!disabled)+'">'+(disabled?'启用账号':'停用账号')+'</button>'+
      '</div>'+
    '</article>';
  }).join('');
}
async function loadUsers() {
  try {
    const params = new URLSearchParams();
    const search = userSearch?.value.trim();
    const plan = userPlanFilter?.value;
    const disabled = userStateFilter?.value;
    if (search) params.set('search', search);
    if (plan) params.set('plan', plan);
    if (disabled) params.set('disabled', disabled);
    const data = await api('/api/admin/users?' + params.toString());
    defaultFreeQuota = Number(data.default_free_quota ?? 10000);
    if (newUserPlan?.value === 'FREE') newUserQuota.value = String(defaultFreeQuota);
    renderSummary(data.summary);
    renderUsers(data.users);
    document.getElementById('error').textContent = '';
  } catch (error) {
    document.getElementById('error').textContent = error.message;
  }
}

function syncCreateUserPlan() {
  const test = newUserPlan.value === 'TEST';
  newUserQuota.disabled = test;
  newUserQuota.placeholder = test ? '∞' : '次数';
}
newUserPlan?.addEventListener('change', syncCreateUserPlan);
syncCreateUserPlan();

createUserForm?.addEventListener('submit', async event => {
  event.preventDefault();
  const button = createUserForm.querySelector('button[type="submit"], button:not([type])');
  button.disabled = true;
  createUserMessage.className = 'message';
  createUserMessage.textContent = '正在创建…';
  try {
    const plan = newUserPlan.value;
    const remaining = plan === 'TEST' ? 0 : Number(newUserQuota.value);
    if (!Number.isInteger(remaining) || remaining < 0 || remaining > 1000000) {
      throw Error('请输入 0–1000000 的整数额度');
    }
    await api('/api/admin/users', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        username:document.getElementById('new-user-username').value,
        email:document.getElementById('new-user-email').value.trim(),
        password:document.getElementById('new-user-password').value,
        plan,
        remaining,
      })
    });
    createUserForm.reset();
    newUserPlan.value = 'FREE';
    newUserQuota.value = String(defaultFreeQuota);
    syncCreateUserPlan();
    createUserMessage.className = 'message success';
    createUserMessage.textContent = '用户创建成功';
    await loadUsers();
  } catch (error) {
    createUserMessage.className = 'message error';
    createUserMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

function openPasswordModal(userId, username) {
  passwordResetUserId = userId;
  document.getElementById('password-modal-user').textContent = username;
  document.getElementById('reset-user-password').value = '';
  document.getElementById('reset-user-password-confirm').value = '';
  passwordResetMessage.textContent = '';
  passwordModal.hidden = false;
  document.getElementById('reset-user-password').focus();
}
function closePasswordModal() {
  passwordResetUserId = null;
  passwordModal.hidden = true;
}
document.querySelectorAll('[data-close-password]').forEach(node => node.addEventListener('click', closePasswordModal));

passwordResetForm?.addEventListener('submit', async event => {
  event.preventDefault();
  if (!passwordResetUserId) return;
  const password = document.getElementById('reset-user-password').value;
  const confirmPassword = document.getElementById('reset-user-password-confirm').value;
  if (password !== confirmPassword) {
    passwordResetMessage.className = 'message error';
    passwordResetMessage.textContent = '两次输入的新密码不一致';
    return;
  }
  const button = passwordResetForm.querySelector('button[type="submit"], button:not([type])');
  button.disabled = true;
  passwordResetMessage.className = 'message';
  passwordResetMessage.textContent = '正在重置…';
  try {
    await api('/api/admin/users/'+encodeURIComponent(passwordResetUserId)+'/password', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password})
    });
    passwordResetMessage.className = 'message success';
    passwordResetMessage.textContent = '密码已重置，用户原有登录会话已失效';
    setTimeout(closePasswordModal, 900);
  } catch (error) {
    passwordResetMessage.className = 'message error';
    passwordResetMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

userRoot.addEventListener('click', async event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const card = button.closest('[data-user]');
  const userId = card.dataset.user;
  if (button.dataset.action === 'password') {
    openPasswordModal(userId, card.dataset.username);
    return;
  }
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
document.getElementById('apply-user-filter')?.addEventListener('click', loadUsers);
document.getElementById('clear-user-filter')?.addEventListener('click', () => {
  if (userSearch) userSearch.value = '';
  if (userPlanFilter) userPlanFilter.value = '';
  if (userStateFilter) userStateFilter.value = '';
  loadUsers();
});
userSearch?.addEventListener('keydown', event => {
  if (event.key === 'Enter') loadUsers();
});
loadUsers();
