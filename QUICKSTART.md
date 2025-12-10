# Быстрый старт за 5 минут

## Шаг 1: Установка зависимостей (1 минута)

```bash
pip install -r requirements.txt
```

## Шаг 2: Получение API ключей Telegram (2 минуты)

1. Перейдите на https://my.telegram.org/apps
2. Войдите с вашим номером телефона
3. Создайте приложение
4. Скопируйте `api_id` и `api_hash`

## Шаг 3: Создание бота для уведомлений (1 минута, опционально)

1. Напишите @BotFather в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте токен бота
5. Напишите @userinfobot чтобы узнать свой chat_id

## Шаг 4: Конфигурация (1 минута)

Скопируйте пример:
```bash
cp .env.example .env
```

Отредактируйте `.env`:
```env
# Обязательно:
API_ID=12345678
API_HASH=ваш_api_hash
CHANNEL_USERNAME=@имя_канала

# Опционально (для уведомлений):
BOT_TOKEN=токен_от_BotFather
ADMIN_CHAT_ID=ваш_chat_id
```

Создайте файлы:
```bash
cp keywords.txt.example keywords.txt
cp passwords.txt.example passwords.txt
```

Отредактируйте `keywords.txt` - добавьте свои ключевые слова (одно на строку):
```
@gmail.com
password:
login:
```

Отредактируйте `passwords.txt` - добавьте пароли для архивов (один на строку):
```
123456
password
mypass123
```

## Шаг 5: Запуск

```bash
python telegram_monitor.py
```

При первом запуске нужно авторизоваться:
1. Введите номер телефона (в международном формате: +79001234567)
2. Введите код из SMS/Telegram

Готово! Программа начнет мониторинг канала.

## Что дальше?

### Остановка программы
Нажмите `Ctrl+C` - программа корректно завершит все задачи и сохранит данные

### Просмотр результатов
Совпадения сохраняются в `matches.txt`

### Просмотр логов
Логи в `telegram_monitor.log`

### Статистика
При остановке (Ctrl+C) показывается статистика работы

## Тонкая настройка

### Для быстрого интернета:
```env
MAX_PARALLEL_DOWNLOADS=16
NUM_WORKERS=16
```

### Для экономии места:
```env
CLEANUP_DOWNLOADS=true
CLEANUP_EXTRACTED=true
```

### Для большего контроля:
```env
CLEANUP_DOWNLOADS=false  # Сохранять все файлы
CLEANUP_EXTRACTED=false  # Сохранять распакованное
```

## Проблемы?

### "Не удалось подключиться к каналу"
- Убедитесь что вы подписаны на канал
- Проверьте что указали `@имя_канала` с собачкой

### "Не удалось распаковать архив"
- Установите UnRAR (см. README.md)
- Добавьте правильные пароли в `passwords.txt`

### Не приходят уведомления
- Напишите боту `/start` в личке
- Проверьте что `BOT_TOKEN` и `ADMIN_CHAT_ID` правильные

## Минимальная конфигурация (без бота)

Если не нужны уведомления, можно работать только с файлами:

```env
API_ID=12345678
API_HASH=ваш_api_hash
CHANNEL_USERNAME=@канал
```

Результаты будут в `matches.txt` и `telegram_monitor.log`

## Запуск в фоне (Linux/macOS)

```bash
# С выводом в файл:
python telegram_monitor.py > output.log 2>&1 &

# Или с screen:
screen -S telegram
python telegram_monitor.py
# Ctrl+A, D для отсоединения
# screen -r telegram для возврата

# Или с tmux:
tmux new -s telegram
python telegram_monitor.py
# Ctrl+B, D для отсоединения
# tmux attach -t telegram для возврата
```

## Запуск как служба (Linux systemd)

Создайте `/etc/systemd/system/telegram-monitor.service`:
```ini
[Unit]
Description=Telegram Channel Monitor
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/TelegramMonitoring
ExecStart=/usr/bin/python3 /path/to/TelegramMonitoring/telegram_monitor.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Затем:
```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-monitor
sudo systemctl start telegram-monitor
sudo systemctl status telegram-monitor
```

## Полезные команды

### Посмотреть логи в реальном времени:
```bash
tail -f telegram_monitor.log
```

### Найти совпадения по ключевому слову:
```bash
grep "password" matches.txt
```

### Очистить кеш дедупликации (скачать все заново):
```bash
rm downloads/dedup_store.json
```

### Очистить историю паролей:
```bash
rm password_history.json
```

Готово! Теперь вы знаете всё необходимое для работы с программой.
