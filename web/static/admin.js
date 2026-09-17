const $ = id => document.getElementById(id);
async function api(path, options = {}) {
  options.headers = {...(options.headers || {}), 'X-CSRF-Token': document.querySelector('meta[name=csrf-token]').content};
  const response = await fetch(path, options), data = await response.json();
  if (!response.ok) throw Error(data.detail || '操作失败');
  return data;
}
$('logout').onclick = async () => {
  const response = await fetch('/admin/logout', {method:'POST', headers:{'X-CSRF-Token':document.querySelector('meta[name=csrf-token]').content}});
  if (response.ok) location.href = '/admin/login';
  else $('error').textContent = '退出失败，请刷新后重试。';
};
