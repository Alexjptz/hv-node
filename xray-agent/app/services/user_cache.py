"""In-memory cache for XRay users to avoid frequent config file reads."""
from datetime import datetime, timedelta
from typing import Set

from app.core.logging import get_logger
from app.services.xray_manager import load_xray_config

logger = get_logger(__name__)


class UserCache:
    """In-memory cache for XRay users."""

    def __init__(self, sync_interval_minutes: int = 5):
        """Initialize user cache.

        Args:
            sync_interval_minutes: How often to sync with config file (default: 5 minutes)
        """
        self._users: Set[str] = set()  # UUID пользователей
        self._last_sync: datetime | None = None
        self._sync_interval = timedelta(minutes=sync_interval_minutes)
        self._last_xray_reload: datetime | None = None  # Время последней перезагрузки XRay

    def exists(self, user_uuid: str, check_sync: bool = True) -> bool:
        """Проверить существование пользователя в кэше.

        Args:
            user_uuid: UUID пользователя
            check_sync: Синхронизировать с конфигом перед проверкой (default: True)

        Returns:
            True если пользователь существует, False иначе
        """
        # Автоматическая синхронизация если нужно
        if check_sync:
            self._maybe_sync()
        return user_uuid in self._users

    def add(self, user_uuid: str):
        """Добавить пользователя в кэш.

        Args:
            user_uuid: UUID пользователя
        """
        self._users.add(user_uuid)
        logger.debug("User added to cache", user_uuid=user_uuid)

    def remove(self, user_uuid: str):
        """Удалить пользователя из кэша.

        Args:
            user_uuid: UUID пользователя
        """
        self._users.discard(user_uuid)
        logger.debug("User removed from cache", user_uuid=user_uuid)

    def sync_from_config(self):
        """Синхронизировать кэш с конфиг файлом."""
        try:
            config = load_xray_config()
            users = set()
            for inbound in config.get("inbounds", []):
                if inbound.get("protocol") == "vless":
                    clients = inbound.get("settings", {}).get("clients", [])
                    for client in clients:
                        user_uuid = client.get("id")
                        if user_uuid:
                            users.add(user_uuid)

            old_count = len(self._users)
            self._users = users
            self._last_sync = datetime.now()
            logger.info(
                "Cache synced from config",
                users_count=len(users),
                added=len(users) - old_count,
            )
        except Exception as e:
            logger.error("Failed to sync cache from config", error=str(e))

    def _maybe_sync(self):
        """Синхронизировать кэш если прошло достаточно времени."""
        if self._last_sync is None:
            # Первая синхронизация
            self.sync_from_config()
        elif datetime.now() - self._last_sync >= self._sync_interval:
            # Время синхронизировать
            self.sync_from_config()

    def clear(self):
        """Очистить кэш."""
        self._users.clear()
        self._last_sync = None
        logger.debug("Cache cleared")

    def mark_xray_reloaded(self):
        """Отметить что XRay был перезагружен."""
        self._last_xray_reload = datetime.now()
        logger.debug("XRay reload marked", timestamp=self._last_xray_reload.isoformat())

    def should_reload_xray(self, user_uuid: str) -> bool:
        """Проверить нужно ли перезагрузить XRay для пользователя.

        Args:
            user_uuid: UUID пользователя

        Returns:
            True если нужно перезагрузить XRay, False иначе
        """
        # Если XRay был перезагружен недавно (менее 5 минут назад), не перезагружаем
        if self._last_xray_reload:
            time_since_reload = datetime.now() - self._last_xray_reload
            if time_since_reload < timedelta(minutes=5):
                return False

        # Если пользователь в кэше (и кэш недавно синхронизирован), не перезагружаем
        if self._last_sync and datetime.now() - self._last_sync < timedelta(minutes=1):
            if user_uuid in self._users:
                return False

        # Проверить в конфиге без синхронизации кэша
        try:
            config = load_xray_config()
            for inbound in config.get("inbounds", []):
                if inbound.get("protocol") == "vless":
                    clients = inbound.get("settings", {}).get("clients", [])
                    for client in clients:
                        if client.get("id") == user_uuid:
                            # Пользователь в конфиге, но возможно не в памяти XRay
                            # Если XRay был перезапущен недавно или кэш пустой → перезагрузить
                            if not self._last_xray_reload or datetime.now() - self._last_xray_reload > timedelta(minutes=5):
                                return True
                            return False
        except Exception:
            pass

        return False

    def get_all(self) -> Set[str]:
        """Получить все UUID пользователей из кэша.

        Returns:
            Множество UUID пользователей
        """
        self._maybe_sync()
        return self._users.copy()

    def count(self) -> int:
        """Получить количество пользователей в кэше.

        Returns:
            Количество пользователей
        """
        self._maybe_sync()
        return len(self._users)


# Глобальный экземпляр кэша
user_cache = UserCache()
