"""
Менеджер кэша с TTL и автоочисткой
"""
import time
from collections import OrderedDict
from typing import Optional, Any


class CacheManager:
    """
    Кэш с автоматической очисткой устаревших записей
    
    Args:
        max_size: Максимальное количество элементов в кэше
        ttl: Время жизни элемента в секундах (по умолчанию 1 час)
    """
    
    def __init__(self, max_size: int = 100, ttl: int = 3600):
        self.cache = OrderedDict()
        self.timestamps = {}
        self.max_size = max_size
        self.ttl = ttl
    
    def _clean_expired(self):
        """Удалить устаревшие элементы"""
        now = time.time()
        expired_keys = [
            key for key, timestamp in self.timestamps.items()
            if now - timestamp > self.ttl
        ]
        
        for key in expired_keys:
            self.cache.pop(key, None)
            self.timestamps.pop(key, None)
    
    def _enforce_max_size(self):
        """Удалить старые элементы если превышен лимит"""
        while len(self.cache) >= self.max_size:
            # Удаляем самый старый элемент (первый в OrderedDict)
            oldest_key = next(iter(self.cache))
            self.cache.pop(oldest_key)
            self.timestamps.pop(oldest_key, None)
    
    def add(self, key: str, value: Any):
        """
        Добавить элемент в кэш
        
        Args:
            key: Ключ
            value: Значение
        """
        # Очищаем устаревшие
        self._clean_expired()
        
        # Проверяем размер
        self._enforce_max_size()
        
        # Добавляем элемент
        self.cache[key] = value
        self.timestamps[key] = time.time()
    
    def get(self, key: str) -> Optional[Any]:
        """
        Получить элемент из кэша
        
        Args:
            key: Ключ
        
        Returns:
            Значение или None если не найдено/устарело
        """
        # Проверяем, не устарел ли элемент
        if key in self.timestamps:
            age = time.time() - self.timestamps[key]
            if age > self.ttl:
                # Элемент устарел, удаляем его
                self.remove(key)
                return None
        
        return self.cache.get(key)
    
    def remove(self, key: str):
        """
        Удалить элемент из кэша
        
        Args:
            key: Ключ
        """
        self.cache.pop(key, None)
        self.timestamps.pop(key, None)
    
    def exists(self, key: str) -> bool:
        """
        Проверить существование элемента
        
        Args:
            key: Ключ
        
        Returns:
            True если элемент существует и не устарел
        """
        return self.get(key) is not None
    
    def clear(self):
        """Очистить весь кэш"""
        self.cache.clear()
        self.timestamps.clear()
    
    def get_stats(self) -> dict:
        """Получить статистику кэша"""
        self._clean_expired()
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl": self.ttl,
        }


# Singleton instance
cache_manager = CacheManager(max_size=200, ttl=1800)
