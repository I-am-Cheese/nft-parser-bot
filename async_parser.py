#!/usr/bin/env python3
"""
Минимальный standalone модуль для асинхронного парсинга NFT подарков Telegram
Поддержка: aiohttp, автоматическая ротация прокси, random range

Использование:
    parser = AsyncGiftParser(
        api_url="https://peek.tg/api/nft/gifts/search",
        proxies=["http://proxy1:port", "http://proxy2:port"],
        request_delay=0.3
    )
    
    # Обычный парсинг
    owners = await parser.parse_collection("AstralShard")
    
    # Парсинг с рандомным диапазоном
    owners = await parser.parse_collection_random_range("AstralShard", range_size=2000)
"""

import asyncio
import json
import random
from dataclasses import dataclass, asdict
from io import BytesIO
from typing import Dict, List, Optional, Set
from pathlib import Path

from proxy_manager import proxy_manager

import aiohttp

try:
    import zstandard
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class GiftInfo:
    """NFT подарок"""
    gift_number: int
    gift_name: str
    model: str
    pattern: str
    backdrop: str
    rarity_model: float
    rarity_pattern: float
    rarity_backdrop: float
    gift_link: str
    created_at: str
    market: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Owner:
    """Владелец NFT"""
    username: str
    profile_name: str
    link: str
    user_id: int
    gift_info: GiftInfo
    phone: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "username": self.username,
            "profile_name": self.profile_name,
            "link": self.link,
            "user_id": self.user_id,
            "phone": self.phone,
            "gift": self.gift_info.to_dict()
        }


# ============================================================================
# UTILS
# ============================================================================

def _decompress(raw: bytes, encoding: Optional[str]) -> bytes:
    """Декомпрессия ответа"""
    if not encoding:
        return raw
    
    enc = encoding.lower()
    
    # zstd
    if "zstd" in enc and HAS_ZSTD:
        try:
            dctx = zstandard.ZstdDecompressor()
            with dctx.stream_reader(BytesIO(raw)) as reader:
                return reader.read()
        except:
            pass
    
    # brotli
    if "br" in enc and HAS_BROTLI:
        try:
            return brotli.decompress(raw)
        except:
            pass
    
    # gzip
    if "gzip" in enc or "deflate" in enc:
        import gzip
        try:
            return gzip.decompress(raw)
        except:
            pass
    
    return raw


def _parse_owner(item: Dict, ignore_list: Set[str]) -> Optional[Owner]:
    """Парсинг владельца из API ответа"""
    username = item.get("username", "").replace("t.me/", "").lower()
    
    if not username or username in ignore_list:
        return None
    
    gift_info = GiftInfo(
        gift_number=item.get("giftNumber", 0),
        gift_name=item.get("giftName", ""),
        model=item.get("model", ""),
        pattern=item.get("pattern", ""),
        backdrop=item.get("backdrop", ""),
        rarity_model=item.get("rarityModel", 0.0),
        rarity_pattern=item.get("rarityPattern", 0.0),
        rarity_backdrop=item.get("rarityBackdrop", 0.0),
        gift_link=f"https://t.me/{username}?gift={item.get('giftNumber', 0)}",
        created_at=item.get("createdAt", ""),
        market=item.get("market")
    )
    
    return Owner(
        username=username,
        profile_name=item.get("owner", ""),
        link=f"https://t.me/{username}",
        user_id=item.get("userId", 0),
        gift_info=gift_info
    )


# ============================================================================
# ASYNC PARSER
# ============================================================================

class AsyncGiftParser:
    """
    Асинхронный парсер NFT подарков
    
    Args:
        api_url: URL API для запросов
        headers: HTTP заголовки (опционально)
        proxies: Список прокси в формате ["http://host:port", ...]
        proxy_file: Путь к файлу с прокси (одна строка = один прокси)
        request_delay: Задержка между запросами в секундах
        max_concurrent: Максимум одновременных запросов
        ignore_usernames: Список игнорируемых username
        max_pages: Максимум страниц для парсинга (по умолчанию 30)
    """
    
    DEFAULT_HEADERS = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://peek.tg/search",
        "Origin": "https://peek.tg",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }
    
    def __init__(
        self,
        api_url: str = "https://peek.tg/api/nft/gifts/search",
        headers: Optional[Dict] = None,
        proxies: Optional[List[str]] = None,
        proxy_file: Optional[str] = None,
        request_delay: float = 0.5,
        max_concurrent: int = 20,
        ignore_usernames: Optional[Set[str]] = None,
        max_pages: int = 20,
        verbose: bool = True
    ):
        self.api_url = api_url
        self.headers = headers or self.DEFAULT_HEADERS
        self.request_delay = request_delay
        self.max_concurrent = max_concurrent
        self.max_pages = max_pages
        self.verbose = verbose
        self.ignore_list = {u.lower() for u in (ignore_usernames or set())}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        self.proxies = []
        self.proxy_index = 0
        
        if proxies:
            self.proxies = proxies
            if self.verbose:
                print(f"⚠️ Использование прокси из параметров (deprecated)")
        
        if proxy_file:
            legacy_proxies = self._load_proxies_from_file(proxy_file)
            if legacy_proxies and self.verbose:
                print(f"⚠️ Загрузка прокси из файла (deprecated)")
            self.proxies.extend(legacy_proxies)
    
    def _load_proxies_from_file(self, filepath: str) -> List[str]:
        """Загрузить прокси из файла"""
        try:
            path = Path(filepath)
            if path.exists():
                with open(path, 'r') as f:
                    return [line.strip() for line in f if line.strip()]
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Ошибка загрузки прокси из {filepath}: {e}")
        return []
    
    async def _get_next_proxy(self) -> Optional[str]:
        """Получить следующий прокси из proxy_manager"""
        if proxy_manager:
            # Загружаем свежие прокси каждый раз без кэша
            proxies = await proxy_manager.get_active_proxies(use_cache=False)
            
            if not proxies:
                return None
            
            # Round-robin через индекс
            proxy = proxies[self.proxy_index % len(proxies)]
            self.proxy_index += 1
            
            return proxy
        
        # Fallback на старый механизм (deprecated)
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.proxy_index]
        self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
        return proxy
    
    async def _request(
        self,
        session: aiohttp.ClientSession,
        params: Dict,
        max_retries: int = 3
    ) -> Optional[Dict]:
        """Выполнить HTTP запрос с ротацией прокси"""
        for attempt in range(1, max_retries + 1):
            async with self.semaphore:
                proxy = await self._get_next_proxy()
                
                from user_agents import get_random_headers
                request_headers = get_random_headers()
                
                try:
                    print(f"🔄 Попытка {attempt}/{max_retries}")
                    print(f"🌐 URL: {self.api_url}")
                    print(f"📝 Параметры: {params}")
                    print(f"🔌 Прокси: {proxy if proxy else 'Без прокси'}")
                    print(f"🎭 User-Agent: {request_headers.get('User-Agent', 'N/A')[:80]}...")
                    
                    async with session.get(
                        self.api_url,
                        params=params,
                        headers=request_headers,  # 🔥 ИСПОЛЬЗУЕМ РАНДОМНЫЕ ЗАГОЛОВКИ
                        timeout=aiohttp.ClientTimeout(total=20),
                        proxy=proxy if proxy else None
                    ) as response:
                        print(f"📊 HTTP Статус: {response.status}")
                        print(f"📋 Headers: {dict(response.headers)}")
                        
                        raw = await response.read()
                        print(f"📦 Размер ответа: {len(raw)} байт")
                        print(f"🔍 Первые 300 байт: {raw[:300]}")
                        
                        # ОБРАБОТКА 403
                        if response.status == 403:
                            wait = min(30, 3 * (2 ** attempt))  # 6s, 12s, 24s
                            print(f"🚫 403 Forbidden — ждём {wait}s (экспоненциальная задержка)")
                            await asyncio.sleep(wait)
                            continue
                        
                        # ОБРАБОТКА 429
                        if response.status == 429:
                            wait = min(60, 10 * attempt)  # 10s, 20s, 30s
                            print(f"⏱️ Rate limit 429 — ждём {wait}s")
                            await asyncio.sleep(wait)
                            continue
                        
                        if response.status != 200:
                            print(f"⚠️ Неуспешный статус {response.status}")
                            print(f"📄 Полный ответ: {raw.decode('utf-8', errors='ignore')[:500]}")
                            if attempt == max_retries:
                                print(f"❌ Все попытки исчерпаны для прокси: {proxy}")
                            continue
                        
                        encoding = response.headers.get("content-encoding")
                        print(f"🗜️ Encoding: {encoding}")
                        
                        decompressed = _decompress(raw, encoding)
                        print(f"📦 Размер после декомпрессии: {len(decompressed)} байт")
                        print(f"🔍 JSON preview: {decompressed[:500]}")
                        
                        result = json.loads(decompressed)
                        print(f"✅ JSON успешно распарсен")
                        print(f"📊 Ключи ответа: {list(result.keys())}")
                        if 'results' in result:
                            print(f"📝 Количество results: {len(result.get('results', []))}")
                        
                        return result
                
                except json.JSONDecodeError as e:
                    print(f"❌ JSON decode error: {e}")
                    print(f"📄 Проблемный контент: {decompressed[:1000] if 'decompressed' in locals() else 'N/A'}")
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * attempt)
                
                except aiohttp.ClientError as e:
                    print(f"❌ aiohttp.ClientError: {type(e).__name__}: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * attempt)
                
                except Exception as e:
                    print(f"❌ Неожиданная ошибка: {type(e).__name__}: {e}")
                    import traceback
                    print(f"📍 Traceback: {traceback.format_exc()}")
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * attempt)
                
                finally:
                    await asyncio.sleep(self.request_delay)
        
        print(f"❌ Все {max_retries} попытки провалились, возвращаю None")
        return None
    
    async def get_max_gift_number(
        self,
        session: aiohttp.ClientSession,
        collection: str
    ) -> Optional[int]:
        """Получить максимальный номер подарка в коллекции"""
        params = {
            "name": collection,
            "page": 1,
            "sortBy": "number",
            "sortOrder": "desc",
            "limit": 1
        }
        
        if self.verbose:
            print(f"🔍 Получаю max номер для '{collection}'...")
        
        data = await self._request(session, params)
        if not data:
            return None
        
        results = data.get("results", [])
        if results:
            max_number = results[0].get("giftNumber")
            if self.verbose and max_number:
                print(f"✅ Max номер: {max_number}")
            return max_number
        
        return None
    
    def generate_random_range(self, max_number: int, range_size: int = 2000) -> tuple:
        """Генерировать случайный диапазон (start, end)"""
        if max_number <= range_size:
            return (1, max_number)
        
        max_start = max_number - range_size
        start = random.randint(1, max_start)
        end = start + range_size
        
        if self.verbose:
            print(f"🎲 Диапазон: {start}-{end} (из {max_number})")
        
        return (start, end)
    
    async def fetch_all_pages(
        self,
        session: aiohttp.ClientSession,
        collection: str,
        gift_range: Optional[tuple] = None
    ) -> List[Owner]:
        """
        Получить всех владельцев коллекции
        
        Args:
            session: aiohttp сессия
            collection: Название коллекции
            gift_range: Опциональный диапазон (start, end) для фильтрации
        """
        owners = []
        page = 1
        total_pages = None
        
        while True:
            sort_order = random.choice(["desc", "asc"])
            params = {
                "name": collection,
                "page": page,
                "sortOrder": sort_order,
                "limit": 20
            }
            
            # Добавляем фильтр по диапазону
            if gift_range:
                params["sortBy"] = "number"
                params["sortOrder"] = "desc"
                params["giftNumber"] = f"{gift_range[0]}-{gift_range[1]}"
            
            data = await self._request(session, params)
            if not data:
                break
            
            pagination = data.get("pagination", {})
            results = data.get("results", [])
            
            if total_pages is None:
                total_pages = pagination.get("totalPages", 1)
            
            for item in results:
                owner = _parse_owner(item, self.ignore_list)
                if owner:
                    owners.append(owner)
            
            if self.verbose and page % 5 == 0:
                print(f"📄 Страница {page}/{min(total_pages, self.max_pages)}: найдено {len(owners)} владельцев")
            
            page += 1
            
            # Ограничение по страницам
            if total_pages and page > min(total_pages, self.max_pages):
                break
        
        random.shuffle(owners)
        return owners
    
    async def parse_collection(self, collection: str) -> List[Owner]:
        """
        Парсинг коллекции (все страницы)
        
        Args:
            collection: Название коллекции
        
        Returns:
            Список владельцев
        """
        async with aiohttp.ClientSession(headers=self.headers) as session:
            return await self.fetch_all_pages(session, collection)
    
    async def parse_collection_random_range(
        self,
        collection: str,
        range_size: int = 2000
    ) -> List[Owner]:
        """
        Парсинг коллекции с рандомным диапазоном
        
        Args:
            collection: Название коллекции
            range_size: Размер диапазона
        
        Returns:
            Список владельцев из рандомного диапазона
        """
        async with aiohttp.ClientSession(headers=self.headers) as session:
            max_number = await self.get_max_gift_number(session, collection)
            
            gift_range = None
            if max_number:
                gift_range = self.generate_random_range(max_number, range_size)
            
            return await self.fetch_all_pages(session, collection, gift_range)
    
    async def parse_collections_batch(
        self,
        collections: List[str],
        use_random_range: bool = False,
        range_size: int = 2000
    ) -> List[Owner]:
        """
        Пакетный парсинг нескольких коллекций
        
        Args:
            collections: Список названий коллекций
            use_random_range: Использовать рандомный диапазон
            range_size: Размер диапазона
        
        Returns:
            Объединённый список владельцев
        """
        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = []
            
            for collection in collections:
                if use_random_range:
                    max_number = await self.get_max_gift_number(session, collection)
                    gift_range = self.generate_random_range(max_number, range_size) if max_number else None
                    tasks.append(self.fetch_all_pages(session, collection, gift_range))
                else:
                    tasks.append(self.fetch_all_pages(session, collection))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_owners = []
            for result in results:
                if isinstance(result, list):
                    all_owners.extend(result)
            
            return all_owners


# ============================================================================
# EXAMPLE
# ============================================================================

async def main():
    """Пример использования"""
    
    # Инициализация парсера
    parser = AsyncGiftParser(
        proxies=[],  # Добавьте свои прокси или укажите proxy_file
        proxy_file="proxies.txt",  # Или загрузите из файла
        request_delay=0.2,
        max_concurrent=20,
        max_pages=20,
        ignore_usernames={"giftstoportals", "giftrelayer"},
        verbose=True
    )
    
    print("=" * 80)
    print("🎁 ASYNC GIFT PARSER - DEMO")
    print("=" * 80)
    
    # Пример 1: Обычный парсинг
    print("\n1️⃣ Обычный парсинг коллекции:")
    owners = await parser.parse_collection("AstralShard")
    print(f"✅ Найдено {len(owners)} владельцев")
    
    # Пример 2: Парсинг с рандомным диапазоном
    print("\n2️⃣ Парсинг с рандомным диапазоном:")
    owners = await parser.parse_collection_random_range("AstralShard", range_size=2000)
    print(f"✅ Найдено {len(owners)} владельцев")
    
    # Пример 3: Пакетный парсинг
    print("\n3️⃣ Пакетный парсинг:")
    collections = ["AstralShard", "DiamondRing", "EternalRose"]
    owners = await parser.parse_collections_batch(collections, use_random_range=True)
    print(f"✅ Найдено {len(owners)} владельцев")
    
    # Вывод примера
    if owners:
        print(f"\n📋 Пример владельца:")
        print(json.dumps(owners[0].to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":

    asyncio.run(main())

