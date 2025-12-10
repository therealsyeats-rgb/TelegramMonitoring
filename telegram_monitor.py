"""
Telegram Channel Monitor - Улучшенная версия
Автоматический мониторинг канала, скачивание, распаковка и поиск ключевых слов
"""

import os
import asyncio
import hashlib
import json
import subprocess
import logging
from typing import List, Optional, Tuple, Set, Dict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import Document
from telethon.errors import FloodWaitError

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.text_decorations import markdown_decoration as md

import pyzipper
import py7zr
from rapidfuzz import fuzz

from dotenv import load_dotenv
from FastTelethon import download_file

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('telegram_monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
load_dotenv()


@dataclass
class Config:
    """Конфигурация приложения"""
    # Telegram
    api_id: int
    api_hash: str
    session_name: str
    channel_username: str

    # Директории
    download_dir: Path
    extract_dir: Path
    output_matches_file: Path

    # Пароли
    password_file: Path
    password_history_file: Path

    # Bot
    bot_token: str
    admin_chat_id: int

    # Настройки производительности
    max_parallel_downloads: int = 4
    num_workers: int = 4
    hash_quick_bytes_mb: int = 16

    # Настройки ключевых слов
    keywords_file: Path = None
    supported_exts: Set[str] = None

    # Настройки cleanup
    cleanup_downloads: bool = False
    cleanup_extracted: bool = True

    # Настройки безопасности
    max_file_size_mb: int = 5000
    max_extract_size_mb: int = 10000

    # Настройки уведомлений
    notification_batch_size: int = 5
    notification_batch_timeout: int = 30

    @classmethod
    def from_env(cls) -> 'Config':
        """Создать конфигурацию из переменных окружения"""
        return cls(
            api_id=int(os.getenv("API_ID")),
            api_hash=os.getenv("API_HASH"),
            session_name=os.getenv("SESSION_NAME", "tg_monitor"),
            channel_username=os.getenv("CHANNEL_USERNAME"),

            download_dir=Path(os.getenv("DOWNLOAD_DIR", "./downloads")),
            extract_dir=Path(os.getenv("EXTRACT_DIR", "./extracted")),
            output_matches_file=Path(os.getenv("OUTPUT_MATCHES_FILE", "./matches.txt")),

            password_file=Path(os.getenv("PASSWORD_FILE", "./passwords.txt")),
            password_history_file=Path(os.getenv("PASSWORD_HISTORY_FILE", "./password_history.json")),

            bot_token=os.getenv("BOT_TOKEN"),
            admin_chat_id=int(os.getenv("ADMIN_CHAT_ID", "0")),

            max_parallel_downloads=int(os.getenv("MAX_PARALLEL_DOWNLOADS", "4")),
            num_workers=int(os.getenv("NUM_WORKERS", "4")),
            hash_quick_bytes_mb=int(os.getenv("HASH_QUICK_BYTES_MB", "16")),

            keywords_file=Path(os.getenv("KEYWORDS_FILE", "./keywords.txt")),
            supported_exts={".rar", ".zip", ".7z", ".txt"},

            cleanup_downloads=os.getenv("CLEANUP_DOWNLOADS", "false").lower() == "true",
            cleanup_extracted=os.getenv("CLEANUP_EXTRACTED", "true").lower() == "true",

            max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", "5000")),
            max_extract_size_mb=int(os.getenv("MAX_EXTRACT_SIZE_MB", "10000")),
        )

    def validate(self):
        """Валидация конфигурации"""
        errors = []

        if not self.api_id or not self.api_hash:
            errors.append("API_ID и API_HASH обязательны")

        if not self.channel_username:
            errors.append("CHANNEL_USERNAME обязателен")

        if not self.bot_token or not self.admin_chat_id:
            logger.warning("BOT_TOKEN или ADMIN_CHAT_ID не установлены - уведомления отключены")

        if errors:
            raise ValueError("Ошибки конфигурации:\n" + "\n".join(errors))

        logger.info("Конфигурация валидна")


# ================= STATISTICS =================
@dataclass
class Statistics:
    """Статистика работы"""
    files_downloaded: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    archives_extracted: int = 0
    archives_failed: int = 0
    matches_found: int = 0
    errors: int = 0
    started_at: datetime = None

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now()

    def summary(self) -> str:
        """Получить текстовую сводку"""
        runtime = datetime.now() - self.started_at
        return (
            f"📊 Статистика работы:\n"
            f"⏱ Время работы: {runtime}\n"
            f"📥 Скачано: {self.files_downloaded}\n"
            f"⏭ Пропущено: {self.files_skipped}\n"
            f"❌ Ошибок загрузки: {self.files_failed}\n"
            f"📦 Распаковано: {self.archives_extracted}\n"
            f"🔒 Не распаковано: {self.archives_failed}\n"
            f"🎯 Совпадений: {self.matches_found}\n"
            f"⚠️ Ошибок: {self.errors}"
        )


# ================= NOTIFICATION MANAGER =================
class NotificationManager:
    """Менеджер уведомлений с батчингом"""

    def __init__(self, bot: Bot, admin_chat_id: int, batch_size: int = 5, batch_timeout: int = 30):
        self.bot = bot
        self.admin_chat_id = admin_chat_id
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.pending_notifications: List[str] = []
        self.lock = asyncio.Lock()
        self.last_send_time = datetime.now()
        self._batch_task = None

    async def start(self):
        """Запустить фоновую задачу для отправки батчей"""
        self._batch_task = asyncio.create_task(self._batch_sender())

    async def stop(self):
        """Остановить и отправить оставшиеся уведомления"""
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        await self._flush()

    async def notify(self, text: str):
        """Добавить уведомление в очередь"""
        if not self.bot or not self.admin_chat_id:
            return

        async with self.lock:
            self.pending_notifications.append(text)

            if len(self.pending_notifications) >= self.batch_size:
                await self._flush()

    async def _flush(self):
        """Отправить все накопленные уведомления"""
        if not self.pending_notifications:
            return

        try:
            # Группируем уведомления
            batch_text = "\n\n".join(self.pending_notifications[:self.batch_size])

            # Экранируем для MarkdownV2
            safe_text = self._escape_markdown(batch_text)

            await self.bot.send_message(self.admin_chat_id, safe_text)

            # Очищаем отправленные
            self.pending_notifications = self.pending_notifications[self.batch_size:]
            self.last_send_time = datetime.now()

        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")

    async def _batch_sender(self):
        """Фоновая задача для периодической отправки батчей"""
        while True:
            try:
                await asyncio.sleep(self.batch_timeout)
                async with self.lock:
                    if self.pending_notifications:
                        time_since_last = (datetime.now() - self.last_send_time).total_seconds()
                        if time_since_last >= self.batch_timeout:
                            await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в batch_sender: {e}")

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """Упрощенное экранирование для MarkdownV2"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text


# ================= PASSWORD MANAGER =================
class PasswordManager:
    """Менеджер паролей с историей и приоритизацией"""

    def __init__(self, password_file: Path, history_file: Path):
        self.password_file = password_file
        self.history_file = history_file
        self.passwords: List[str] = []
        self.history: Dict[str, List[str]] = {}
        self.lock = asyncio.Lock()
        self._load()

    def _load(self):
        """Загрузить пароли и историю"""
        # Загрузка паролей
        if self.password_file.exists():
            with open(self.password_file, 'r', encoding='utf-8', errors='ignore') as f:
                self.passwords = [line.strip() for line in f if line.strip()]

        # Добавляем пустой пароль в начало
        if "" not in self.passwords:
            self.passwords.insert(0, "")

        # Загрузка истории
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
            except Exception as e:
                logger.warning(f"Не удалось загрузить историю паролей: {e}")
                self.history = {}

        logger.info(f"Загружено {len(self.passwords)} паролей, история: {len(self.history)} записей")

    async def save_history(self):
        """Сохранить историю паролей"""
        async with self.lock:
            try:
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump(self.history, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Ошибка сохранения истории паролей: {e}")

    async def add_to_history(self, archive_name: str, password: str):
        """Добавить успешный пароль в историю"""
        async with self.lock:
            if password not in self.history:
                self.history[password] = []
            if archive_name not in self.history[password]:
                self.history[password].append(archive_name)
                logger.debug(f"Добавлен в историю: {archive_name} -> {password}")

        await self.save_history()

    def get_priority_passwords(self, archive_name: str, threshold: int = 70) -> List[str]:
        """Получить приоритетные пароли на основе похожих названий"""
        priority = []
        seen = set()

        # Приоритетные пароли из истории
        for pwd, archives in self.history.items():
            if pwd in seen:
                continue
            for archived_name in archives:
                similarity = fuzz.WRatio(archive_name, archived_name)
                if similarity >= threshold:
                    priority.append(pwd)
                    seen.add(pwd)
                    break

        # Добавляем остальные пароли
        for pwd in self.passwords:
            if pwd not in seen:
                priority.append(pwd)

        return priority


# ================= DEDUPLICATION =================
class DeduplicationStore:
    """Хранилище для дедупликации файлов"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.unique_ids: Set[str] = set()
        self.name_size: Set[str] = set()
        self.quick_hashes: Set[str] = set()
        self.lock = asyncio.Lock()
        self._load()

    def _load(self):
        """Загрузить данные из файла"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.unique_ids = set(data.get("unique_ids", []))
                    self.name_size = set(data.get("name_size", []))
                    self.quick_hashes = set(data.get("quick_hashes", []))
                logger.info(f"Загружено из БД дедупликации: {len(self.unique_ids)} ID, {len(self.quick_hashes)} хешей")
            except Exception as e:
                logger.warning(f"Не удалось загрузить БД дедупликации: {e}")

    async def save(self):
        """Сохранить данные в файл"""
        async with self.lock:
            try:
                with open(self.db_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "unique_ids": list(self.unique_ids),
                        "name_size": list(self.name_size),
                        "quick_hashes": list(self.quick_hashes)
                    }, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Ошибка сохранения БД дедупликации: {e}")

    async def is_duplicate(self, uid: str, name: str, size: int) -> bool:
        """Проверить, является ли файл дубликатом"""
        async with self.lock:
            if uid in self.unique_ids:
                return True
            if f"{name}|{size}" in self.name_size:
                return True
            return False

    async def add(self, uid: str, name: str, size: int, quick_hash: Optional[str] = None):
        """Добавить файл в БД"""
        async with self.lock:
            self.unique_ids.add(uid)
            self.name_size.add(f"{name}|{size}")
            if quick_hash:
                self.quick_hashes.add(quick_hash)

        await self.save()


# ================= ARCHIVE EXTRACTOR =================
class ArchiveExtractor:
    """Экстрактор архивов с поддержкой паролей"""

    # Поиск WinRAR
    UNRAR_PATHS = [
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
        "/usr/bin/unrar",
        "/usr/local/bin/unrar",
        "unrar"
    ]

    def __init__(self, password_manager: PasswordManager):
        self.password_manager = password_manager
        self.unrar_path = self._find_unrar()

    def _find_unrar(self) -> str:
        """Найти путь к unrar"""
        for path in self.UNRAR_PATHS:
            if os.path.exists(path):
                return path
        return "unrar"  # Fallback

    async def extract(self, archive_path: Path, dest_dir: Path) -> Tuple[bool, Optional[str]]:
        """
        Извлечь архив
        Returns: (успех, использованный_пароль)
        """
        dest_dir.mkdir(parents=True, exist_ok=True)

        ext = archive_path.suffix.lower()
        archive_name = archive_path.name

        # Получаем приоритетные пароли
        passwords = self.password_manager.get_priority_passwords(archive_name)

        logger.info(f"Попытка распаковки {archive_path.name}")

        # Пробуем без пароля
        if await self._try_extract(archive_path, dest_dir, ext, None):
            logger.info(f"✅ {archive_name} распакован без пароля")
            return True, None

        # Пробуем с паролями
        for pwd in passwords:
            if not pwd:  # Пустой пароль уже пробовали
                continue

            if await self._try_extract(archive_path, dest_dir, ext, pwd):
                logger.info(f"✅ {archive_name} распакован с паролем: '{pwd}'")
                await self.password_manager.add_to_history(archive_name, pwd)
                return True, pwd

        logger.warning(f"❌ Не удалось распаковать {archive_name}")
        return False, None

    async def _try_extract(self, archive_path: Path, dest_dir: Path, ext: str, password: Optional[str]) -> bool:
        """Попытка распаковки с конкретным паролем"""
        try:
            if ext == ".zip":
                return await self._extract_zip(archive_path, dest_dir, password)
            elif ext == ".7z":
                return await self._extract_7z(archive_path, dest_dir, password)
            elif ext == ".rar":
                return await self._extract_rar(archive_path, dest_dir, password)
            return False
        except Exception as e:
            logger.debug(f"Ошибка при распаковке с паролем '{password}': {e}")
            return False

    async def _extract_zip(self, filepath: Path, outdir: Path, pwd: Optional[str]) -> bool:
        """Распаковка ZIP"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_zip_sync, filepath, outdir, pwd)

    def _extract_zip_sync(self, filepath: Path, outdir: Path, pwd: Optional[str]) -> bool:
        try:
            with pyzipper.AESZipFile(str(filepath)) as zf:
                zf.pwd = pwd.encode() if pwd else None
                zf.extractall(str(outdir))
            return True
        except:
            return False

    async def _extract_7z(self, filepath: Path, outdir: Path, pwd: Optional[str]) -> bool:
        """Распаковка 7Z"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_7z_sync, filepath, outdir, pwd)

    def _extract_7z_sync(self, filepath: Path, outdir: Path, pwd: Optional[str]) -> bool:
        try:
            with py7zr.SevenZipFile(str(filepath), mode='r', password=pwd) as archive:
                archive.extractall(str(outdir))
            return True
        except:
            return False

    async def _extract_rar(self, filepath: Path, outdir: Path, pwd: Optional[str]) -> bool:
        """Распаковка RAR"""
        try:
            p_arg = f"-p{pwd}" if pwd else "-p-"
            cmd = [self.unrar_path, "x", p_arg, "-y", str(filepath), str(outdir)]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await proc.communicate()
            return proc.returncode == 0
        except:
            return False


# ================= KEYWORD SCANNER =================
class KeywordScanner:
    """Сканер ключевых слов в файлах"""

    def __init__(self, keywords: Set[str]):
        self.keywords = {k.lower() for k in keywords}
        logger.info(f"Загружено {len(self.keywords)} ключевых слов")

    def scan_file(self, file_path: Path) -> List[Tuple[int, str, List[str]]]:
        """
        Сканировать файл на наличие ключевых слов
        Returns: [(номер_строки, текст_строки, [найденные_ключевые_слова])]
        """
        results = []
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_no, line in enumerate(f, start=1):
                    line_lower = line.lower()
                    found_keywords = [k for k in self.keywords if k in line_lower]

                    if found_keywords:
                        results.append((line_no, line.strip(), found_keywords))
        except Exception as e:
            logger.error(f"Ошибка чтения файла {file_path}: {e}")

        return results

    def scan_directory(self, directory: Path) -> Dict[str, List[Tuple[int, str, List[str]]]]:
        """
        Сканировать все .txt файлы в директории
        Returns: {путь_к_файлу: [(строка, текст, [ключи])]}
        """
        matches = {}

        for txt_file in directory.rglob("*.txt"):
            hits = self.scan_file(txt_file)
            if hits:
                matches[str(txt_file)] = hits

        return matches


# ================= FILE PROCESSOR =================
class FileProcessor:
    """Процессор файлов - скачивание, распаковка, сканирование"""

    def __init__(
        self,
        config: Config,
        dedup_store: DeduplicationStore,
        password_manager: PasswordManager,
        keyword_scanner: KeywordScanner,
        notification_manager: NotificationManager,
        stats: Statistics
    ):
        self.config = config
        self.dedup = dedup_store
        self.password_manager = password_manager
        self.scanner = keyword_scanner
        self.notifier = notification_manager
        self.stats = stats
        self.extractor = ArchiveExtractor(password_manager)
        self.download_semaphore = asyncio.Semaphore(config.max_parallel_downloads)

    async def process_document(self, client: TelegramClient, doc: Document):
        """Обработать документ: скачать, распаковать, просканировать"""
        try:
            # Получаем имя и размер
            filename, size = self._get_filename_and_size(doc)

            # Проверяем расширение
            if not self._is_supported(filename):
                logger.debug(f"Пропуск неподдерживаемого файла: {filename}")
                return

            # Проверяем размер
            if size > self.config.max_file_size_mb * 1024 * 1024:
                logger.warning(f"Файл слишком большой: {filename} ({size / 1024 / 1024:.1f} MB)")
                self.stats.files_skipped += 1
                return

            # Проверяем дедупликацию
            uid = f"{doc.id}:{doc.access_hash}:{getattr(doc, 'dc_id', '')}"
            if await self.dedup.is_duplicate(uid, filename, size):
                logger.info(f"⏭ Пропуск дубликата: {filename}")
                self.stats.files_skipped += 1
                return

            # Скачиваем
            downloaded_path = await self._download(client, doc, filename, size)
            if not downloaded_path:
                self.stats.files_failed += 1
                return

            # Вычисляем quick hash
            quick_hash = await self._compute_quick_hash(downloaded_path)

            # Добавляем в dedup
            await self.dedup.add(uid, filename, size, quick_hash)
            self.stats.files_downloaded += 1

            # Обрабатываем файл
            matches = await self._process_file(downloaded_path)

            # Если найдены совпадения
            if matches:
                await self._handle_matches(filename, matches)
                self.stats.matches_found += len(matches)

            # Cleanup
            if self.config.cleanup_downloads and downloaded_path.exists():
                downloaded_path.unlink()
                logger.debug(f"Удален скачанный файл: {filename}")

        except Exception as e:
            logger.error(f"Ошибка обработки документа: {e}", exc_info=True)
            self.stats.errors += 1

    def _get_filename_and_size(self, doc: Document) -> Tuple[str, int]:
        """Получить имя файла и размер"""
        filename = None
        size = getattr(doc, "size", 0)

        if doc.attributes:
            for attr in doc.attributes:
                if hasattr(attr, "file_name"):
                    filename = attr.file_name
                    break

        if not filename:
            filename = f"file_{doc.id}"

        return filename, size

    def _is_supported(self, filename: str) -> bool:
        """Проверить, поддерживается ли расширение файла"""
        return Path(filename).suffix.lower() in self.config.supported_exts

    async def _download(
        self,
        client: TelegramClient,
        doc: Document,
        filename: str,
        size: int
    ) -> Optional[Path]:
        """Скачать документ"""
        out_path = self.config.download_dir / filename
        self.config.download_dir.mkdir(parents=True, exist_ok=True)

        async with self.download_semaphore:
            try:
                logger.info(f"📥 Начало загрузки: {filename} ({size / 1024 / 1024:.1f} MB)")

                with open(out_path, "wb") as f:
                    await download_file(
                        client,
                        doc,
                        f,
                        progress_callback=lambda done, total: logger.debug(
                            f"{filename}: {done/1024/1024:.1f}/{total/1024/1024:.1f} MB ({done/total*100:.0f}%)"
                        )
                    )

                logger.info(f"✅ Загружен: {filename}")
                return out_path

            except FloodWaitError as e:
                logger.warning(f"⏰ FloodWait: {e.seconds} сек для {filename}")
                await asyncio.sleep(e.seconds + 1)
                return await self._download(client, doc, filename, size)

            except Exception as e:
                logger.error(f"❌ Ошибка загрузки {filename}: {e}")
                if out_path.exists():
                    out_path.unlink()
                return None

    async def _compute_quick_hash(self, file_path: Path) -> Optional[str]:
        """Вычислить быстрый хеш файла"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self._compute_quick_hash_sync,
                file_path
            )
        except Exception as e:
            logger.debug(f"Ошибка вычисления хеша: {e}")
            return None

    def _compute_quick_hash_sync(self, file_path: Path) -> str:
        """Синхронное вычисление быстрого хеша"""
        h = hashlib.sha256()
        bytes_to_read = self.config.hash_quick_bytes_mb * 1024 * 1024
        size = file_path.stat().st_size

        with open(file_path, "rb") as f:
            first = f.read(bytes_to_read)
            h.update(first)

            if size > bytes_to_read:
                f.seek(max(0, size - bytes_to_read))
                last = f.read(bytes_to_read)
                h.update(last)

        return h.hexdigest()

    async def _process_file(self, file_path: Path) -> Dict[str, List[Tuple[int, str, List[str]]]]:
        """Обработать файл: распаковать если архив, просканировать"""
        ext = file_path.suffix.lower()

        # Если это txt файл - сразу сканируем
        if ext == ".txt":
            matches = self.scanner.scan_file(file_path)
            return {str(file_path): matches} if matches else {}

        # Если архив - распаковываем
        if ext in {".zip", ".7z", ".rar"}:
            extract_dir = self.config.extract_dir / f"extract_{file_path.stem}"

            success, used_password = await self.extractor.extract(file_path, extract_dir)

            if not success:
                logger.warning(f"❌ Не удалось распаковать: {file_path.name}")
                self.stats.archives_failed += 1
                return {}

            self.stats.archives_extracted += 1

            # Сканируем распакованные файлы
            matches = self.scanner.scan_directory(extract_dir)

            # Cleanup извлеченных файлов
            if self.config.cleanup_extracted:
                import shutil
                shutil.rmtree(extract_dir, ignore_errors=True)
                logger.debug(f"Удалена папка распаковки: {extract_dir.name}")

            return matches

        return {}

    async def _handle_matches(self, original_filename: str, matches: Dict):
        """Обработать найденные совпадения"""
        # Записываем в файл
        with open(self.config.output_matches_file, "a", encoding="utf-8") as f:
            for file_path, hits in matches.items():
                for line_no, line_text, found_keywords in hits:
                    f.write(
                        f"{original_filename} | {Path(file_path).name} | "
                        f"строка {line_no} | ключи: {', '.join(found_keywords)} | "
                        f"{line_text}\n"
                    )

        # Логируем
        logger.info(f"🎯 Найдены совпадения в: {original_filename}")
        for file_path, hits in matches.items():
            logger.info(f"   📄 {Path(file_path).name}: {len(hits)} совпадений")
            for line_no, line_text, found_keywords in hits[:3]:  # Первые 3
                logger.info(f"      Строка {line_no}: {found_keywords}")

        # Отправляем уведомление
        summary_lines = []
        for file_path, hits in matches.items():
            all_keywords = {kw for _, _, kws in hits for kw in kws}
            summary_lines.append(f"{Path(file_path).name}: {', '.join(sorted(all_keywords))}")

        notification_text = (
            f"🎯 Найдено в: {original_filename}\n"
            + "\n".join(summary_lines)
        )

        await self.notifier.notify(notification_text)


# ================= TELEGRAM MONITOR =================
class TelegramMonitor:
    """Главный класс мониторинга Telegram"""

    def __init__(self, config: Config):
        self.config = config
        self.stats = Statistics()

        # Инициализация компонентов
        self.client = TelegramClient(
            str(config.session_name),
            config.api_id,
            config.api_hash
        )

        self.bot = None
        if config.bot_token and config.admin_chat_id:
            self.bot = Bot(
                token=config.bot_token,
                default=DefaultBotProperties(parse_mode="MarkdownV2")
            )

        self.notifier = NotificationManager(
            self.bot,
            config.admin_chat_id,
            config.notification_batch_size,
            config.notification_batch_timeout
        )

        self.dedup = DeduplicationStore(config.download_dir / "dedup_store.json")
        self.password_manager = PasswordManager(config.password_file, config.password_history_file)

        # Загрузка ключевых слов
        keywords = self._load_keywords()
        self.scanner = KeywordScanner(keywords)

        self.processor = FileProcessor(
            config,
            self.dedup,
            self.password_manager,
            self.scanner,
            self.notifier,
            self.stats
        )

        # Очередь и воркеры
        self.queue: asyncio.Queue = asyncio.Queue()
        self.workers: List[asyncio.Task] = []
        self.running = False

    def _load_keywords(self) -> Set[str]:
        """Загрузить ключевые слова из файла"""
        if not self.config.keywords_file or not self.config.keywords_file.exists():
            logger.warning(f"Файл ключевых слов не найден: {self.config.keywords_file}")
            return set()

        with open(self.config.keywords_file, 'r', encoding='utf-8', errors='ignore') as f:
            keywords = {line.strip() for line in f if line.strip()}

        logger.info(f"Загружено {len(keywords)} ключевых слов из {self.config.keywords_file}")
        return keywords

    async def start(self):
        """Запустить мониторинг"""
        logger.info("🚀 Запуск Telegram Monitor...")

        # Создаем директории
        self.config.download_dir.mkdir(parents=True, exist_ok=True)
        self.config.extract_dir.mkdir(parents=True, exist_ok=True)

        # Подключаемся к Telegram
        await self.client.start()
        logger.info("✅ Подключен к Telegram")

        # Получаем канал
        try:
            channel = await self.client.get_entity(self.config.channel_username)
            logger.info(f"✅ Подписан на канал: {self.config.channel_username}")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к каналу: {e}")
            raise

        # Запускаем уведомления
        await self.notifier.start()

        # Запускаем воркеры
        self.running = True
        for i in range(self.config.num_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)

        logger.info(f"✅ Запущено {self.config.num_workers} воркеров")

        # Регистрируем обработчик новых сообщений
        @self.client.on(events.NewMessage(chats=channel))
        async def handler(event):
            if event.document:
                await self.queue.put(event.document)
                logger.debug(f"📨 Документ добавлен в очередь: {event.document.id}")

        logger.info("▶️ Мониторинг запущен. Ожидание новых файлов...")
        await self.notifier.notify("🟢 Мониторинг запущен")

        # Запускаем клиент
        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("⏹ Получен сигнал остановки")
        finally:
            await self.stop()

    async def _worker(self, worker_id: int):
        """Воркер для обработки файлов из очереди"""
        logger.info(f"Воркер #{worker_id} запущен")

        while self.running:
            try:
                # Получаем документ из очереди с таймаутом
                try:
                    doc = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                logger.debug(f"Воркер #{worker_id} обрабатывает документ {doc.id}")

                # Обрабатываем
                await self.processor.process_document(self.client, doc)

                # Отмечаем задачу выполненной
                self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в воркере #{worker_id}: {e}", exc_info=True)
                self.stats.errors += 1

        logger.info(f"Воркер #{worker_id} остановлен")

    async def stop(self):
        """Остановить мониторинг"""
        logger.info("🛑 Остановка мониторинга...")

        self.running = False

        # Ждем завершения очереди
        if not self.queue.empty():
            logger.info(f"Ожидание завершения {self.queue.qsize()} задач...")
            await self.queue.join()

        # Останавливаем воркеры
        for worker in self.workers:
            worker.cancel()

        await asyncio.gather(*self.workers, return_exceptions=True)

        # Отправляем финальную статистику
        await self.notifier.notify(f"🔴 Мониторинг остановлен\n\n{self.stats.summary()}")
        await self.notifier.stop()

        # Закрываем бота
        if self.bot:
            await self.bot.session.close()

        logger.info("✅ Мониторинг остановлен")
        logger.info(self.stats.summary())


# ================= MAIN =================
async def main():
    """Главная функция"""
    try:
        # Загружаем конфигурацию
        config = Config.from_env()
        config.validate()

        # Создаем и запускаем монитор
        monitor = TelegramMonitor(config)
        await monitor.start()

    except KeyboardInterrupt:
        logger.info("⏹ Остановлено пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
