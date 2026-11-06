'use strict';

// Маршруты (hash):
//   #/            — список профилей (для вашего основного телефона)
//   #/p/<id>      — профиль: подключение RustDesk, загрузка видео
//   #/inbox/<id>  — «входящие» для телефона фермы: скачать видео в галерею

const app = document.getElementById('app');
const crumb = document.getElementById('crumb');

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtSize = (b) => (b >= 1 << 30 ? (b / (1 << 30)).toFixed(2) + ' ГБ' : b >= 1 << 20 ? (b / (1 << 20)).toFixed(1) + ' МБ' : Math.ceil(b / 1024) + ' КБ');
const fmtId = (id) => String(id || '').replace(/(\d{3})(?=\d)/g, '$1 ');

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2500);
}

async function api(path, opts = {}) {
  const res = await fetch('api/' + path, {
    ...opts,
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
  });
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.status === 204 ? null : res.json();
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Скопировано');
  } catch {
    prompt('Скопируйте вручную:', text);
  }
}

// ---------- экраны ----------

async function viewList() {
  crumb.textContent = '';
  const profiles = await api('profiles');
  app.innerHTML = `
    <h1>Профили</h1>
    ${profiles.map((p) => `
      <a class="card profile" href="#/p/${esc(p.id)}">
        <div class="ph">📱</div>
        <div class="meta">
          <b>${esc(p.name)}</b>
          <span>${p.channel ? esc(p.channel) + ' · ' : ''}${p.rustdeskId ? 'ID ' + esc(fmtId(p.rustdeskId)) : 'RustDesk ID не задан'}</span><br>
          <span>Видео в очереди: ${p.videos}</span>
        </div>
        <div class="chev">›</div>
      </a>`).join('')}
    <button class="btn" id="add">+ Добавить профиль</button>
    <p class="muted small">Совет: «Добавить на главный экран» в меню браузера, и панель откроется как приложение.</p>`;
  document.getElementById('add').onclick = async () => {
    const p = await api('profiles', { method: 'POST', body: JSON.stringify({}) });
    location.hash = '#/p/' + p.id;
  };
}

async function viewProfile(id) {
  const [p, videos] = await Promise.all([api('profiles/' + id), api(`profiles/${id}/videos`)]);
  crumb.textContent = '› ' + p.name;
  const inboxUrl = `${location.origin}${location.pathname}#/inbox/${p.id}`;

  app.innerHTML = `
    <h1>${esc(p.name)}</h1>

    <section class="card stack">
      <h2>Удалённый телефон</h2>
      ${p.rustdeskId
        ? `<div class="idbox">${esc(fmtId(p.rustdeskId))}</div>
           <div class="row">
             <a class="btn primary" href="rustdesk://${esc(p.rustdeskId)}">Подключиться</a>
             <button class="btn" id="copyId">Копировать ID</button>
           </div>
           <p class="muted small">Если кнопка не открыла RustDesk, скопируйте ID и вставьте его в RustDesk вручную.</p>`
        : `<p class="muted">Укажите RustDesk ID телефона ниже, в «Настройках профиля».</p>`}
    </section>

    <section class="card stack">
      <h2>Видео для этого телефона</h2>
      <input type="file" id="file" accept="video/*" multiple hidden>
      <button class="btn primary" id="pick">Загрузить видео</button>
      <div id="progress" hidden>
        <div class="small muted" id="progressText"></div>
        <progress id="bar" max="100" value="0"></progress>
      </div>
      ${videos.length
        ? `<ul class="list">${videos.map((v) => `
            <li><span class="name">${esc(v.name)} <span class="muted small">· ${fmtSize(v.size)}</span></span>
                <button class="btn act" data-del="${esc(v.name)}">Удалить</button></li>`).join('')}</ul>`
        : '<p class="muted">Пока пусто.</p>'}
      <details>
        <summary>Как видео попадает на телефон фермы</summary>
        <p class="small">Подключитесь к телефону через RustDesk, откройте на нём браузер со ссылкой ниже и нажмите «Скачать». Видео окажется в «Загрузках» и будет доступно в YouTube при выборе файла.</p>
        <div class="row"><button class="btn" id="copyInbox">Копировать ссылку для телефона</button></div>
      </details>
    </section>

    <section class="card">
      <details>
        <summary>Настройки профиля</summary>
        <form id="edit">
          <label>Название</label><input type="text" name="name" value="${esc(p.name)}">
          <label>Канал YouTube</label><input type="text" name="channel" value="${esc(p.channel)}" placeholder="@mychannel">
          <label>RustDesk ID телефона</label><input type="text" name="rustdeskId" value="${esc(p.rustdeskId)}" inputmode="numeric" placeholder="123 456 789">
          <label>Заметка (SIM, оператор, где стоит)</label><textarea name="note">${esc(p.note)}</textarea>
          <p><button class="btn primary">Сохранить</button></p>
        </form>
      </details>
    </section>`;

  const copyIdBtn = document.getElementById('copyId');
  if (copyIdBtn) copyIdBtn.onclick = () => copy(p.rustdeskId);
  document.getElementById('copyInbox').onclick = () => copy(inboxUrl);

  document.getElementById('edit').onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    await api('profiles/' + id, { method: 'PUT', body: JSON.stringify(body) });
    toast('Сохранено');
    render();
  };

  app.querySelectorAll('[data-del]').forEach((b) => {
    b.onclick = async () => {
      if (!confirm('Удалить «' + b.dataset.del + '»?')) return;
      await api(`profiles/${id}/videos/${encodeURIComponent(b.dataset.del)}`, { method: 'DELETE' });
      render();
    };
  });

  const input = document.getElementById('file');
  document.getElementById('pick').onclick = () => input.click();
  input.onchange = async () => {
    const files = [...input.files];
    if (!files.length) return;
    document.getElementById('pick').disabled = true;
    document.getElementById('progress').hidden = false;
    try {
      for (let i = 0; i < files.length; i++) await upload(id, files[i], i + 1, files.length);
      toast('Загружено');
    } catch (e) {
      alert('Ошибка загрузки: ' + e.message);
    }
    render();
  };
}

function upload(id, file, n, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `api/profiles/${id}/videos?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      document.getElementById('bar').value = pct;
      document.getElementById('progressText').textContent = `${n}/${total} · ${file.name} · ${pct}%`;
    };
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(xhr.responseText || xhr.status)));
    xhr.onerror = () => reject(new Error('сеть недоступна'));
    xhr.send(file);
  });
}

async function viewInbox(id) {
  const [p, videos] = await Promise.all([api('profiles/' + id), api(`profiles/${id}/videos`)]);
  crumb.textContent = '› Входящие';
  app.innerHTML = `
    <h1>Видео для «${esc(p.name)}»</h1>
    <section class="card">
      ${videos.length
        ? `<ul class="list">${videos.map((v) => `
            <li><span class="name">${esc(v.name)} <span class="muted small">· ${fmtSize(v.size)}</span></span>
                <a class="btn primary act" href="dl/${esc(id)}/${encodeURIComponent(v.name)}" download>Скачать</a></li>`).join('')}</ul>`
        : '<p class="muted">Новых видео нет.</p>'}
    </section>
    <button class="btn" onclick="location.reload()">Обновить</button>
    <p class="muted small">После скачивания откройте YouTube → «+» → выберите видео из «Загрузок».</p>`;
}

// ---------- роутер ----------

async function render() {
  const [, kind, id] = (location.hash || '#/').split('/');
  try {
    if (kind === 'p' && id) await viewProfile(id);
    else if (kind === 'inbox' && id) await viewInbox(id);
    else await viewList();
  } catch (e) {
    app.innerHTML = `<div class="card"><b>Ошибка</b><p class="muted">${esc(e.message)}</p><a class="btn" href="#/">На главную</a></div>`;
  }
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', render);
render();

if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
