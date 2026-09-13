#!/usr/bin/env python3
"""
Главный файл бота
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, PARSER_PROXIES, ADMIN_IDS, REDIS_URL
from database import db
from async_queue import task_queue
from webhook import start_webhook
from proxy_manager import init_proxy_manager, check_proxies_task

import redis_cache as redis_cache_module
from redis_cache import RedisCache

# Импортируем роутеры
import handlers
import admin
import filter_handlers

async def main():
    """Главная функция"""
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    print("=" * 80)
    print("🤖 TELEGRAM NFT PARSER BOT")
    print("=" * 80)
    
    # Инициализация базы данных
    print("\n📦 Инициализация базы данных...")
    await db.init()

    # Инициализация Redis
    print("\n📦 Инициализация Redis...")
    redis_cache_module.redis_cache = RedisCache(REDIS_URL)
    await redis_cache_module.redis_cache.init()
    
    # ВАЖНО: Инициализация proxy manager СРАЗУ после БД
    print("\n📡 Инициализация proxy manager...")
    await init_proxy_manager(db)
    
    # Получаем proxy_manager ПОСЛЕ инициализации
    from proxy_manager import proxy_manager
    
    # Миграция прокси из config.py в БД (одноразово)
    if PARSER_PROXIES:
        print("\nМиграция прокси из конфига в БД...")
        admin_id = list(ADMIN_IDS)[0] if ADMIN_IDS else 0
        for proxy in PARSER_PROXIES:
            try:
                result = await proxy_manager.add_proxy(
                    proxy, 
                    admin_id=admin_id,
                    check_before_add=False
                )
                if result['success']:
                    print(f"✅ Мигрирован прокси")
            except Exception as e:
                print(f"⚠️ Ошибка миграции прокси: {e}")
    
    # Запуск очереди задач
    print("\n⚙️ Запуск очереди задач...")
    await task_queue.start()
    
    # Создание бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    dp = Dispatcher()
    
    # Регистрация роутеров
    dp.include_router(handlers.router)
    dp.include_router(admin.router)
    dp.include_router(filter_handlers.router)
    
    print("\n✅ Роутеры зарегистрированы")
    
    # Запуск фоновой задачи проверки прокси
    print("\n🔍 Запуск фоновой проверки прокси (каждые 6 часов)...")
    proxy_check_task_instance = asyncio.create_task(check_proxies_task(bot))
    
    try:
        # Запуск webhook сервера
        print("\n🚀 Запуск webhook сервера...")
        await start_webhook(dp, bot)
        
    except KeyboardInterrupt:
        print("\n⏸ Получен сигнал остановки")
    
    finally:
        # Остановка задачи проверки прокси
        print("\n🛑 Остановка задачи проверки прокси...")
        proxy_check_task_instance.cancel()
        try:
            await proxy_check_task_instance
        except asyncio.CancelledError:
            pass
        
        # Остановка очереди
        print("\n🛑 Остановка очереди задач...")
        await task_queue.stop()
        
        # Закрытие Redis
        print("🛑 Закрытие Redis...")
        await redis_cache_module.redis_cache.close()
        
        print("🛑 Закрытие базы данных...")
        await db.close()
        
        # Закрытие сессии бота
        print("🛑 Закрытие бота...")
        await bot.session.close()
        
        print("\n✅ Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Выход")
