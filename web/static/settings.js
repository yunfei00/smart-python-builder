function populate(values, form = null) {
  for (const [key, value] of Object.entries(values)) {
    if (key === 'overridden' || !$(key)) continue;
    if (form && !form.contains($(key))) continue;
    if (['ai_api_key','feishu_webhook'].includes(key)) {
      $(key + '-status').textContent = value ? '已配置：********' : '尚未配置';
      $(key).value = ''; $(key).hidden = true; $(key).disabled = true;
    } else if ($(key).type === 'checkbox') $(key).checked = value;
    else $(key).value = value;
  }
  $('overrides').hidden = !values.overridden.length;
  $('overrides').textContent = '环境变量优先覆盖以下设置：' + values.overridden.join(', ') + '。若要使用后台保存值，请移除对应环境变量并重启服务。';
  baseUrlWarning();
}
function baseUrlWarning() {
  const message = $('base-url-warning');
  try {
    const url = new URL($('base_url').value.trim());
    const local = url.hostname === 'localhost' || url.hostname === 'localhost.' || url.hostname.startsWith('127.') || url.hostname === '[::1]';
    const invalid = !['http:', 'https:'].includes(url.protocol) || ['0.0.0.0','[::]'].includes(url.hostname) || url.search || url.hash || url.username || url.password;
    message.className = local || invalid ? 'warning' : 'meta';
    message.textContent = invalid ? '请输入有效 HTTP(S) 访问地址，不含查询或片段。0.0.0.0 是监听地址，不是客户端访问地址。' : local ? '当前地址仅适用于本机访问。飞书通知中的链接无法从其他设备打开，请配置局域网 IP 或可访问域名。' : '该地址将用于飞书通知链接。';
  } catch { message.className = 'warning'; message.textContent = '请输入完整 HTTP(S) 访问地址。'; }
}
$('base_url').oninput = baseUrlWarning;
function payload(form) {
  const result = {};
  for (const input of form.elements) {
    if (!input.name || input.disabled) continue;
    result[input.name] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
  }
  return result;
}
async function action(form, path, save = false) {
  const message = form.querySelector('.message'), buttons = form.querySelectorAll('button');
  message.className = 'message'; message.textContent = '正在处理…'; buttons.forEach(button => button.disabled = true);
  try {
    const result = await api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload(form))});
    if (save) populate(result.settings, form);
    message.className = 'message success'; message.textContent = result.message;
  } catch (error) { message.className = 'message error'; message.textContent = error.message; }
  finally { buttons.forEach(button => button.disabled = false); }
}
for (const id of ['builder-settings','ai-settings','feishu-settings']) $(id).onsubmit = event => { event.preventDefault(); action(event.target, '/api/admin/settings', true); };
for (const button of document.querySelectorAll('[data-replace]')) button.onclick = () => { const input = $(button.dataset.replace); input.hidden = false; input.disabled = false; input.focus(); };
$('test-ai').onclick = () => action($('ai-settings'), '/api/admin/settings/test-ai');
$('test-feishu').onclick = () => action($('feishu-settings'), '/api/admin/settings/test-feishu');
api('/api/admin/settings').then(populate).catch(error => $('error').textContent = error.message);
