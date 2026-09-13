"""
Webhook сервер для бота
"""
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import BOT_TOKEN, WEBHOOK_PATH, WEBHOOK_URL, WEBAPP_HOST, WEBAPP_PORT


async def on_startup(bot: Bot):
    """При запуске бота"""
    # Устанавливаем webhook
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True
    )
    print(f"✅ Webhook установлен: {WEBHOOK_URL}")


async def on_shutdown(bot: Bot):
    """При остановке бота"""
    # Удаляем webhook
    await bot.delete_webhook()
    print("✅ Webhook удалён")


def setup_webhook(dp: Dispatcher, bot: Bot) -> web.Application:
    """
    Настройка webhook сервера
    
    Args:
        dp: Dispatcher
        bot: Bot
    
    Returns:
        aiohttp Application
    """
    # Регистрируем startup/shutdown хуки
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Создаём aiohttp приложение
    app = web.Application()
    
    # Создаём webhook handler
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)
    
    # Настраиваем приложение
    setup_application(app, dp, bot=bot)
    
    return app


async def start_webhook(dp: Dispatcher, bot: Bot):
    """
    Запуск webhook сервера
    
    Args:
        dp: Dispatcher
        bot: Bot
    """
    # Настраиваем приложение
    app = setup_webhook(dp, bot)
    
    # Запускаем веб-сервер
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    
    print(f"🚀 Webhook сервер запущен на {WEBAPP_HOST}:{WEBAPP_PORT}")
    print(f"📡 Webhook путь: {WEBHOOK_PATH}")
    
    # Держим сервер запущенным
    import asyncio
    await asyncio.Event().wait()