"""
Менеджер прокси с автоматической проверкой работоспособности
"""
import asyncio
import aiohttp
from typing import List, Dict, Optional, Set
from datetime import datetime
import logging

from config import PARSER_API_URL


class ProxyManager:
    """Менеджер для управления и проверки прокси"""
    
    def __init__(self, db, check_timeout: int = 10, verbose: bool = True):
        """
        Args:
            db: Database instance
            check_timeout: Таймаут для проверки прокси (секунды)
            verbose: Выводить логи
        """
        self.db = db
        self.check_timeout = check_timeout
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)
        
        # Кэш активных прокси для быстрого доступа
        self._active_proxies_cache: List[str] = []
        self._cache_updated_at: Optional[datetime] = None
        self._cache_ttl = 300  # 5 минут
    
    async def check_proxy(self, proxy: str) -> bool:
        """
        Проверить работоспособность одного прокси
        
        Args:
            proxy: URL прокси (http://user:pass@host:port)
        
        Returns:
            True если прокси работает, False если нет
        """
        test_params = {
            "collection": "AstralShard",
            "offset": 0,
            "limit": 1
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=self.check_timeout)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    PARSER_API_URL,
                    params=test_params,
                    proxy=proxy,
                    ssl=False
                ) as response:
                    # Прокси работает если статус в диапазоне HTTP кодов (100-599)
                    return 100 <= response.status < 600
            
            return False
        
        except asyncio.TimeoutError:
            if self.verbose:
                self.logger.warning(f"⏱ Timeout для прокси: {self._mask_proxy(proxy)}")
            return False
        
        except aiohttp.ClientError as e:
            if self.verbose:
                self.logger.warning(f"❌ Ошибка прокси {self._mask_proxy(proxy)}: {type(e).__name__}")
            return False
        
        except Exception as e:
            if self.verbose:
                self.logger.error(f"❌ Неожиданная ошибка для {self._mask_proxy(proxy)}: {e}")
            return False
    
    async def check_all_proxies(self) -> Dict[str, any]:
        """Проверить все прокси из базы данных"""
        if self.verbose:
            self.logger.info("🔍 Начинаем проверку всех прокси...")
        
        all_proxies = await self.db.get_all_proxies()
        
        if not all_proxies:
            if self.verbose:
                self.logger.warning("⚠️ Нет прокси в базе данных")
            return {
                'total': 0,
                'alive': 0,
                'dead': 0,
                'alive_list': [],
                'dead_list': []
            }
        
        if self.verbose:
            self.logger.info(f"📊 Проверяем {len(all_proxies)} прокси...")
        
        # 🔥 РЕШЕНИЕ: Проверяем прокси с задержкой, а не все сразу
        alive_list = []
        dead_list = []
        
        for i, proxy in enumerate(all_proxies, 1):
            if self.verbose:
                self.logger.info(f"🔍 Проверка {i}/{len(all_proxies)}: {self._mask_proxy(proxy)}")
            
            is_alive = await self.check_proxy(proxy)
            
            if is_alive:
                alive_list.append(proxy)
            else:
                dead_list.append(proxy)
            
            # Задержка между проверками (1-2 секунды)
            if i < len(all_proxies):  # Не ждём после последнего
                await asyncio.sleep(1.5)
        
        result = {
            'total': len(all_proxies),
            'alive': len(alive_list),
            'dead': len(dead_list),
            'alive_list': alive_list,
            'dead_list': dead_list
        }
        
        if self.verbose:
            self.logger.info(
                f"✅ Проверка завершена: "
                f"{result['alive']} живых, {result['dead']} мертвых"
            )
        
        return result
    
    async def remove_dead_proxies(self, dead_proxies: List[str]) -> int:
        """
        Удалить мертвые прокси из базы данных
        
        Args:
            dead_proxies: Список мертвых прокси
        
        Returns:
            Количество удаленных прокси
        """
        if not dead_proxies:
            return 0
        
        removed_count = 0
        
        for proxy in dead_proxies:
            try:
                await self.db.remove_proxy(proxy)
                removed_count += 1
                
                if self.verbose:
                    self.logger.info(f"🗑 Удален прокси: {self._mask_proxy(proxy)}")
            
            except Exception as e:
                self.logger.error(f"❌ Ошибка удаления прокси {self._mask_proxy(proxy)}: {e}")
        
        # Очищаем кэш
        self._invalidate_cache()
        
        if self.verbose:
            self.logger.info(f"🗑 Всего удалено: {removed_count} прокси")
        
        return removed_count
    
    async def get_active_proxies(self, use_cache: bool = True) -> List[str]:
        """
        Получить список активных прокси
        
        Args:
            use_cache: Использовать кэш (по умолчанию True)
        
        Returns:
            Список активных прокси
        """
        # Проверяем кэш
        if use_cache and self._is_cache_valid():
            return self._active_proxies_cache.copy()
        
        # Загружаем из БД
        proxies = await self.db.get_active_proxies()
        
        # Обновляем кэш
        self._active_proxies_cache = proxies
        self._cache_updated_at = datetime.now()
        
        return proxies.copy()
    
    async def add_proxy(self, proxy: str, admin_id: int, check_before_add: bool = True) -> Dict[str, any]:
        """
        Добавить новый прокси
        
        Args:
            proxy: URL прокси
            admin_id: ID администратора
            check_before_add: Проверить прокси перед добавлением
        
        Returns:
            Dict с результатом:
            {
                'success': bool,
                'message': str,
                'is_alive': bool (если check_before_add=True)
            }
        """
        # Валидация формата
        if not self._validate_proxy_format(proxy):
            return {
                'success': False,
                'message': '❌ Неверный формат прокси. Используйте: http://user:pass@host:port'
            }
        
        # Проверка на дубликат
        existing = await self.db.get_all_proxies()
        if proxy in existing:
            return {
                'success': False,
                'message': '⚠️ Этот прокси уже есть в базе'
            }
        
        # Проверка работоспособности (опционально)
        is_alive = True
        if check_before_add:
            if self.verbose:
                self.logger.info(f"🔍 Проверяем новый прокси: {self._mask_proxy(proxy)}")
            
            is_alive = await self.check_proxy(proxy)
            
            if not is_alive:
                return {
                    'success': False,
                    'message': '❌ Прокси не работает',
                    'is_alive': False
                }
        
        # Добавляем в БД
        try:
            await self.db.add_proxy(proxy, admin_id, is_alive)
            
            # Очищаем кэш
            self._invalidate_cache()
            
            if self.verbose:
                self.logger.info(f"✅ Прокси добавлен: {self._mask_proxy(proxy)}")
            
            return {
                'success': True,
                'message': '✅ Прокси успешно добавлен',
                'is_alive': is_alive
            }
        
        except Exception as e:
            self.logger.error(f"❌ Ошибка добавления прокси: {e}")
            return {
                'success': False,
                'message': f'❌ Ошибка: {str(e)}'
            }
    
    async def get_proxies_stats(self) -> Dict[str, any]:
        """
        Получить статистику по прокси
        
        Returns:
            Dict со статистикой
        """
        all_proxies = await self.db.get_all_proxies()
        active_proxies = await self.db.get_active_proxies()
        
        return {
            'total': len(all_proxies),
            'active': len(active_proxies),
            'inactive': len(all_proxies) - len(active_proxies)
        }
    
    def _validate_proxy_format(self, proxy: str) -> bool:
        """Валидация формата прокси"""
        if not proxy.startswith(('http://', 'https://')):
            return False
        
        # Базовая проверка на наличие @ и :
        if '@' not in proxy or ':' not in proxy:
            return False
        
        return True
    
    def _mask_proxy(self, proxy: str) -> str:
        """Замаскировать прокси для логов (скрыть пароль)"""
        try:
            if '@' in proxy:
                parts = proxy.split('@')
                if ':' in parts[0]:
                    protocol_and_user = parts[0].rsplit(':', 1)[0]
                    return f"{protocol_and_user}:***@{parts[1]}"
            return proxy
        except:
            return "***"
    
    def _is_cache_valid(self) -> bool:
        """Проверить валидность кэша"""
        if not self._cache_updated_at:
            return False
        
        elapsed = (datetime.now() - self._cache_updated_at).total_seconds()
        return elapsed < self._cache_ttl
    
    def _invalidate_cache(self):
        """Инвалидировать кэш"""
        self._cache_updated_at = None
        self._active_proxies_cache = []


# Глобальный экземпляр (будет инициализирован в main.py)
proxy_manager: Optional[ProxyManager] = None


async def init_proxy_manager(db):
    """
    Инициализировать глобальный proxy_manager
    
    Args:
        db: Database instance
    """
    global proxy_manager
    proxy_manager = ProxyManager(db, verbose=True)
    print("✅ ProxyManager инициализирован")


async def check_proxies_task(bot):
    """
    Фоновая задача для проверки прокси каждые 6 часов
    
    Args:
        bot: Bot instance для отправки уведомлений
    """
    from config import ADMIN_IDS
    
    while True:
        try:
            # Ждем 6 часов
            await asyncio.sleep(6 * 60 * 60)
            
            print("🔍 Запуск автоматической проверки прокси...")
            
            # Проверяем все прокси
            result = await proxy_manager.check_all_proxies()
            
            # Удаляем мертвые
            removed = await proxy_manager.remove_dead_proxies(result['dead_list'])
            
            # Формируем сообщение
            message = (
                f"🔍 **Автоматическая проверка прокси**\n\n"
                f"✅ Живых: {result['alive']}\n"
                f"❌ Мертвых: {result['dead']}\n"
                f"🗑 Удалено: {removed}\n"
                f"📊 Осталось в базе: {result['alive']}\n\n"
            )
            
            if result['dead'] > 0:
                message += "⚠️ **Мертвые прокси удалены из использования**"
            else:
                message += "✅ Все прокси работают исправно"
            
            # Отправляем уведомление всем админам
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        message,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"❌ Ошибка отправки уведомления админу {admin_id}: {e}")
            
            print(f"✅ Проверка завершена: {result['alive']} живых, {removed} удалено")
        
        except asyncio.CancelledError:
            print("🛑 Задача проверки прокси остановлена")
            break
        
        except Exception as e:
            print(f"❌ Ошибка в задаче проверки прокси: {e}")
            # Продолжаем работу даже при ошибке

            continue

