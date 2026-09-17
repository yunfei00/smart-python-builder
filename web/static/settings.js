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
}
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
