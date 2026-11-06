// Панель управления фермой телефонов (MVP, 1+ профиль).
// Без внешних зависимостей: только Node.js >= 18.
//
// Переменные окружения:
//   PANEL_PASSWORD  — обязательный пароль для входа (логин PANEL_USER, по умолчанию admin)
//   PANEL_USER      — логин, по умолчанию admin
//   PORT            — порт, по умолчанию 8080
//   DATA_DIR        — где хранить профили и видео, по умолчанию ./data
//   MAX_UPLOAD_MB   — максимальный размер одного видео, по умолчанию 4096

'use strict';

const http = require('node:http');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { pipeline } = require('node:stream/promises');

const PORT = Number(process.env.PORT || 8080);
const PANEL_USER = process.env.PANEL_USER || 'admin';
const PANEL_PASSWORD = process.env.PANEL_PASSWORD || '';
const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(__dirname, 'data'));
const MAX_UPLOAD = Number(process.env.MAX_UPLOAD_MB || 4096) * 1024 * 1024;
const PUBLIC_DIR = path.join(__dirname, 'public');
const PROFILES_FILE = path.join(DATA_DIR, 'profiles.json');
const VIDEOS_DIR = path.join(DATA_DIR, 'videos');

if (!PANEL_PASSWORD) {
  console.error('Ошибка: задайте PANEL_PASSWORD (пароль для входа в панель).');
  process.exit(1);
}

const ID_RE = /^[a-z0-9_-]{1,40}$/i;
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webmanifest': 'application/manifest+json',
  '.json': 'application/json',
};

// ---------- данные ----------

async function loadProfiles() {
  try {
    return JSON.parse(await fsp.readFile(PROFILES_FILE, 'utf8'));
  } catch (e) {
    if (e.code !== 'ENOENT') throw e;
    const initial = [
      { id: 'p1', name: 'Профиль 1', channel: '', rustdeskId: '', note: '' },
    ];
    await saveProfiles(initial);
    return initial;
  }
}

async function saveProfiles(list) {
  await fsp.mkdir(DATA_DIR, { recursive: true });
  const tmp = PROFILES_FILE + '.tmp';
  await fsp.writeFile(tmp, JSON.stringify(list, null, 2));
  await fsp.rename(tmp, PROFILES_FILE);
}

function safeFileName(raw) {
  const base = path.basename(String(raw || '')).replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').trim();
  const cleaned = base.replace(/^\.+/, '');
  return cleaned.slice(0, 180) || '';
}

async function listVideos(profileId) {
  const dir = path.join(VIDEOS_DIR, profileId);
  let names;
  try {
    names = await fsp.readdir(dir);
  } catch (e) {
    if (e.code === 'ENOENT') return [];
    throw e;
  }
  const out = [];
  for (const name of names) {
    if (name.startsWith('.')) continue; // временные файлы загрузки
    const st = await fsp.stat(path.join(dir, name));
    if (st.isFile()) out.push({ name, size: st.size, mtime: st.mtimeMs });
  }
  return out.sort((a, b) => b.mtime - a.mtime);
}

// ---------- http-утилиты ----------

function send(res, status, body, headers = {}) {
  const isObj = body !== null && typeof body === 'object' && !Buffer.isBuffer(body);
  const data = isObj ? JSON.stringify(body) : body ?? '';
  res.writeHead(status, {
    'Content-Type': isObj ? 'application/json; charset=utf-8' : 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store',
    ...headers,
  });
  res.end(data);
}

function checkAuth(req) {
  const h = req.headers.authorization || '';
  if (!h.startsWith('Basic ')) return false;
  const decoded = Buffer.from(h.slice(6), 'base64').toString('utf8');
  const expected = `${PANEL_USER}:${PANEL_PASSWORD}`;
  const a = crypto.createHash('sha256').update(decoded).digest();
  const b = crypto.createHash('sha256').update(expected).digest();
  return crypto.timingSafeEqual(a, b);
}

async function readJson(req, limit = 64 * 1024) {
  let size = 0;
  const chunks = [];
  for await (const c of req) {
    size += c.length;
    if (size > limit) throw Object.assign(new Error('too large'), { status: 413 });
    chunks.push(c);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

async function serveStatic(res, rel) {
  const file = path.join(PUBLIC_DIR, rel);
  if (!file.startsWith(PUBLIC_DIR + path.sep)) return send(res, 404, 'Not found');
  try {
    const data = await fsp.readFile(file);
    send(res, 200, data, {
      'Content-Type': MIME[path.extname(file)] || 'application/octet-stream',
      'Cache-Control': 'no-cache',
    });
  } catch {
    send(res, 404, 'Not found');
  }
}

// ---------- обработчики ----------

async function handleApi(req, res, parts, url) {
  // parts: ['api', 'profiles', id?, 'videos'?, name?]
  if (parts[1] !== 'profiles') return send(res, 404, { error: 'not found' });
  const profiles = await loadProfiles();

  if (parts.length === 2) {
    if (req.method === 'GET') {
      const withCounts = await Promise.all(
        profiles.map(async (p) => ({ ...p, videos: (await listVideos(p.id)).length })),
      );
      return send(res, 200, withCounts);
    }
    if (req.method === 'POST') {
      const body = await readJson(req);
      let n = profiles.length + 1;
      while (profiles.some((p) => p.id === `p${n}`)) n++;
      const p = {
        id: `p${n}`,
        name: String(body.name || `Профиль ${n}`).slice(0, 80),
        channel: String(body.channel || '').slice(0, 120),
        rustdeskId: String(body.rustdeskId || '').replace(/\s+/g, '').slice(0, 40),
        note: String(body.note || '').slice(0, 500),
      };
      profiles.push(p);
      await saveProfiles(profiles);
      return send(res, 201, p);
    }
    return send(res, 405, { error: 'method not allowed' });
  }

  const id = parts[2];
  if (!ID_RE.test(id)) return send(res, 400, { error: 'bad id' });
  const idx = profiles.findIndex((p) => p.id === id);
  if (idx === -1) return send(res, 404, { error: 'profile not found' });

  if (parts.length === 3) {
    if (req.method === 'GET') return send(res, 200, profiles[idx]);
    if (req.method === 'PUT') {
      const body = await readJson(req);
      const p = profiles[idx];
      if ('name' in body) p.name = String(body.name).slice(0, 80);
      if ('channel' in body) p.channel = String(body.channel).slice(0, 120);
      if ('rustdeskId' in body) p.rustdeskId = String(body.rustdeskId).replace(/\s+/g, '').slice(0, 40);
      if ('note' in body) p.note = String(body.note).slice(0, 500);
      await saveProfiles(profiles);
      return send(res, 200, p);
    }
    return send(res, 405, { error: 'method not allowed' });
  }

  if (parts[3] !== 'videos') return send(res, 404, { error: 'not found' });
  const dir = path.join(VIDEOS_DIR, id);

  if (parts.length === 4) {
    if (req.method === 'GET') return send(res, 200, await listVideos(id));
    if (req.method === 'POST') {
      // Тело запроса — сам файл (без multipart), имя в ?name=
      const name = safeFileName(url.searchParams.get('name'));
      if (!name) return send(res, 400, { error: 'name required' });
      const declared = Number(req.headers['content-length'] || 0);
      if (declared > MAX_UPLOAD) return send(res, 413, { error: 'file too large' });

      await fsp.mkdir(dir, { recursive: true });
      let finalName = name;
      const ext = path.extname(name);
      const stem = name.slice(0, name.length - ext.length);
      for (let i = 2; fs.existsSync(path.join(dir, finalName)); i++) finalName = `${stem} (${i})${ext}`;

      const tmp = path.join(dir, `.upload-${crypto.randomUUID()}`);
      let received = 0;
      req.on('data', (c) => {
        received += c.length;
        if (received > MAX_UPLOAD) req.destroy(new Error('too large'));
      });
      try {
        await pipeline(req, fs.createWriteStream(tmp));
        await fsp.rename(tmp, path.join(dir, finalName));
      } catch (e) {
        await fsp.rm(tmp, { force: true });
        if (!res.headersSent) send(res, received > MAX_UPLOAD ? 413 : 400, { error: 'upload failed' });
        return;
      }
      return send(res, 201, { name: finalName, size: received });
    }
    return send(res, 405, { error: 'method not allowed' });
  }

  if (parts.length === 5 && req.method === 'DELETE') {
    const name = safeFileName(decodeURIComponent(parts[4]));
    if (!name) return send(res, 400, { error: 'bad name' });
    await fsp.rm(path.join(dir, name), { force: true });
    return send(res, 204, '');
  }
  return send(res, 404, { error: 'not found' });
}

async function handleDownload(res, parts) {
  // /dl/<profileId>/<file>
  const id = parts[1];
  const name = safeFileName(decodeURIComponent(parts[2] || ''));
  if (!ID_RE.test(id || '') || !name) return send(res, 400, 'Bad request');
  const file = path.join(VIDEOS_DIR, id, name);
  let st;
  try {
    st = await fsp.stat(file);
  } catch {
    return send(res, 404, 'Not found');
  }
  res.writeHead(200, {
    'Content-Type': 'application/octet-stream',
    'Content-Length': st.size,
    'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(name)}`,
    'Cache-Control': 'no-store',
  });
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://x');
    const parts = url.pathname.split('/').filter(Boolean);

    if (url.pathname === '/healthz') return send(res, 200, 'ok');

    if (!checkAuth(req)) {
      return send(res, 401, 'Нужен логин и пароль', {
        'WWW-Authenticate': 'Basic realm="PhoneFarm", charset="UTF-8"',
      });
    }

    if (parts[0] === 'api') return await handleApi(req, res, parts, url);
    if (parts[0] === 'dl') return await handleDownload(res, parts);
    if (url.pathname === '/' || parts.length === 0) return await serveStatic(res, 'index.html');
    return await serveStatic(res, parts.join('/'));
  } catch (e) {
    console.error(e);
    if (!res.headersSent) send(res, e.status || 500, { error: e.status ? e.message : 'server error' });
  }
});

server.requestTimeout = 0; // большие видео грузятся долго
server.listen(PORT, () => {
  console.log(`PhoneFarm panel: http://0.0.0.0:${PORT}  (данные: ${DATA_DIR})`);
});
