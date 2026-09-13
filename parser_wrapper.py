"""
Обёртка над парсером и GPT фильтром для интеграции с ботом
"""
from typing import List, Dict, Any
import sys
import os

# Импортируем парсер и GPT фильтр
from async_parser import AsyncGiftParser
from gpt_filter import GPTGenderFilter

from config import (
    IGNORE_USERNAMES,
    PARSER_API_URL,
    PARSER_REQUEST_DELAY,
    PARSER_MAX_CONCURRENT,
    PARSER_MAX_PAGES,
    PARSER_RANGE_SIZE,
    PARSER_PROXIES,
    PARSER_PROXY_FILE,
    OPENAI_API_KEY,
    GPT_MODEL,
    GPT_TEMPERATURE,
    GPT_MAX_TOKENS,
    GPT_BATCH_SIZE,
    DEFAULT_FEMALE_COUNT,
)


# Инициализация парсера
parser = AsyncGiftParser(
    api_url=PARSER_API_URL,
    proxies=PARSER_PROXIES,
    proxy_file=PARSER_PROXY_FILE,
    request_delay=PARSER_REQUEST_DELAY,
    max_concurrent=PARSER_MAX_CONCURRENT,
    max_pages=PARSER_MAX_PAGES,
    ignore_usernames=IGNORE_USERNAMES,
    verbose=False  # Отключаем verbose для бота
)

# Инициализация GPT фильтра
gpt_filter = GPTGenderFilter(
    api_key=OPENAI_API_KEY,
    model=GPT_MODEL,
    temperature=GPT_TEMPERATURE,
    max_tokens=GPT_MAX_TOKENS,
    batch_size=GPT_BATCH_SIZE,
    verbose=False  # Отключаем verbose для бота
)


async def parse_with_filters(
    collections: List[str],
    models: List[str],
    backdrops: List[str],
    user_id: int
) -> Dict[str, Any]:
    """
    Парсинг с фильтрами по коллекциям, моделям и фонам
    
    Args:
        collections: Список коллекций
        models: Список моделей (опционально)
        backdrops: Список фонов (опционально)
        user_id: ID пользователя
    
    Returns:
        Dict с результатами парсинга
    """
    print(f"🔍 Парсинг с фильтрами для пользователя {user_id}")
    print(f"📦 Коллекции: {len(collections)}")
    print(f"🎨 Модели: {len(models) if models else 0}")
    print(f"🖼 Фоны: {len(backdrops) if backdrops else 0}")
    
    # Парсим все выбранные коллекции
    all_owners = []
    for collection in collections:
        owners = await parser.parse_collection_random_range(
            collection=collection,
            range_size=PARSER_RANGE_SIZE
        )
        all_owners.extend(owners)
    
    print(f"📊 Всего найдено: {len(all_owners)} владельцев")
    
    # Фильтруем по моделям и фонам
    filtered_owners = []
    for owner in all_owners:
        gift = owner.gift_info
        
        # Фильтр по моделям
        if models and gift.model not in models:
            continue
        
        # Фильтр по фонам
        if backdrops and gift.backdrop not in backdrops:
            continue
        
        filtered_owners.append(owner)
    
    print(f"✅ После фильтрации: {len(filtered_owners)} владельцев")
    
    # Конвертируем в dict
    owners_dict = [owner.to_dict() for owner in filtered_owners]
    
    return {
        "collections": collections,
        "models": models,
        "backdrops": backdrops,
        "owners": owners_dict,
        "total": len(owners_dict)
    }

async def parse_random_collection(collection: str, user_id: int) -> Dict[str, Any]:
    """
    Парсинг случайной коллекции с рандомным диапазоном
    
    Args:
        collection: Название коллекции
        user_id: ID пользователя (для логирования)
    
    Returns:
        Dict с результатами парсинга
    """
    print(f"🎲 Парсинг коллекции {collection} для пользователя {user_id}")
    
    # Парсим коллекцию с рандомным диапазоном
    owners = await parser.parse_collection_random_range(
        collection=collection,
        range_size=PARSER_RANGE_SIZE
    )
    
    # Конвертируем в dict
    owners_dict = [owner.to_dict() for owner in owners]
    
    print(f"✅ Найдено {len(owners_dict)} владельцев в коллекции {collection}")
    
    return {
        "collection": collection,
        "owners": owners_dict,
        "total": len(owners_dict)
    }


async def parse_female_accounts(collection: str, user_id: int) -> Dict[str, Any]:
    """
    Парсинг коллекции и фильтрация женских аккаунтов через GPT
    
    Args:
        collection: Название коллекции
        user_id: ID пользователя (для логирования)
    
    Returns:
        Dict с результатами парсинга и фильтрации
    """
    print(f"👩 Парсинг женских аккаунтов из {collection} для пользователя {user_id}")
    
    # 1. Парсим коллекцию
    owners = await parser.parse_collection_random_range(
        collection=collection,
        range_size=PARSER_RANGE_SIZE
    )
    
    print(f"📊 Найдено {len(owners)} владельцев")
    
    # 2. Извлекаем уникальные username
    usernames = []
    username_to_owner = {}  # Для связи username с данными владельца
    
    seen_usernames = set()
    for owner in owners:
        username = owner.username.lower()
        if username not in seen_usernames:
            usernames.append(owner.username)
            username_to_owner[username] = owner
            seen_usernames.add(username)
    
    print(f"🔍 Уникальных username: {len(usernames)}")
    
    # 3. Проверяем наличие OpenAI API ключа
    if not OPENAI_API_KEY or OPENAI_API_KEY == "":
        print("⚠️ OpenAI API ключ не установлен, пропускаем фильтрацию")
        return {
            "collection": collection,
            "owners": [owner.to_dict() for owner in owners],
            "female_usernames": [],
            "total": len(owners)
        }
    
    # 4. Фильтруем через GPT
    female_usernames = await gpt_filter.filter_female(
        usernames=usernames,
        count=DEFAULT_FEMALE_COUNT
    )
    
    print(f"✅ Найдено {len(female_usernames)} женских аккаунтов")
    
    return {
        "collection": collection,
        "owners": [owner.to_dict() for owner in owners],
        "female_usernames": female_usernames,
        "total": len(owners)
    }


async def test_parser():
    """Тест парсера"""
    print("=" * 80)
    print("🧪 Тест парсера")
    print("=" * 80)
    
    # Тест 1: Рандомный парсинг
    print("\n1️⃣ Тест рандомного парсинга")
    result = await parse_random_collection("AstralShard", user_id=123456)
    print(f"Результат: {result['total']} владельцев")
    
    # Тест 2: Парсинг женских аккаунтов (если есть API ключ)
    if OPENAI_API_KEY:
        print("\n2️⃣ Тест парсинга женских аккаунтов")
        result = await parse_female_accounts("AstralShard", user_id=123456)
        print(f"Результат: {len(result['female_usernames'])} женских аккаунтов из {result['total']}")
    else:
        print("\n⚠️ OpenAI API ключ не установлен, тест пропущен")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_parser())