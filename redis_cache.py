"""
Redis кэш для хранения результатов парсинга
"""
import redis.asyncio as redis
import json
from typing import Optional
import logging


class RedisCache:
    """
    Redis кэш с TTL и автоматической сериализацией
    """
    
    def __init__(self, redis_url: str):
        """
        Args:
            redis_url: URL подключения к Redis
        """
        self.redis_url = redis_url
        self.redis = None
        self.logger = logging.getLogger(__name__)
    
    async def init(self):
        """Инициализация подключения к Redis"""
        if self.redis is None:
            self.redis = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                encoding="utf-8"
            )
            self.logger.info("✅ Redis подключен")
    
    async def set(self, key: str, value: dict, ttl: int = 21600):
        """
        Сохранить с TTL (6 часов по умолчанию)
        
        Args:
            key: Ключ
            value: Значение (dict)
            ttl: Время жизни в секундах
        """
        if self.redis is None:
            await self.init()
        
        try:
            await self.redis.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения в Redis: {e}")
    
    async def get(self, key: str) -> Optional[dict]:
        """
        Получить значение
        
        Args:
            key: Ключ
        
        Returns:
            Dict или None если не найдено
        """
        if self.redis is None:
            await self.init()
        
        try:
            data = await self.redis.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            self.logger.error(f"❌ Ошибка чтения из Redis: {e}")
            return None
    
    async def exists(self, key: str) -> bool:
        """Проверить существование ключа"""
        if self.redis is None:
            await self.init()
        
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки ключа: {e}")
            return False
    
    async def delete(self, key: str):
        """Удалить ключ"""
        if self.redis is None:
            await self.init()
        
        try:
            await self.redis.delete(key)
        except Exception as e:
            self.logger.error(f"❌ Ошибка удаления ключа: {e}")
    
    async def close(self):
        """Закрыть соединение"""
        if self.redis:
            await self.redis.close()
            self.logger.info("✅ Redis отключен")


# Singleton instance (будет инициализирован в main.py)
redis_cache = None