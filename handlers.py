"""
Обработчики команд и сообщений бота
"""
import asyncio
import random
import time
import uuid
import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MESSAGES, BUTTONS, USER_RATE_LIMIT
from database import db
from async_queue import task_queue, TaskStatus
from gifts_constants import ALL_COLLECTIONS
from parser_wrapper import parse_random_collection, parse_female_accounts
import redis_cache

# Rate limiting (простая in-memory реализация)
from collections import defaultdict, deque

user_requests = defaultdict(deque)  # user_id -> deque of timestamps

router = Router()


def escape_markdown_v2(text: str) -> str:
    """Экранировать специальные символы MarkdownV2"""
    escape_chars = r'_*[]()~`>#+=|{}.!-'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)


def check_rate_limit(user_id: int) -> bool:
    """Проверить rate limit для пользователя"""
    now = time.time()
    minute_ago = now - 60
    
    # Удаляем старые запросы
    while user_requests[user_id] and user_requests[user_id][0] < minute_ago:
        user_requests[user_id].popleft()
    
    # Проверяем лимит
    if len(user_requests[user_id]) >= USER_RATE_LIMIT:
        return False
    
    # Добавляем текущий запрос
    user_requests[user_id].append(now)
    return True


def get_main_keyboard():
    """Главная клавиатура"""
    builder = InlineKeyboardBuilder()
    builder.button(text="Парсинг по фильтрам", callback_data="filter_parsing")
    builder.button(text=BUTTONS["random_parsing"], callback_data="random_parsing")
    builder.button(text=BUTTONS["female_accounts"], callback_data="female_accounts")
    builder.button(text=BUTTONS["help"], callback_data="help")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def get_collections_keyboard(page: int = 0, per_page: int = 10):
    """Клавиатура с коллекциями (пагинация)"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    collections_page = ALL_COLLECTIONS[start_idx:end_idx]
    
    for collection in collections_page:
        builder.button(
            text=collection,
            callback_data=f"collection:{collection}"
        )
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(("⬅️ Назад", f"page:{page-1}"))
    if end_idx < len(ALL_COLLECTIONS):
        nav_buttons.append(("➡️ Далее", f"page:{page+1}"))
    
    for text, callback in nav_buttons:
        builder.button(text=text, callback_data=callback)
    
    # Кнопка возврата
    builder.button(text=BUTTONS["back"], callback_data="back_to_main")
    
    builder.adjust(2)
    return builder.as_markup()


def format_owners_page(owners: list, page: int = 0, per_page: int = 10) -> tuple:
    """
    Форматировать страницу владельцев
    
    Returns:
        (formatted_text, total_pages)
    """
    if not owners:
        return MESSAGES["no_results"], 0
    
    # Дедупликация по username
    seen_usernames = set()
    unique_owners = []
    for owner in owners:
        username = owner.get("username", "").lower()
        if username and username not in seen_usernames:
            seen_usernames.add(username)
            unique_owners.append(owner)
    
    owners = unique_owners
    
    total_pages = (len(owners) + per_page - 1) // per_page
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(owners))
    page_owners = owners[start_idx:end_idx]
    
    result_lines = []
    for i, owner in enumerate(page_owners, start_idx + 1):
        username = owner.get("username", "")
        gift_info = owner.get("gift", {})
        gift_name = gift_info.get("gift_name", "")
        gift_number = gift_info.get("gift_number", 0)
        
        # Формат ссылки: https://t.me/nft/CollectionName-123
        gift_link = f"https://t.me/nft/{gift_name}-{gift_number}"
        
        # Экранируем username для MarkdownV2
        escaped_username = escape_markdown_v2(username)
        
        # Формат: LINK | @username
        result_lines.append(f"{i}\\. [LINK]({gift_link}) \\| @{escaped_username}")
    
    result_text = "\n".join(result_lines)
    result_text += f"\n\n📄 Страница {page + 1}/{total_pages} \\| Всего: {len(owners)}"
    
    return result_text, total_pages


def format_female_usernames_page(owners: list, female_usernames: list, page: int = 0, per_page: int = 10) -> tuple:
    """
    Форматировать страницу женских username с подарками
    
    Args:
        owners: Полный список владельцев с информацией о подарках
        female_usernames: Список отфильтрованных женских username
        page: Номер страницы
        per_page: Количество на странице
    
    Returns:
        (formatted_text, total_pages)
    """
    if not female_usernames:
        return MESSAGES["no_results"], 0
    
    # Дедупликация женских username
    seen_usernames = set()
    unique_female_usernames = []
    for username in female_usernames:
        username_lower = username.lower()
        if username_lower not in seen_usernames:
            seen_usernames.add(username_lower)
            unique_female_usernames.append(username)
    
    female_usernames = unique_female_usernames
    
    total_pages = (len(female_usernames) + per_page - 1) // per_page
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(female_usernames))
    page_usernames = female_usernames[start_idx:end_idx]
    
    # Создаём словарь username -> owner для быстрого поиска
    username_to_owner = {owner.get("username", "").lower(): owner for owner in owners}
    
    result_lines = []
    for i, username in enumerate(page_usernames, start_idx + 1):
        # Находим данные владельца по username
        owner = username_to_owner.get(username.lower())
        
        if owner:
            gift_info = owner.get("gift", {})
            gift_name = gift_info.get("gift_name", "")
            gift_number = gift_info.get("gift_number", 0)
            
            # Формат ссылки: https://t.me/nft/CollectionName-123
            gift_link = f"https://t.me/nft/{gift_name}-{gift_number}"
            
            # Экранируем username для MarkdownV2
            escaped_username = escape_markdown_v2(username)
            
            # Формат: LINK | @username
            result_lines.append(f"{i}\\. [LINK]({gift_link}) \\| @{escaped_username}")
        else:
            # Если по какой-то причине owner не найден, просто показываем username
            escaped_username = escape_markdown_v2(username)
            result_lines.append(f"{i}\\. @{escaped_username}")
    
    result_text = "\n".join(result_lines)
    result_text += f"\n\n📄 Страница {page + 1}/{total_pages} \\| Всего: {len(female_usernames)}"
    
    return result_text, total_pages


def get_pagination_keyboard(callback_prefix: str, page: int, total_pages: int, task_id: str = None):
    """Клавиатура для пагинации результатов"""
    builder = InlineKeyboardBuilder()
    
    buttons = []
    
    # Кнопки навигации
    if page > 0:
        callback_data = f"{callback_prefix}:{page-1}"
        if task_id:
            callback_data += f":{task_id}"
        buttons.append(("⬅️ Назад", callback_data))
    
    if page < total_pages - 1:
        callback_data = f"{callback_prefix}:{page+1}"
        if task_id:
            callback_data += f":{task_id}"
        buttons.append(("➡️ Далее", callback_data))
    
    for text, callback in buttons:
        builder.button(text=text, callback_data=callback)
    
    # Кнопка обновить (повторить парсинг)
    refresh_callback = f"refresh_{callback_prefix.replace('_page', '')}"
    if task_id:
        refresh_callback += f":{task_id}"
    builder.button(text="🔄 Обновить", callback_data=refresh_callback)
    
    # Кнопка в главное меню
    builder.button(text=BUTTONS["back"], callback_data="back_to_main")
    
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def get_task_status_keyboard(task_id: str):
    """Клавиатура для проверки статуса задачи"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Проверить статус", callback_data=f"check_status:{task_id}")
    builder.button(text=BUTTONS["back"], callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


# ============================================================================
# BACKGROUND TASK PROCESSING
# ============================================================================

async def send_random_parsing_result(bot: Bot, user_id: int, task_id: str, collection: str):
    """
    Фоновая отправка результатов рандомного парсинга
    
    Args:
        bot: Bot instance
        user_id: ID пользователя
        task_id: ID задачи
        collection: Название коллекции
    """
    try:
        # Ждём завершения задачи
        task = await task_queue.wait_for_task(task_id, timeout=180)
        
        if not task or task.status == TaskStatus.FAILED:
            error_msg = task.error if task else "Timeout"
            await bot.send_message(
                user_id,
                f"❌ Парсинг коллекции **{collection}** завершился с ошибкой:\n{error_msg}",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
            return
        
        # Получаем результат
        result = task.result
        owners = result["owners"]
        duration = task.get_duration()
        
        # Сохраняем запрос в БД
        # Убеждаемся что пользователь существует в БД
        try:
            user = await bot.get_chat(user_id)
            await db.add_user(
                user_id=user_id,
                username=user.username,
                first_name=user.first_name or "Unknown",
                last_name=user.last_name
            )
        except:
            pass  # Пользователь уже есть или ошибка
        
        await db.add_request(
            user_id=user_id,
            request_type="random",
            collection=collection,
            result_count=len(owners)
        )
        
        # Сохраняем результаты в кэш для пагинации
        await redis_cache.redis_cache.set(task_id, {
            "type": "random",
            "collection": collection,
            "owners": owners,
            "duration": duration
        })
        
        # Форматируем первую страницу
        formatted_results, total_pages = format_owners_page(owners, page=0, per_page=10)
        
        # Экранируем текст сообщения
        escaped_collection = escape_markdown_v2(collection)
        escaped_duration = escape_markdown_v2(f"{duration:.1f}")
        message_text = (
            f"✅ *Парсинг завершён\\!*\n\n"
            f"📊 Коллекция: {escaped_collection}\n"
            f"👥 Найдено владельцев: {len(owners)}\n"
            f"⏱ Время: {escaped_duration}с\n\n"
            f"{formatted_results}"
        )
        
        await bot.send_message(
            user_id,
            message_text,
            reply_markup=get_pagination_keyboard("random_page", 0, total_pages, task_id),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        print(f"❌ Ошибка отправки результата парсинга: {e}")
        try:
            await bot.send_message(
                user_id,
                f"❌ Ошибка при обработке результата: {str(e)}",
                reply_markup=get_main_keyboard()
            )
        except:
            pass


async def send_female_parsing_result(bot: Bot, user_id: int, task_id: str, collection: str):
    """
    Фоновая отправка результатов парсинга женских аккаунтов
    
    Args:
        bot: Bot instance
        user_id: ID пользователя
        task_id: ID задачи
        collection: Название коллекции
    """
    try:
        # Ждём завершения задачи
        task = await task_queue.wait_for_task(task_id, timeout=300)
        
        if not task or task.status == TaskStatus.FAILED:
            error_msg = task.error if task else "Timeout"
            await bot.send_message(
                user_id,
                f"❌ Поиск женских аккаунтов в коллекции **{collection}** завершился с ошибкой:\n{error_msg}",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
            return
        
        # Получаем результат
        result = task.result
        owners = result["owners"]
        female_usernames = result["female_usernames"]
        duration = task.get_duration()
        
        # Сохраняем запрос в БД
        # Убеждаемся что пользователь существует в БД
        try:
            user = await bot.get_chat(user_id)
            await db.add_user(
                user_id=user_id,
                username=user.username,
                first_name=user.first_name or "Unknown",
                last_name=user.last_name
            )
        except:
            pass  # Пользователь уже есть или ошибка
        
        await db.add_request(
            user_id=user_id,
            request_type="female",
            collection=collection,
            result_count=len(female_usernames)
        )
        
        # Сохраняем результаты в кэш для пагинации
        await redis_cache.redis_cache.set(task_id, {
            "type": "female",
            "collection": collection,
            "owners": owners,
            "female_usernames": female_usernames,
            "duration": duration
        })
        
        # Форматируем первую страницу
        formatted_results, total_pages = format_female_usernames_page(
            owners=owners,
            female_usernames=female_usernames,
            page=0,
            per_page=10
        )
        
        # Экранируем текст сообщения
        escaped_collection = escape_markdown_v2(collection)
        escaped_duration = escape_markdown_v2(f"{duration:.1f}")
        message_text = (
            f"✅ *Поиск завершён\\!*\n\n"
            f"📊 Коллекция: {escaped_collection}\n"
            f"👩 Найдено аккаунтов: {len(female_usernames)}\n"
            f"⏱ Время: {escaped_duration}с\n\n"
            f"{formatted_results}"
        )
        
        await bot.send_message(
            user_id,
            message_text,
            reply_markup=get_pagination_keyboard("female_page", 0, total_pages, task_id),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        print(f"❌ Ошибка отправки результата female парсинга: {e}")
        try:
            await bot.send_message(
                user_id,
                f"❌ Ошибка при обработке результата: {str(e)}",
                reply_markup=get_main_keyboard()
            )
        except:
            pass


# ============================================================================
# COMMAND HANDLERS
# ============================================================================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("test")
    
@router.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    """Показать помощь"""
    await callback.message.edit_text(
        MESSAGES["help"].format(rate_limit=USER_RATE_LIMIT),
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def callback_back(callback: CallbackQuery):
    """Вернуться в главное меню"""
    await callback.message.edit_text(
        MESSAGES["start"],
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# ============================================================================
# RANDOM PARSING
# ============================================================================

@router.callback_query(F.data == "random_parsing")
async def callback_random_parsing(callback: CallbackQuery):
    """Рандомный парсинг - асинхронная обработка"""
    user_id = callback.from_user.id
    
    # Проверка rate limit
    if not check_rate_limit(user_id):
        await callback.answer(MESSAGES["rate_limit"], show_alert=True)
        return
    
    # Выбираем случайную коллекцию
    collection = random.choice(ALL_COLLECTIONS)
    
    # Создаём уникальный ID задачи
    task_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
    
    # Добавляем задачу в очередь
    added = await task_queue.add_task(
        task_id=task_id,
        user_id=user_id,
        task_type="random",
        collection=collection,
        callback=parse_random_collection
    )
    
    if not added:
        await callback.message.edit_text(
            MESSAGES["queue_full"],
            reply_markup=get_main_keyboard()
        )
        await callback.answer()
        return
    
    # Сразу отвечаем пользователю (не ждём!)
    queue_size = task_queue.get_queue_size()
    await callback.message.edit_text(
        f"⏳ **Задача добавлена в очередь**\n\n"
        f"📊 Коллекция: {collection}\n"
        f"🔢 Задача: \\#{task_id[:8]}\n"
        f"📋 В очереди: {queue_size} задач\n\n"
        f"Вы получите уведомление когда парсинг завершится\\.\n"
        f"Или можете проверить статус вручную\\.",
        reply_markup=get_task_status_keyboard(task_id),
        parse_mode="MarkdownV2"
    )
    await callback.answer("✅ Задача добавлена")
    
    # Запускаем фоновую обработку
    asyncio.create_task(
        send_random_parsing_result(callback.bot, user_id, task_id, collection)
    )


# ============================================================================
# FEMALE ACCOUNTS PARSING
# ============================================================================

@router.callback_query(F.data == "female_accounts")
async def callback_female_accounts(callback: CallbackQuery):
    """Выбор коллекции для парсинга женских аккаунтов"""
    await callback.message.edit_text(
        MESSAGES["select_collection"],
        reply_markup=get_collections_keyboard(page=0)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("page:"))
async def callback_page(callback: CallbackQuery):
    """Навигация по страницам коллекций"""
    page = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        MESSAGES["select_collection"],
        reply_markup=get_collections_keyboard(page=page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("collection:"))
async def callback_collection(callback: CallbackQuery):
    """Выбор коллекции для парсинга женских аккаунтов - асинхронная обработка"""
    user_id = callback.from_user.id
    collection = callback.data.split(":", 1)[1]
    
    # Проверка rate limit
    if not check_rate_limit(user_id):
        await callback.answer(MESSAGES["rate_limit"], show_alert=True)
        return
    
    # Создаём уникальный ID задачи
    task_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
    
    # Добавляем задачу в очередь
    added = await task_queue.add_task(
        task_id=task_id,
        user_id=user_id,
        task_type="female",
        collection=collection,
        callback=parse_female_accounts
    )
    
    if not added:
        await callback.message.edit_text(
            MESSAGES["queue_full"],
            reply_markup=get_main_keyboard()
        )
        await callback.answer()
        return
    
    # Сразу отвечаем пользователю (не ждём!)
    queue_size = task_queue.get_queue_size()
    await callback.message.edit_text(
        f"⏳ **Задача добавлена в очередь**\n\n"
        f"📊 Коллекция: {collection}\n"
        f"🔍 Тип: Поиск женских аккаунтов\n"
        f"🔢 Задача: \\#{task_id[:8]}\n"
        f"📋 В очереди: {queue_size} задач\n\n"
        f"Вы получите уведомление когда парсинг завершится\\.\n"
        f"Или можете проверить статус вручную\\.",
        reply_markup=get_task_status_keyboard(task_id),
        parse_mode="MarkdownV2"
    )
    await callback.answer("✅ Задача добавлена")
    
    # Запускаем фоновую обработку
    asyncio.create_task(
        send_female_parsing_result(callback.bot, user_id, task_id, collection)
    )


# ============================================================================
# TASK STATUS CHECK
# ============================================================================

@router.callback_query(F.data.startswith("check_status:"))
async def callback_check_status(callback: CallbackQuery):
    """Проверить статус задачи"""
    task_id = callback.data.split(":", 1)[1]
    task = task_queue.get_task(task_id)
    
    if not task:
        await callback.answer("❌ Задача не найдена или уже завершена", show_alert=True)
        return
    
    if task.status == TaskStatus.PENDING:
        queue_size = task_queue.get_queue_size()
        await callback.answer(f"⏳ Задача в очереди (всего задач: {queue_size})", show_alert=True)
        
    elif task.status == TaskStatus.PROCESSING:
        await callback.answer("⚙️ Задача обрабатывается...", show_alert=True)
        
    elif task.status == TaskStatus.COMPLETED:
        await callback.answer("✅ Задача завершена! Результат должен быть выше.", show_alert=True)
        
    elif task.status == TaskStatus.FAILED:
        error_msg = task.error or "Неизвестная ошибка"
        await callback.answer(f"❌ Ошибка: {error_msg}", show_alert=True)


# ============================================================================
# PAGINATION HANDLERS
# ============================================================================

@router.callback_query(F.data.startswith("random_page:"))
async def callback_random_page(callback: CallbackQuery):
    """Навигация по страницам рандомного парсинга"""
    parts = callback.data.split(":")
    page = int(parts[1])
    task_id = parts[2] if len(parts) > 2 else None
    
    if not task_id:
        await callback.answer("❌ Неверные данные", show_alert=True)
        return
    
    cached = await redis_cache.redis_cache.get(task_id)
    if not cached:
        await callback.answer("❌ Результаты устарели. Запустите парсинг заново.", show_alert=True)
        return
    
    owners = cached["owners"]
    collection = cached["collection"]
    duration = cached["duration"]
    
    # Форматируем страницу
    formatted_results, total_pages = format_owners_page(owners, page=page, per_page=10)
    
    # Экранируем текст сообщения
    escaped_collection = escape_markdown_v2(collection)
    escaped_duration = escape_markdown_v2(f"{duration:.1f}")
    message_text = (
        f"✅ *Парсинг завершён\\!*\n\n"
        f"📊 Коллекция: {escaped_collection}\n"
        f"👥 Найдено владельцев: {len(owners)}\n"
        f"⏱ Время: {escaped_duration}с\n\n"
        f"{formatted_results}"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_pagination_keyboard("random_page", page, total_pages, task_id),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data.startswith("female_page:"))
async def callback_female_page(callback: CallbackQuery):
    """Навигация по страницам женских аккаунтов"""
    parts = callback.data.split(":")
    page = int(parts[1])
    task_id = parts[2] if len(parts) > 2 else None
    
    if not task_id:
        await callback.answer("❌ Неверные данные", show_alert=True)
        return
    
    cached = await redis_cache.redis_cache.get(task_id)
    if not cached:
        await callback.answer("❌ Результаты устарели. Запустите парсинг заново.", show_alert=True)
        return
    
    female_usernames = cached["female_usernames"]
    collection = cached["collection"]
    duration = cached["duration"]
    owners = cached["owners"]
    
    # Форматируем страницу
    formatted_results, total_pages = format_female_usernames_page(
        owners=owners,
        female_usernames=female_usernames,
        page=page,
        per_page=10
    )
    
    # Экранируем текст сообщения
    escaped_collection = escape_markdown_v2(collection)
    escaped_duration = escape_markdown_v2(f"{duration:.1f}")
    message_text = (
        f"✅ *Поиск завершён\\!*\n\n"
        f"📊 Коллекция: {escaped_collection}\n"
        f"👩 Найдено аккаунтов: {len(female_usernames)}\n"
        f"⏱ Время: {escaped_duration}с\n\n"
        f"{formatted_results}"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_pagination_keyboard("female_page", page, total_pages, task_id),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )
    await callback.answer()


# ============================================================================
# REFRESH HANDLERS
# ============================================================================

@router.callback_query(F.data.startswith("refresh_random"))
async def callback_refresh_random(callback: CallbackQuery):
    """Обновить рандомный парсинг - асинхронная обработка"""
    user_id = callback.from_user.id
    
    # Проверка rate limit
    if not check_rate_limit(user_id):
        await callback.answer(MESSAGES["rate_limit"], show_alert=True)
        return
    
    # Получаем старый task_id из callback_data
    parts = callback.data.split(":")
    old_task_id = parts[1] if len(parts) > 1 else None
    
    # Пытаемся получить коллекцию из кэша
    collection = None
    if old_task_id:
        cached = await redis_cache.redis_cache.get(old_task_id)
        if cached:
            collection = cached.get("collection")
    
    # Если не нашли в кэше, выбираем случайную
    if not collection:
        collection = random.choice(ALL_COLLECTIONS)
    
    # Создаём новый уникальный ID задачи
    task_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
    
    # Добавляем задачу в очередь
    added = await task_queue.add_task(
        task_id=task_id,
        user_id=user_id,
        task_type="random",
        collection=collection,
        callback=parse_random_collection
    )
    
    if not added:
        await callback.message.edit_text(
            MESSAGES["queue_full"],
            reply_markup=get_main_keyboard()
        )
        await callback.answer()
        return
    
    # Сразу отвечаем пользователю (не ждём!)
    queue_size = task_queue.get_queue_size()
    await callback.message.edit_text(
        f"🔄 **Обновление: задача добавлена в очередь**\n\n"
        f"📊 Коллекция: {collection}\n"
        f"🔢 Задача: \\#{task_id[:8]}\n"
        f"📋 В очереди: {queue_size} задач\n\n"
        f"Вы получите уведомление когда парсинг завершится\\.",
        reply_markup=get_task_status_keyboard(task_id),
        parse_mode="MarkdownV2"
    )
    await callback.answer("🔄 Обновление запущено")
    
    # Запускаем фоновую обработку
    asyncio.create_task(
        send_random_parsing_result(callback.bot, user_id, task_id, collection)
    )


@router.callback_query(F.data.startswith("refresh_female"))
async def callback_refresh_female(callback: CallbackQuery):
    """Обновить парсинг женских аккаунтов - асинхронная обработка"""
    user_id = callback.from_user.id
    
    # Проверка rate limit
    if not check_rate_limit(user_id):
        await callback.answer(MESSAGES["rate_limit"], show_alert=True)
        return
    
    # Получаем старый task_id из callback_data
    parts = callback.data.split(":")
    old_task_id = parts[1] if len(parts) > 1 else None
    
    # Получаем коллекцию из кэша
    collection = None
    if old_task_id:
        cached = await redis_cache.redis_cache.get(old_task_id)
        if cached:
            collection = cached.get("collection")
    
    if not collection:
        await callback.answer("❌ Данные устарели. Выберите коллекцию заново.", show_alert=True)
        return
    
    # Создаём новый уникальный ID задачи
    task_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
    
    # Добавляем задачу в очередь
    added = await task_queue.add_task(
        task_id=task_id,
        user_id=user_id,
        task_type="female",
        collection=collection,
        callback=parse_female_accounts
    )
    
    if not added:
        await callback.message.edit_text(
            MESSAGES["queue_full"],
            reply_markup=get_main_keyboard()
        )
        await callback.answer()
        return
    
    # Сразу отвечаем пользователю (не ждём!)
    queue_size = task_queue.get_queue_size()
    await callback.message.edit_text(
        f"🔄 **Обновление: задача добавлена в очередь**\n\n"
        f"📊 Коллекция: {collection}\n"
        f"🔍 Тип: Поиск женских аккаунтов\n"
        f"🔢 Задача: \\#{task_id[:8]}\n"
        f"📋 В очереди: {queue_size} задач\n\n"
        f"Вы получите уведомление когда парсинг завершится\\.",
        reply_markup=get_task_status_keyboard(task_id),
        parse_mode="MarkdownV2"
    )
    await callback.answer("🔄 Обновление запущено")
    
    # Запускаем фоновую обработку
    asyncio.create_task(
        send_female_parsing_result(callback.bot, user_id, task_id, collection)
    )
