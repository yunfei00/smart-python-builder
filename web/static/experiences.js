async function load() {
  try {
    $('error').textContent = '';
    const items = await api('/api/admin/experiences'); $('items').replaceChildren();
    if (!items.length) { const empty = document.createElement('section'); empty.textContent = '暂无构建经验候选。AI 修复成功后将在此显示。'; $('items').append(empty); }
    for (const item of items) {
      const section = document.createElement('section'), title = document.createElement('h2'), details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
      title.textContent = item.id + ' · ' + item.status; title.className = 'meta';
      summary.textContent = '查看失败计划、诊断、成功计划与适用条件'; pre.textContent = JSON.stringify(item, null, 2);
      details.append(summary, pre); section.append(title, details);
      if (item.status === 'CANDIDATE') {
        const edit = document.createElement('textarea'), actions = document.createElement('div');
        edit.setAttribute('aria-label', '修复计划 ' + item.id); edit.value = JSON.stringify(item.repair_plan, null, 2); actions.className = 'actions';
        section.append(edit, actions);
        for (const [label, decision] of [['批准（采用当前编辑）','APPROVED'], ['拒绝','REJECTED']]) {
          const button = document.createElement('button'); button.textContent = label;
          button.onclick = async () => { try { await api('/api/admin/experiences/' + item.id, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decision, repair_plan:JSON.parse(edit.value)})}); await load(); } catch (error) { $('error').textContent = error.message; } };
          actions.append(button);
        }
      }
      $('items').append(section);
    }
  } catch (error) { $('error').textContent = error.message; }
}
$('load').onclick = load; load();
