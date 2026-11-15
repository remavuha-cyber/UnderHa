# Конвейер YouTube Shorts: «Факты о кино»

Сценарий (JSON) → озвучка ИИ → видео 1080×1920 с караоке-субтитрами → загрузка через YouTube Data API v3 → ежедневно через GitHub Actions.

```
content/queue/*.json      очередь сценариев (публикуются по порядку имён)
content/published.json    что уже вышло (id → video_id), обновляется автоматически
config.json               ник канала, голос, цвета, приватность, хэштеги
render.py                 сборка видео
upload.py                 загрузка (videos.insert)
publish_next.py           взять следующий → собрать → загрузить → записать
stats.py                  просмотры/лайки/комменты по всем роликам
auth.py                   разово: получить refresh token
```

## Настройка (один раз, ~15 минут)

1. **Google Cloud Console** → новый проект → *APIs & Services → Library* → включить **YouTube Data API v3**.
2. *OAuth consent screen*: тип **External**, добавить свой email в Test users.
   Затем нажать **Publish app → In production**. Иначе refresh token умрёт через 7 дней.
   (Предупреждение «приложение не проверено» при входе — нормально, жмите «Продолжить».)
3. *Credentials → Create credentials → OAuth client ID → Desktop app* → скачать JSON как `client_secret.json`.
4. На своём компьютере:
   ```
   pip install google-auth-oauthlib google-api-python-client
   cd shorts && python auth.py client_secret.json
   ```
   Войти в Google-аккаунт **канала**. Скрипт напечатает три значения.
5. GitHub → репозиторий → *Settings → Secrets and variables → Actions* → добавить
   `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
6. Влить эту ветку в основную (расписание Actions работает только в ветке по умолчанию).
7. *Actions → Daily Short → Run workflow* с галкой `dry_run` — проверить сборку; затем без галки — первая публикация.

## ⚠️ Ограничение YouTube для новых API-проектов

Видео, загруженные через API из **непроверенного** проекта, YouTube блокирует в режиме «Доступ ограничен» (private).
Чтобы ролики выходили публично, нужно пройти аудит: форма **«YouTube API Services – Audit and Quota Extension Form»**
(ссылка в документации YouTube Data API → Quota and Compliance Audits). Обычно занимает от нескольких дней до пары недель.
До одобрения ролики будут загружаться, но останутся приватными.

Квота: 10 000 единиц в сутки, загрузка = 1600 → до 6 роликов в день.

## Локально

```
pip install -r requirements.txt          # + ffmpeg в системе
python render.py content/queue/001-interstellar-corn.json   # → out/*.mp4
python publish_next.py --dry-run
YT_CLIENT_ID=... YT_CLIENT_SECRET=... YT_REFRESH_TOKEN=... python stats.py
```

## Формат сценария

```json
{
  "id": "011-slug",
  "film": "Название (год)",
  "title": "Заголовок ролика до ~90 символов",
  "lines": ["Крючок.", "Факт.", "Деталь.", "Призыв подписаться/написать коммент."],
  "tags": ["фильм", "режиссёр"]
}
```
30–90 слов ≈ 20–40 секунд. Первая фраза — крючок.

Фоновая музыка: положите свободный от прав трек и укажите путь в `config.json → music_path`.
