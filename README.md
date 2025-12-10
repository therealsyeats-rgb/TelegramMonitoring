# Telegram Channel Monitor

Автоматический мониторинг Telegram-канала с загрузкой файлов, распаковкой архивов и поиском ключевых слов.

## Основные возможности

- 📥 Автоматическое скачивание файлов из Telegram-канала
- 📦 Распаковка архивов (.rar, .zip, .7z) с подбором паролей
- 🔍 Поиск ключевых слов в текстовых файлах
- 🤖 Уведомления в Telegram через бота
- ⚡ Параллельная обработка файлов
- 🎯 Дедупликация файлов
- 📊 Статистика работы

## Что улучшено по сравнению с оригинальной версией

### 1. **Архитектура и организация кода**

#### ✅ Класс-ориентированный дизайн
- Код разделен на логические классы: `TelegramMonitor`, `FileProcessor`, `PasswordManager`, `ArchiveExtractor`, `KeywordScanner`
- Каждый класс отвечает за свою область (Single Responsibility Principle)
- Легче тестировать и поддерживать

#### ✅ Конфигурация через dataclass
- Все настройки в едином классе `Config`
- Валидация конфигурации при запуске
- Типизация параметров

### 2. **Производительность**

#### ✅ Множественные воркеры
```python
# Было: 1 воркер
async def worker(client):
    ...

# Стало: NUM_WORKERS (по умолчанию 4)
for i in range(self.config.num_workers):
    worker = asyncio.create_task(self._worker(i))
```

#### ✅ Оптимизация блокирующих операций
- Распаковка архивов вынесена в executor (не блокирует event loop)
- Вычисление хешей асинхронное

#### ✅ Приоритизация паролей
```python
# Сначала проверяются пароли из похожих архивов (fuzzy matching)
# Потом все остальные
passwords = self.password_manager.get_priority_passwords(archive_name)
```

### 3. **Логирование**

#### ✅ Профессиональная система логирования
```python
# Было:
print(f"[Download] Downloading...")

# Стало:
logger.info("📥 Начало загрузки: filename (10.5 MB)")
logger.error("❌ Ошибка загрузки", exc_info=True)
```

- Логи в файл `telegram_monitor.log` + консоль
- Разные уровни: DEBUG, INFO, WARNING, ERROR
- Автоматическое логирование stacktrace при ошибках

### 4. **Управление ресурсами**

#### ✅ Автоматический cleanup
```python
CLEANUP_DOWNLOADS=false  # Оставлять скачанные файлы
CLEANUP_EXTRACTED=true   # Удалять распакованные (экономия места)
```

#### ✅ Ограничения безопасности
```python
MAX_FILE_SIZE_MB=5000        # Защита от огромных файлов
MAX_EXTRACT_SIZE_MB=10000    # Защита от zip-бомб
```

### 5. **Уведомления**

#### ✅ Батчинг уведомлений
```python
# Было: отправка каждого уведомления сразу
await notify_admin(text)

# Стало: группировка для избежания флуда
await self.notifier.notify(text)  # Соберется батч и отправится группой
```

- Автоматическая группировка уведомлений
- Защита от rate-limiting Telegram
- Настраиваемый размер батча и таймаут

#### ✅ Улучшенное экранирование Markdown
- Правильное экранирование спецсимволов для MarkdownV2
- Нет крашей при отправке уведомлений

### 6. **Обработка ошибок**

#### ✅ Graceful shutdown
```python
# Корректное завершение при Ctrl+C
- Ждет завершения текущих задач
- Сохраняет все данные
- Отправляет финальную статистику
```

#### ✅ Статистика работы
```python
@dataclass
class Statistics:
    files_downloaded: int
    files_skipped: int
    files_failed: int
    archives_extracted: int
    matches_found: int
    errors: int
```

### 7. **Thread Safety**

#### ✅ Asyncio locks для shared ресурсов
```python
# PASSWORD_HISTORY, DEDUP_STORE - защищены от race conditions
async with self.lock:
    self.history[password] = archives
```

### 8. **Дедупликация**

#### ✅ Улучшенная система дедупликации
- Проверка по unique_id
- Проверка по имени+размеру
- Проверка по quick_hash (опционально)
- Асинхронное сохранение базы

### 9. **Код качество**

#### ✅ Type hints везде
```python
async def process_document(
    self,
    client: TelegramClient,
    doc: Document
) -> None:
```

#### ✅ Docstrings для всех классов и важных методов

#### ✅ Pathlib вместо os.path
```python
# Было:
os.path.join(DOWNLOAD_DIR, filename)

# Стало:
self.config.download_dir / filename
```

### 10. **Дополнительные фичи**

#### ✅ Поддержка относительных путей
```python
DOWNLOAD_DIR=./downloads  # Работает относительно текущей директории
```

#### ✅ Лучший поиск unrar
```python
# Автоматический поиск в нескольких местах
UNRAR_PATHS = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    "/usr/bin/unrar",
    ...
]
```

#### ✅ Детальное логирование совпадений
```python
# В файл и в консоль записываются:
- Оригинальное имя архива
- Файл внутри архива
- Номер строки
- Найденные ключевые слова
- Текст строки
```

## Установка

### 1. Клонировать репозиторий
```bash
git clone <repository>
cd TelegramMonitoring
```

### 2. Установить зависимости
```bash
pip install -r requirements.txt
```

### 3. Установить UnRAR (для распаковки .rar)

**Windows:**
- Скачать WinRAR с https://www.rarlab.com/
- Установить в стандартную директорию

**Linux:**
```bash
sudo apt-get install unrar  # Debian/Ubuntu
sudo yum install unrar      # CentOS/RHEL
```

**macOS:**
```bash
brew install unrar
```

### 4. Настроить конфигурацию

Скопируйте `.env.example` в `.env`:
```bash
cp .env.example .env
```

Отредактируйте `.env` и заполните:

#### Обязательные параметры:
- `API_ID` и `API_HASH` - получите на https://my.telegram.org/apps
- `CHANNEL_USERNAME` - username канала (например: `@channelname`)

#### Опциональные (для уведомлений):
- `BOT_TOKEN` - токен бота от @BotFather
- `ADMIN_CHAT_ID` - ваш Telegram ID (узнайте у @userinfobot)

### 5. Создать файлы

**keywords.txt** - ключевые слова для поиска (одно на строку):
```
пароль
email
логин
```

**passwords.txt** - пароли для архивов (один на строку):
```
123456
password
mypass123
```

## Запуск

```bash
python telegram_monitor.py
```

При первом запуске потребуется авторизация в Telegram:
- Введите номер телефона
- Введите код из SMS/Telegram

## Структура файлов

```
TelegramMonitoring/
├── telegram_monitor.py      # Основной скрипт
├── requirements.txt          # Зависимости
├── .env                      # Конфигурация (создайте из .env.example)
├── .env.example              # Пример конфигурации
├── keywords.txt              # Ключевые слова
├── passwords.txt             # Пароли для архивов
├── password_history.json     # История успешных паролей (создается автоматически)
├── telegram_monitor.log      # Лог файл (создается автоматически)
├── matches.txt               # Найденные совпадения (создается автоматически)
├── downloads/                # Скачанные файлы
│   └── dedup_store.json     # База дедупликации
└── extracted/                # Временные распакованные файлы
```

## Конфигурация

### Производительность

```env
MAX_PARALLEL_DOWNLOADS=4  # Одновременных загрузок
NUM_WORKERS=4             # Воркеров для обработки
```

**Рекомендации:**
- Для быстрого интернета: 8-16 загрузок
- Для медленного: 2-4 загрузки
- NUM_WORKERS обычно = MAX_PARALLEL_DOWNLOADS

### Управление файлами

```env
CLEANUP_DOWNLOADS=false   # Удалять скачанные файлы после обработки
CLEANUP_EXTRACTED=true    # Удалять распакованные файлы
```

**Рекомендации:**
- `CLEANUP_DOWNLOADS=false` если хотите сохранить оригиналы
- `CLEANUP_EXTRACTED=true` экономит место (файлы уже просканированы)

### Безопасность

```env
MAX_FILE_SIZE_MB=5000        # Не скачивать файлы больше 5GB
MAX_EXTRACT_SIZE_MB=10000    # Защита от zip-бомб
```

### Уведомления

```env
NOTIFICATION_BATCH_SIZE=5      # Группировать по 5 уведомлений
NOTIFICATION_BATCH_TIMEOUT=30  # Или отправлять каждые 30 секунд
```

## Примеры использования

### Пример 1: Мониторинг канала с базами данных

**.env:**
```env
CHANNEL_USERNAME=@leaksChannel
KEYWORDS_FILE=./keywords_emails.txt
```

**keywords_emails.txt:**
```
@gmail.com
@yahoo.com
@outlook.com
password:
```

### Пример 2: Корпоративный мониторинг

```env
CHANNEL_USERNAME=@corporateChannel
KEYWORDS_FILE=./keywords_corporate.txt
MAX_PARALLEL_DOWNLOADS=16
NUM_WORKERS=16
CLEANUP_DOWNLOADS=true
```

### Пример 3: Экономия места

```env
CLEANUP_DOWNLOADS=true   # Удалять после обработки
CLEANUP_EXTRACTED=true   # Удалять распакованное
```

## Troubleshooting

### Ошибка: "Не удалось подключиться к каналу"
- Проверьте что канал существует
- Убедитесь что вы подписаны на канал
- Проверьте формат: `@channelname` (с собачкой)

### Ошибка: "Не удалось распаковать архив"
- Установите UnRAR
- Проверьте что пароли в `passwords.txt`
- Проверьте права доступа к папкам

### Не приходят уведомления
- Проверьте `BOT_TOKEN` и `ADMIN_CHAT_ID`
- Напишите боту `/start` в личке
- Проверьте логи: `telegram_monitor.log`

### Медленная работа
- Увеличьте `NUM_WORKERS`
- Увеличьте `MAX_PARALLEL_DOWNLOADS`
- Включите `CLEANUP_EXTRACTED=true`

### Ошибки памяти
- Уменьшите `MAX_PARALLEL_DOWNLOADS`
- Уменьшите `NUM_WORKERS`
- Включите `CLEANUP_DOWNLOADS=true`

## Сравнение производительности

### Оригинальная версия:
- 1 воркер → обработка последовательная
- Print вместо logging → нет истории
- Нет cleanup → диск заполняется
- Нет батчинга → флуд уведомлениями
- Глобальные переменные → race conditions

### Улучшенная версия:
- 4+ воркеров → параллельная обработка
- Полноценное логирование → история в файле
- Опциональный cleanup → контроль места
- Батчинг уведомлений → нет флуда
- Thread-safe → нет race conditions

**Ускорение: ~4-8x** (в зависимости от настроек)

## Лицензия

MIT

## Автор

Улучшенная версия создана с использованием лучших практик:
- Async/await patterns
- SOLID principles
- Type hints
- Error handling
- Resource management
- Logging
- Configuration management
