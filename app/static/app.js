/* 抖音火花助手 —— 前端逻辑
   两个账号的数据完全按 account_id 分开请求，切换页签时只渲染当前账号。 */

const state = {
  accounts: [],
  currentId: null,
  friends: [],
  logs: [],
  times: [],
  messages: [],
  polling: null,
  dirty: new Set(),
};

const $ = (id) => document.getElementById(id);

/* ---------------- 基础工具 ---------------- */
async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.message || `请求失败 (${res.status})`);
  }
  return data.data !== undefined ? data.data : data;
}

let toastTimer = null;
function toast(message, isError = false) {
  const el = $('toast');
  el.textContent = message;
  el.style.background = isError ? '#c0392b' : '#1f2329';
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 2600);
}

function guard(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (err) {
      toast(err.message || String(err), true);
    }
  };
}

function current() {
  return state.accounts.find((a) => a.id === state.currentId);
}

/* ---------------- 账号与页签 ---------------- */
async function loadAccounts(keepSelection = true) {
  const accounts = await api('/api/accounts');
  state.accounts = accounts;
  renderTabs();
  if (!keepSelection || !state.accounts.some((a) => a.id === state.currentId)) {
    if (state.accounts.length) selectAccount(state.accounts[0].id);
    return;
  }
  const acc = current();
  if (acc) {
    renderStatus(acc);
    if (acc.status !== 'logging_in') {
      await Promise.all([loadFriends(), loadLogs()]);
    }
  }
}

function renderTabs() {
  const box = $('tabs');
  box.innerHTML = '';
  state.accounts.forEach((acc) => {
    const btn = document.createElement('button');
    btn.className = `tab ${acc.status} ${acc.id === state.currentId ? 'active' : ''}`;
    btn.innerHTML = `<i class="dot"></i>${escapeHtml(acc.label || `账号 ${acc.slot}`)}`;
    btn.onclick = () => selectAccount(acc.id);
    box.appendChild(btn);
  });
}

function selectAccount(id) {
  state.currentId = id;
  stopPolling();
  renderTabs();
  const acc = current();
  if (!acc) return;
  renderStatus(acc);
  renderSettings(acc);
  loadFriends();
  loadLogs();
  if (acc.status === 'logging_in') startPolling();
}

function renderStatus(acc) {
  const badge = $('statusBadge');
  badge.textContent = acc.status_text || acc.status;
  badge.className = `badge ${acc.status}`;

  // 正在输入备注时不要被轮询覆盖
  if (document.activeElement !== $('labelInput')) {
    $('labelInput').value = acc.label || '';
  }
  $('nicknameText').textContent = acc.nickname || '—';
  $('lastLoginText').textContent = acc.last_login_at || '—';
  $('nextRunText').textContent = acc.next_run || (acc.task_enabled ? '已启用' : '—');

  const online = acc.status === 'online';
  const logging = acc.status === 'logging_in';
  $('btnLogin').textContent = online ? '重新扫码' : '扫码登录';
  $('btnLogin').disabled = logging;
  $('btnCancelLogin').disabled = !logging;
  $('btnVerify').disabled = !online;
  $('btnLogout').disabled = acc.status === 'offline';

  if (logging) {
    // 转圈只在还没拿到二维码（图片仍隐藏）时显示，避免遮罩盖住二维码
    if ($('qrImage').classList.contains('hidden')) {
      $('qrSpin').classList.remove('hidden');
    } else {
      $('qrSpin').classList.add('hidden');
    }
  } else {
    $('qrSpin').classList.add('hidden');
    if (!online) {
      $('qrImage').classList.add('hidden');
      $('qrPlaceholder').classList.remove('hidden');
    }
  }
}

/* ---------------- 登录流程 ---------------- */
let startLogin = guard(async () => {
  const acc = current();
  const btn = $('btnLogin');
  btn.disabled = true;
  // 请求进行中：显示转圈，隐藏旧图
  $('qrSpin').classList.remove('hidden');
  $('qrImage').classList.add('hidden');
  $('qrPlaceholder').classList.remove('hidden');
  try {
    const res = await api(`/api/accounts/${acc.id}/login/start`, { method: 'POST' });
    $('qrSpin').classList.add('hidden'); // 请求返回，隐藏转圈
    if (res.status === 'success') {
      toast('已登录');
      await loadAccounts();
      return;
    }
    if (res.qr_url) {
      const img = $('qrImage');
      img.src = res.qr_url;
      img.classList.remove('hidden');
      $('qrPlaceholder').classList.add('hidden');
      toast(res.message || '请用抖音 App 扫码');
    }
    await loadAccounts();
    startPolling();
  } finally {
    btn.disabled = false;
  }
});

function startPolling() {
  stopPolling();
  state.polling = setInterval(
    guard(async () => {
      const acc = current();
      if (!acc) return stopPolling();
      const res = await api(`/api/accounts/${acc.id}/login/poll`);
      if (res.status === 'success') {
        stopPolling();
        $('qrSpin').classList.add('hidden');
        toast('登录成功');
        await loadAccounts();
      } else if (res.status === 'expired') {
        stopPolling();
        toast(res.message || '二维码已失效，请重新获取', true);
        await loadAccounts();
      }
      // pending 状态继续等下一轮
    }),
    2000
  );
}

function stopPolling() {
  if (state.polling) {
    clearInterval(state.polling);
    state.polling = null;
  }
}

const cancelLogin = guard(async () => {
  const acc = current();
  await api(`/api/accounts/${acc.id}/login/cancel`, { method: 'POST' });
  stopPolling();
  $('qrSpin').classList.add('hidden');
  await loadAccounts();
});

const verifyLogin = guard(async () => {
  const acc = current();
  const res = await api(`/api/accounts/${acc.id}/verify`, { method: 'POST' });
  toast(res.status === 'success' ? '登录态有效' : (res.message || '登录态已失效'), res.status !== 'success');
  await loadAccounts();
});

const doLogout = guard(async () => {
  const acc = current();
  if (!confirm(`确定登出「${acc.label || acc.nickname || '该账号'}」？本地会话会被清除。`)) return;
  await api(`/api/accounts/${acc.id}/logout`, { method: 'POST' });
  stopPolling();
  await loadFriends();
  await loadAccounts();
});

const cookieLogin = guard(async () => {
  const acc = current();
  const cookie = $('cookieInput').value.trim();
  if (!cookie) return toast('请先粘贴 Cookie', true);
  const res = await api(`/api/accounts/${acc.id}/login/cookies`, {
    method: 'POST',
    body: JSON.stringify({ cookie }),
  });
  if (res.status === 'success') {
    $('cookieInput').value = '';
    toast('导入成功');
    await loadAccounts();
  } else {
    toast(res.message || '导入失败', true);
  }
});

const smsSend = guard(async () => {
  const acc = current();
  const phone = $('smsPhone').value.trim();
  if (!phone) return toast('请先输入手机号', true);
  const btn = $('btnSmsSend');
  btn.disabled = true;
  btn.textContent = '发送中…';
  try {
    await api(`/api/accounts/${acc.id}/login/sms/send`, {
      method: 'POST',
      body: JSON.stringify({ phone }),
    });
    toast('验证码已发送，请查收短信');
    $('smsCode').focus();
  } finally {
    btn.disabled = false;
    btn.textContent = '获取验证码';
  }
});

const smsLogin = guard(async () => {
  const acc = current();
  const code = $('smsCode').value.trim();
  if (!code) return toast('请输入验证码', true);
  const btn = $('btnSmsLogin');
  btn.disabled = true;
  btn.textContent = '登录中…';
  try {
    const res = await api(`/api/accounts/${acc.id}/login/sms/verify`, {
      method: 'POST',
      body: JSON.stringify({ code }),
    });
    if (res.status === 'success') {
      $('smsPhone').value = '';
      $('smsCode').value = '';
      toast('登录成功');
      await loadAccounts();
    } else {
      toast(res.message || '登录状态未确认，稍后点「校验登录态」', true);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = '登录';
  }
});

const saveLabel = guard(async () => {
  const acc = current();
  await api(`/api/accounts/${acc.id}`, {
    method: 'POST',
    body: JSON.stringify({ label: $('labelInput').value.trim() }),
  });
  toast('已保存');
  await loadAccounts();
});

/* ---------------- 定时任务设置 ---------------- */
function renderSettings(acc) {
  state.times = [...(acc.send_times || [])];
  state.messages = [...(acc.message_pool || [])];

  $('taskToggle').checked = !!acc.task_enabled;
  $('taskToggleText').textContent = acc.task_enabled ? '已启用' : '已停用';
  $('msgMode').value = acc.message_mode || 'random';
  $('jitter').value = acc.jitter_seconds ?? 20;
  $('dryRun').checked = !!acc.dry_run;

  renderTimes();
  renderMessages();
}

function renderTimes() {
  const box = $('timeChips');
  box.innerHTML = '';
  if (!state.times.length) {
    box.innerHTML = '<span class="muted">还没有时间点，定时任务不会执行</span>';
    return;
  }
  state.times.forEach((t) => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = `<span>每天 ${t}</span><button title="移除">×</button>`;
    chip.querySelector('button').onclick = () => {
      state.times = state.times.filter((x) => x !== t);
      renderTimes();
    };
    box.appendChild(chip);
  });
}

function renderMessages() {
  const box = $('msgList');
  box.innerHTML = '';
  if (!state.messages.length) {
    box.innerHTML = '<span class="muted">还没有消息内容</span>';
    return;
  }
  state.messages.forEach((m, i) => {
    const item = document.createElement('div');
    item.className = 'msg-item';
    item.innerHTML = `<span>${escapeHtml(m)}</span><button class="btn tiny">删除</button>`;
    item.querySelector('button').onclick = () => {
      state.messages.splice(i, 1);
      renderMessages();
    };
    box.appendChild(item);
  });
}

const addTime = () => {
  const value = $('timeInput').value;
  if (!value) return;
  const [h, m] = value.split(':');
  const text = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  if (!state.times.includes(text)) state.times.push(text);
  state.times.sort();
  renderTimes();
};

const addMessage = () => {
  const value = $('msgInput').value.trim();
  if (!value) return;
  state.messages.push(value);
  $('msgInput').value = '';
  renderMessages();
};

const saveTask = guard(async () => {
  const acc = current();
  const data = await api(`/api/accounts/${acc.id}/settings`, {
    method: 'POST',
    body: JSON.stringify({
      send_times: state.times,
      message_pool: state.messages,
      message_mode: $('msgMode').value,
      jitter_seconds: Number($('jitter').value || 0),
      dry_run: $('dryRun').checked,
    }),
  });
  state.messages = data.message_pool;
  state.times = data.send_times;
  renderTimes();
  renderMessages();
  toast('设置已保存');
  await loadAccounts();
});

const onTaskToggle = guard(async (e) => {
  const acc = current();
  const enabled = e.target.checked;
  const res = await api(`/api/accounts/${acc.id}/task/toggle`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  });
  $('taskToggleText').textContent = res.task_enabled ? '已启用' : '已停用';
  toast(res.task_enabled ? '定时任务已启用' : '定时任务已停用');
  await loadAccounts();
});

const runNow = guard(async () => {
  const acc = current();
  if (!confirm('立即向所有已勾选好友发送一次消息？')) return;
  await api(`/api/accounts/${acc.id}/run-now`, { method: 'POST' });
  toast('已触发，稍后查看日志');
  setTimeout(loadLogs, 2500);
});

/* ---------------- 好友 ---------------- */
async function loadFriends() {
  const acc = current();
  if (!acc) return;
  state.friends = await api(`/api/accounts/${acc.id}/friends`);
  renderFriends();
}

let friendFilter = '';
function renderFriends() {
  const box = $('friendList');
  const keyword = friendFilter.trim().toLowerCase();
  const list = state.friends.filter(
    (f) => !keyword || (f.nickname || '').toLowerCase().includes(keyword)
  );

  const enabled = state.friends.filter((f) => f.enabled).length;
  $('friendSummary').textContent = `共 ${state.friends.length} 位，已勾选 ${enabled} 位`;

  box.innerHTML = '';
  if (!list.length) {
    box.innerHTML =
      '<p class="muted">暂无好友。登录后点「刷新」拉取，或手动添加。</p>';
    return;
  }

  list.forEach((f) => {
    const card = document.createElement('div');
    card.className = `friend-card ${f.enabled ? 'on' : ''}`;

    const metaClass = f.last_status === 'ok' ? 'ok' : f.last_status === 'fail' ? 'fail' : '';
    const metaText = f.last_sent_at
      ? `${f.last_sent_at} · ${f.last_result || f.last_status}`
      : '';

    card.innerHTML = `
      <div class="friend-top">
        <label class="checkbox"><input type="checkbox" ${f.enabled ? 'checked' : ''}></label>
        <div class="avatar">${f.avatar ? `<img src="${escapeHtml(f.avatar)}" alt="">` : escapeHtml((f.nickname || '?').slice(0, 1))}</div>
        <div class="name" title="${escapeHtml(f.nickname)}">${escapeHtml(f.nickname)}</div>
        <button class="btn tiny" data-act="del">删除</button>
      </div>
      <input type="text" placeholder="专属消息（留空则用公共消息池）" value="${escapeHtml(f.custom_message)}">
      <div class="friend-meta ${metaClass}">${escapeHtml(metaText)}</div>
    `;

    card.querySelector('input[type=checkbox]').onchange = (e) =>
      updateFriend(f.id, { enabled: e.target.checked });
    card.querySelector('[data-act=del]').onclick = () => deleteFriend(f.id);

    const input = card.querySelector('input[type=text]');
    input.onchange = () => updateFriend(f.id, { custom_message: input.value });

    box.appendChild(card);
  });
}

const updateFriend = guard(async (id, patch) => {
  const data = await api(`/api/friends/${id}`, {
    method: 'POST',
    body: JSON.stringify(patch),
  });
  const index = state.friends.findIndex((f) => f.id === id);
  if (index >= 0) state.friends[index] = data;
  renderFriends();
});

const deleteFriend = guard(async (id) => {
  if (!confirm('删除该好友？')) return;
  await api(`/api/friends/${id}`, { method: 'DELETE' });
  await loadFriends();
});

const addFriend = guard(async () => {
  const acc = current();
  const ref = $('friendInput').value.trim();
  if (!ref) return toast('请输入昵称', true);
  await api(`/api/accounts/${acc.id}/friends`, {
    method: 'POST',
    body: JSON.stringify({ ref, enabled: true }),
  });
  $('friendInput').value = '';
  await loadFriends();
});

const refreshFriends = guard(async () => {
  const acc = current();
  const btn = $('refreshFriends');
  btn.disabled = true;
  btn.textContent = '拉取中…';
  try {
    const res = await api(`/api/accounts/${acc.id}/friends/refresh`, { method: 'POST' });
    toast(`刷新完成，新增 ${res.added} 位`);
    await loadFriends();
  } finally {
    btn.disabled = false;
    btn.textContent = '刷新';
  }
});

const setAllFriends = guard(async (enabled) => {
  const acc = current();
  await api(`/api/accounts/${acc.id}/friends/toggle-all`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  });
  await loadFriends();
});

/* ---------------- 日志 ---------------- */
async function loadLogs() {
  const acc = current();
  if (!acc) return;
  state.logs = await api(`/api/accounts/${acc.id}/logs`);
  renderLogs();
}

function renderLogs() {
  const box = $('logBox');
  if (!state.logs.length) {
    box.innerHTML = '<div class="empty">暂无日志</div>';
    return;
  }
  box.innerHTML = state.logs
    .map(
      (l) =>
        `<div class="${l.level}">[${l.created_at}] ${escapeHtml(l.message)}</div>`
    )
    .join('');
  box.scrollTop = box.scrollHeight;
}

const clearLogs = guard(async () => {
  const acc = current();
  await api(`/api/accounts/${acc.id}/logs`, { method: 'DELETE' });
  await loadLogs();
});

/* ---------------- 工具 ---------------- */
function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ---------------- 绑定 ---------------- */
function bind() {
  $('btnLogin').onclick = startLogin;
  $('btnCancelLogin').onclick = cancelLogin;
  $('btnVerify').onclick = verifyLogin;
  $('btnLogout').onclick = doLogout;
  $('btnCookieLogin').onclick = cookieLogin;
  $('btnSmsSend').onclick = smsSend;
  $('btnSmsLogin').onclick = smsLogin;
  $('saveLabel').onclick = saveLabel;

  $('taskToggle').onchange = onTaskToggle;
  $('addTime').onclick = addTime;
  $('addMsg').onclick = addMessage;
  $('saveTask').onclick = saveTask;
  $('runNow').onclick = runNow;
  document.querySelectorAll('[data-quick]').forEach((btn) => {
    btn.onclick = () => {
      $('timeInput').value = btn.dataset.quick;
      addTime();
    };
  });

  $('refreshFriends').onclick = refreshFriends;
  $('addFriend').onclick = addFriend;
  $('toggleAll').onclick = () => setAllFriends(true);
  $('toggleNone').onclick = () => setAllFriends(false);
  $('friendSearch').oninput = (e) => {
    friendFilter = e.target.value;
    renderFriends();
  };

  $('clearLogs').onclick = clearLogs;
}

async function boot() {
  bind();
  try {
    const sys = await api('/api/system');
    $('sysInfo').textContent =
      `驱动：${sys.driver} · 时区：${sys.timezone} · 服务器时间：${sys.now}`;
  } catch (e) {
    $('sysInfo').textContent = '无法连接服务';
  }
  await loadAccounts(false);
  setInterval(() => loadAccounts(), 8000);
  setInterval(() => {
    const acc = current();
    if (acc && acc.status === 'online') loadLogs();
  }, 5000);
}

boot();
