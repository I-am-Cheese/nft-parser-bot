"""
База данных для хранения пользователей и статистики
PostgreSQL only
"""
import asyncpg
from datetime import datetime, date
from typing import List, Optional, Tuple
from dataclasses import dataclass

from config import DATABASE_URL


@dataclass
class User:
    """Модель пользователя"""
    user_id: int
    username: Optional[str]
    first_name: str
    last_name: Optional[str]
    created_at: datetime
    request_count: int = 0


@dataclass
class Request:
    """Модель запроса"""
    id: int
    user_id: int
    request_type: str  # 'random', 'female'
    collection: str
    result_count: int
    created_at: datetime


class Database:
    """Асинхронная база данных PostgreSQL"""
    
    def __init__(self):
        self._initialized = False
        self.pool = None
    
    async def init(self):
        """Инициализация базы данных"""
        if self._initialized:
            return
        
        # Создаём connection pool
        self.pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        
        async with self.pool.acquire() as conn:
            # Таблица пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT NOT NULL,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    request_count INTEGER DEFAULT 0,
                    is_blocked BOOLEAN DEFAULT FALSE
                )
            """)
            
            # Таблица запросов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    request_type TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    result_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Таблица фильтров пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_filters (
                    user_id BIGINT PRIMARY KEY,
                    filters TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Таблица прокси
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id SERIAL PRIMARY KEY,
                    proxy_url TEXT UNIQUE NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    last_check TIMESTAMP,
                    fail_count INTEGER DEFAULT 0,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    added_by BIGINT
                )
            """)
            
            # Индексы
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_requests_user_id 
                ON requests(user_id)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_requests_created_at 
                ON requests(created_at)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_proxies_active 
                ON proxies(is_active)
            """)
        
        self._initialized = True
        print("✅ База данных PostgreSQL инициализирована")
    
    async def close(self):
        """Закрыть соединение с БД"""
        if self.pool:
            await self.pool.close()
            print("✅ Соединение с PostgreSQL закрыто")
    
    # ============================================================================
    # МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ
    # ============================================================================
    
    async def add_user(
        self,
        user_id: int,
        username: Optional[str],
        first_name: str,
        last_name: Optional[str] = None
    ) -> bool:
        """Добавить или обновить пользователя"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name
                """, user_id, username, first_name, last_name)
            return True
        except Exception as e:
            print(f"❌ Ошибка добавления пользователя: {e}")
            return False
    
    async def get_user(self, user_id: int) -> Optional[User]:
        """Получить пользователя по ID"""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE user_id = $1",
                    user_id
                )
                if row:
                    return User(
                        user_id=row["user_id"],
                        username=row["username"],
                        first_name=row["first_name"],
                        last_name=row["last_name"],
                        created_at=row["created_at"],
                        request_count=row["request_count"]
                    )
            return None
        except Exception as e:
            print(f"❌ Ошибка получения пользователя: {e}")
            return None
    
    async def add_request(
        self,
        user_id: int,
        request_type: str,
        collection: str,
        result_count: int = 0
    ) -> bool:
        """Добавить запрос и увеличить счётчик пользователя"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("""
                        INSERT INTO requests (user_id, request_type, collection, result_count)
                        VALUES ($1, $2, $3, $4)
                    """, user_id, request_type, collection, result_count)
                    
                    await conn.execute("""
                        UPDATE users SET request_count = request_count + 1
                        WHERE user_id = $1
                    """, user_id)
            return True
        except Exception as e:
            print(f"❌ Ошибка добавления запроса: {e}")
            return False
    
    async def get_total_users(self) -> int:
        """Получить общее количество пользователей"""
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("SELECT COUNT(*) FROM users")
                return result or 0
        except Exception as e:
            print(f"❌ Ошибка получения количества пользователей: {e}")
            return 0
    
    async def get_new_users_24h(self) -> int:
        """Получить количество новых пользователей за последние 24 часа"""
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("""
                    SELECT COUNT(*) FROM users
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                """)
                return result or 0
        except Exception as e:
            print(f"❌ Ошибка получения новых пользователей за 24 часа: {e}")
            return 0
    
    async def get_blocked_users_count(self) -> int:
        """Получить количество пользователей, заблокировавших бота"""
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("""
                    SELECT COUNT(*) FROM users
                    WHERE is_blocked = TRUE
                """)
                return result or 0
        except Exception as e:
            print(f"❌ Ошибка получения заблокированных пользователей: {e}")
            return 0
    
    async def get_requests_today(self) -> int:
        """Получить количество запросов за сегодня"""
        try:
            today = date.today()
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("""
                    SELECT COUNT(*) FROM requests
                    WHERE DATE(created_at) = $1
                """, today)
                return result or 0
        except Exception as e:
            print(f"❌ Ошибка получения запросов за сегодня: {e}")
            return 0
    
    async def get_all_user_ids(self) -> List[int]:
        """Получить все ID пользователей для рассылки"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT user_id FROM users")
                return [row["user_id"] for row in rows]
        except Exception as e:
            print(f"❌ Ошибка получения списка пользователей: {e}")
            return []
    
    async def get_user_ids_batch(self, limit: int = 100, offset: int = 0) -> List[int]:
        """Получить ID пользователей батчами для рассылки"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_id FROM users ORDER BY user_id LIMIT $1 OFFSET $2",
                    limit, offset
                )
                return [row["user_id"] for row in rows]
        except Exception as e:
            print(f"❌ Ошибка получения батча пользователей: {e}")
            return []
    
    async def get_top_users(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Получить топ пользователей по количеству запросов"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT first_name, username, request_count
                    FROM users
                    ORDER BY request_count DESC
                    LIMIT $1
                """, limit)
                return [
                    (
                        f"@{row['username']}" if row['username'] else row['first_name'],
                        row['request_count']
                    )
                    for row in rows
                ]
        except Exception as e:
            print(f"❌ Ошибка получения топ пользователей: {e}")
            return []
    
    async def mark_user_blocked(self, user_id: int) -> bool:
        """Пометить пользователя как заблокировавшего бота"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET is_blocked = TRUE WHERE user_id = $1",
                    user_id
                )
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления статуса блокировки: {e}")
            return False
    
    # ============================================================================
    # МЕТОДЫ ДЛЯ ФИЛЬТРОВ
    # ============================================================================
    
    async def get_user_filters(self, user_id: int) -> dict:
        """Получить фильтры пользователя"""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT filters FROM user_filters WHERE user_id = $1",
                    user_id
                )
                if row and row["filters"]:
                    import json
                    return json.loads(row["filters"])
            return {"collections": [], "models": [], "backdrops": []}
        except Exception as e:
            print(f"❌ Ошибка получения фильтров: {e}")
            return {"collections": [], "models": [], "backdrops": []}
    
    async def save_user_filters(self, user_id: int, filters: dict) -> bool:
        """Сохранить фильтры пользователя"""
        try:
            import json
            filters_json = json.dumps(filters)
            
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_filters (user_id, filters)
                    VALUES ($1, $2)
                    ON CONFLICT(user_id) DO UPDATE SET
                        filters = EXCLUDED.filters,
                        updated_at = CURRENT_TIMESTAMP
                """, user_id, filters_json)
            return True
        except Exception as e:
            print(f"❌ Ошибка сохранения фильтров: {e}")
            return False
    
    # ============================================================================
    # МЕТОДЫ ДЛЯ ПРОКСИ
    # ============================================================================
    
    async def get_all_proxies(self) -> List[str]:
        """Получить все прокси из БД"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('SELECT proxy_url FROM proxies')
                return [row["proxy_url"] for row in rows]
        except Exception as e:
            print(f"❌ Ошибка получения прокси: {e}")
            return []
    
    async def get_active_proxies(self) -> List[str]:
        """Получить только активные прокси"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    'SELECT proxy_url FROM proxies WHERE is_active = TRUE'
                )
                return [row["proxy_url"] for row in rows]
        except Exception as e:
            print(f"❌ Ошибка получения активных прокси: {e}")
            return []
    
    async def add_proxy(self, proxy_url: str, admin_id: int, is_active: bool = True):
        """Добавить новый прокси"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    '''INSERT INTO proxies (proxy_url, added_by, is_active, last_check)
                       VALUES ($1, $2, $3, CURRENT_TIMESTAMP)''',
                    proxy_url, admin_id, is_active
                )
            return True
        except Exception as e:
            print(f"❌ Ошибка добавления прокси: {e}")
            return False
    
    async def remove_proxy(self, proxy_url: str):
        """Удалить прокси"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    'DELETE FROM proxies WHERE proxy_url = $1',
                    proxy_url
                )
            return True
        except Exception as e:
            print(f"❌ Ошибка удаления прокси: {e}")
            return False
    
    async def update_proxy_status(self, proxy_url: str, is_active: bool):
        """Обновить статус прокси"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    '''UPDATE proxies 
                       SET is_active = $1, last_check = CURRENT_TIMESTAMP
                       WHERE proxy_url = $2''',
                    is_active, proxy_url
                )
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления статуса прокси: {e}")
            return False


# Singleton
db = Database()
