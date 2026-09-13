"""
Обработчики для парсинга по фильтрам
"""
import asyncio
import uuid
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MESSAGES, BUTTONS
from database import db
from async_queue import task_queue, TaskStatus
from gifts_constants import COLLECTION_MODELS, ALL_BACKDROPS, ALL_COLLECTIONS
from parser_wrapper import parse_with_filters
import redis_cache
from handlers import (
    check_rate_limit,
    escape_markdown_v2,
    format_owners_page,
    get_pagination_keyboard,
    get_task_status_keyboard
)

router = Router()


def get_filter_main_keyboard(user_id: int, filters: dict):
    """Главная клавиатура фильтров"""
    builder = InlineKeyboardBuilder()
    
    collections_count = len(filters.get("collections", []))
    models_count = len(filters.get("models", []))
    backdrops_count = len(filters.get("backdrops", []))
    
    collections_text = f"Коллекции ({collections_count})"
    builder.button(text=collections_text, callback_data="filter_select_collections:0")
    
    if collections_count > 0:
        models_text = f"Модели ({models_count})"
        backdrops_text = f"Фоны ({backdrops_count})"
        builder.button(text=models_text, callback_data="filter_select_models:0")
        builder.button(text=backdrops_text, callback_data="filter_select_backdrops:0")
    
    if collections_count > 0 or models_count > 0 or backdrops_count > 0:
        builder.button(text="🗑 Сбросить всё", callback_data="filter_reset_all")
    
    if collections_count > 0:
        builder.button(text="Начать парсинг", callback_data="filter_start_parsing")
    
    builder.button(text=BUTTONS["back"], callback_data="back_to_main")
    
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_collections_filter_keyboard(page: int, selected_collections: list, per_page: int = 10):
    """Клавиатура выбора коллекций"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    collections_page = ALL_COLLECTIONS[start_idx:end_idx]
    
    for collection in collections_page:
        is_selected = collection in selected_collections
        checkbox = "✅" if is_selected else "⬜"
        builder.button(
            text=f"{checkbox} {collection}",
            callback_data=f"filter_toggle_collection:{collection}"
        )
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(("⬅️ Назад", f"filter_select_collections:{page-1}"))
    if end_idx < len(ALL_COLLECTIONS):
        nav_buttons.append(("➡️ Далее", f"filter_select_collections:{page+1}"))
    
    for text, callback in nav_buttons:
        builder.button(text=text, callback_data=callback)
    
    builder.button(text="✅ Выбрать все", callback_data=f"filter_select_all_collections:{page}")
    builder.button(text="❌ Сбросить", callback_data=f"filter_reset_collections:{page}")
    builder.button(text="✔️ Готово", callback_data="filter_done_collections")
    
    builder.adjust(2)
    return builder.as_markup()


def get_models_filter_keyboard(page: int, selected_collections: list, selected_models: list, per_page: int = 10):
    """Клавиатура выбора моделей"""
    builder = InlineKeyboardBuilder()
    
    all_models = []
    for collection in selected_collections:
        models = COLLECTION_MODELS.get(collection, [])
        all_models.extend(models)
    
    seen = set()
    unique_models = []
    for model in all_models:
        if model not in seen:
            seen.add(model)
            unique_models.append(model)
    
    if not unique_models:
        builder.button(text="⚠️ Нет доступных моделей", callback_data="filter_no_models")
        builder.button(text="⬅️ Назад", callback_data="filter_done_models")
        builder.adjust(1)
        return builder.as_markup()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    models_page = unique_models[start_idx:end_idx]
    
    for model in models_page:
        is_selected = model in selected_models
        checkbox = "✅" if is_selected else "⬜"
        model_callback = model.replace(" ", "_")
        builder.button(
            text=f"{checkbox} {model}",
            callback_data=f"filter_toggle_model:{model_callback}"
        )
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(("⬅️ Назад", f"filter_select_models:{page-1}"))
    if end_idx < len(unique_models):
        nav_buttons.append(("➡️ Далее", f"filter_select_models:{page+1}"))
    
    for text, callback in nav_buttons:
        builder.button(text=text, callback_data=callback)
    
    builder.button(text="✅ Выбрать все", callback_data=f"filter_select_all_models:{page}")
    builder.button(text="❌ Сбросить", callback_data=f"filter_reset_models:{page}")
    builder.button(text="✔️ Готово", callback_data="filter_done_models")
    
    builder.adjust(2)
    return builder.as_markup()


def get_backdrops_filter_keyboard(page: int, selected_backdrops: list, per_page: int = 10):
    """Клавиатура выбора фонов"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    backdrops_page = ALL_BACKDROPS[start_idx:end_idx]
    
    for backdrop in backdrops_page:
        is_selected = backdrop in selected_backdrops
        checkbox = "✅" if is_selected else "⬜"
        backdrop_callback = backdrop.replace(" ", "_")
        builder.button(
            text=f"{checkbox} {backdrop}",
            callback_data=f"filter_toggle_backdrop:{backdrop_callback}"
        )
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(("⬅️ Назад", f"filter_select_backdrops:{page-1}"))
    if end_idx < len(ALL_BACKDROPS):
        nav_buttons.append(("➡️ Далее", f"filter_select_backdrops:{page+1}"))
    
    for text, callback in nav_buttons:
        builder.button(text=text, callback_data=callback)
    
    builder.button(text="✅ Выбрать все", callback_data=f"filter_select_all_backdrops:{page}")
    builder.button(text="❌ Сбросить", callback_data=f"filter_reset_backdrops:{page}")
    builder.button(text="✔️ Готово", callback_data="filter_done_backdrops")
    
    builder.adjust(2)
    return builder.as_markup()


def format_filters_summary(filters: dict) -> str:
    """Форматировать сводку фильтров"""
    collections = filters.get("collections", [])
    models = filters.get("models", [])
    backdrops = filters.get("backdrops", [])
    
    lines = ["**Текущие фильтры:**\n"]
    
    if collections:
        collections_text = ", ".join(collections[:3])
        if len(collections) > 3:
            collections_text += f" и ещё {len(collections) - 3}"
        lines.append(f"Коллекции: {collections_text}")
    else:
        lines.append("Коллекции: не выбраны")
    
    if models:
        models_text = ", ".join(models[:3])
        if len(models) > 3:
            models_text += f" и ещё {len(models) - 3}"
        lines.append(f"Модели: {models_text}")
    else:
        lines.append("Модели: не выбраны")
    
    if backdrops:
        backdrops_text = ", ".join(backdrops[:3])
        if len(backdrops) > 3:
            backdrops_text += f" и ещё {len(backdrops) - 3}"
        lines.append(f"Фоны: {backdrops_text}")
    else:
        lines.append("Фоны: не выбраны")
    
    return "\n".join(lines)


async def send_filter_parsing_result(bot: Bot, user_id: int, task_id: str, collections: list, models: list, backdrops: list):
    """Фоновая отправка результатов парсинга с фильтрами"""
    try:
        task = await task_queue.wait_for_task(task_id, timeout=300)
        
        if not task or task.status == TaskStatus.FAILED:
            error_msg = task.error if task else "Timeout"
            filters = await db.get_user_filters(user_id)
            await bot.send_message(
                user_id,
                f"❌ Парсинг с фильтрами завершился с ошибкой:\n{error_msg}",
                reply_markup=get_filter_main_keyboard(user_id, filters),
                parse_mode="Markdown"
            )
            return
        
        result = task.result
        owners = result["owners"]
        duration = task.get_duration()
        
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
            request_type="filter",
            collection=f"{len(collections)} collections",
            result_count=len(owners)
        )
        
        await redis_cache.redis_cache.set(task_id, {
            "type": "filter",
            "collections": collections,
            "models": models,
            "backdrops": backdrops,
            "owners": owners,
            "duration": duration
        })
        
        formatted_results, total_pages = format_owners_page(owners, page=0, per_page=10)
        
        escaped_duration = escape_markdown_v2(f"{duration:.1f}")
        
        filters_summary = []
        filters_summary.append(f"📦 Коллекции: {len(collections)}")
        if models:
            filters_summary.append(f"🎨 Модели: {len(models)}")
        if backdrops:
            filters_summary.append(f"🖼 Фоны: {len(backdrops)}")
        
        message_text = (
            f"✅ *Парсинг завершён\\!*\n\n"
            f"{escape_markdown_v2(chr(10).join(filters_summary))}\n"
            f"👥 Найдено владельцев: {len(owners)}\n"
            f"⏱ Время: {escaped_duration}с\n\n"
            f"{formatted_results}"
        )
        
        await bot.send_message(
            user_id,
            message_text,
            reply_markup=get_pagination_keyboard("filter_page", 0, total_pages, task_id),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        print(f"❌ Ошибка отправки результата filter парсинга: {e}")


@router.callback_query(F.data == "filter_parsing")
async def callback_filter_parsing(callback: CallbackQuery):
    """Открыть меню парсинга по фильтрам"""
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    summary = format_filters_summary(filters)
    
    await callback.message.edit_text(
        f"🔍 **Парсинг по фильтрам**\n\n{summary}\n\nВыберите действие:",
        reply_markup=get_filter_main_keyboard(user_id, filters),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter_select_collections:"))
async def callback_select_collections(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])
    filters = await db.get_user_filters(user_id)
    selected_collections = filters.get("collections", [])
    
    await callback.message.edit_text(
        f"📦 **Выбор коллекций** (выбрано: {len(selected_collections)})",
        reply_markup=get_collections_filter_keyboard(page, selected_collections),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter_toggle_collection:"))
async def callback_toggle_collection(callback: CallbackQuery):
    user_id = callback.from_user.id
    collection = callback.data.split(":", 1)[1]
    filters = await db.get_user_filters(user_id)
    collections = filters.get("collections", [])
    
    if collection in collections:
        collections.remove(collection)
    else:
        collections.append(collection)
    
    filters["collections"] = collections
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        f"📦 **Выбор коллекций** (выбрано: {len(collections)})",
        reply_markup=get_collections_filter_keyboard(0, collections),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter_select_all_collections:"))
async def callback_select_all_collections(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    filters["collections"] = ALL_COLLECTIONS.copy()
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        f"📦 **Выбор коллекций** (выбрано: {len(ALL_COLLECTIONS)})",
        reply_markup=get_collections_filter_keyboard(0, ALL_COLLECTIONS),
        parse_mode="Markdown"
    )
    await callback.answer("✅ Все коллекции выбраны")


@router.callback_query(F.data.startswith("filter_reset_collections:"))
async def callback_reset_collections(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    filters["collections"] = []
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        "📦 **Выбор коллекций** (выбрано: 0)",
        reply_markup=get_collections_filter_keyboard(0, []),
        parse_mode="Markdown"
    )
    await callback.answer("🗑 Коллекции сброшены")


@router.callback_query(F.data == "filter_done_collections")
async def callback_done_collections(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    summary = format_filters_summary(filters)
    
    await callback.message.edit_text(
        f"**Парсинг по фильтрам**\n\n{summary}\n\nВыберите действие:",
        reply_markup=get_filter_main_keyboard(user_id, filters),
        parse_mode="Markdown"
    )
    await callback.answer("✅ Коллекции сохранены")


@router.callback_query(F.data.startswith("filter_select_models:"))
async def callback_select_models(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])
    filters = await db.get_user_filters(user_id)
    selected_collections = filters.get("collections", [])
    selected_models = filters.get("models", [])
    
    if not selected_collections:
        await callback.answer("⚠️ Сначала выберите коллекции", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"🎨 **Выбор моделей** (выбрано: {len(selected_models)})",
        reply_markup=get_models_filter_keyboard(page, selected_collections, selected_models),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter_toggle_model:"))
async def callback_toggle_model(callback: CallbackQuery):
    user_id = callback.from_user.id
    model_callback = callback.data.split(":", 1)[1]
    model = model_callback.replace("_", " ")
    
    filters = await db.get_user_filters(user_id)
    models = filters.get("models", [])
    collections = filters.get("collections", [])
    
    if model in models:
        models.remove(model)
    else:
        models.append(model)
    
    filters["models"] = models
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        f"🎨 **Выбор моделей** (выбрано: {len(models)})",
        reply_markup=get_models_filter_keyboard(0, collections, models),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter_select_all_models:"))
async def callback_select_all_models(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    collections = filters.get("collections", [])
    
    all_models = []
    for collection in collections:
        models = COLLECTION_MODELS.get(collection, [])
        all_models.extend(models)
    all_models = list(set(all_models))
    
    filters["models"] = all_models
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        f"🎨 **Выбор моделей** (выбрано: {len(all_models)})",
        reply_markup=get_models_filter_keyboard(0, collections, all_models),
        parse_mode="Markdown"
    )
    await callback.answer("✅ Все модели выбраны")


@router.callback_query(F.data.startswith("filter_reset_models:"))
async def callback_reset_models(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    collections = filters.get("collections", [])
    filters["models"] = []
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        "🎨 **Выбор моделей** (выбрано: 0)",
        reply_markup=get_models_filter_keyboard(0, collections, []),
        parse_mode="Markdown"
    )
    await callback.answer("🗑 Модели сброшены")


@router.callback_query(F.data == "filter_done_models")
async def callback_done_models(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    summary = format_filters_summary(filters)
    
    await callback.message.edit_text(
        f"**Парсинг по фильтрам**\n\n{summary}\n\nВыберите действие:",
        reply_markup=get_filter_main_keyboard(user_id, filters),
        parse_mode="Markdown"
    )
    await callback.answer("✅ Модели сохранены")


@router.callback_query(F.data.startswith("filter_select_backdrops:"))
async def callback_select_backdrops(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])
    filters = await db.get_user_filters(user_id)
    selected_backdrops = filters.get("backdrops", [])
    
    await callback.message.edit_text(
        f"🖼 **Выбор фонов** (выбрано: {len(selected_backdrops)})",
        reply_markup=get_backdrops_filter_keyboard(page, selected_backdrops),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter_toggle_backdrop:"))
async def callback_toggle_backdrop(callback: CallbackQuery):
    user_id = callback.from_user.id
    backdrop_callback = callback.data.split(":", 1)[1]
    backdrop = backdrop_callback.replace("_", " ")
    
    filters = await db.get_user_filters(user_id)
    backdrops = filters.get("backdrops", [])
    
    if backdrop in backdrops:
        backdrops.remove(backdrop)
    else:
        backdrops.append(backdrop)
    
    filters["backdrops"] = backdrops
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        f"🖼 **Выбор фонов** (выбрано: {len(backdrops)})",
        reply_markup=get_backdrops_filter_keyboard(0, backdrops),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter_select_all_backdrops:"))
async def callback_select_all_backdrops(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    filters["backdrops"] = ALL_BACKDROPS.copy()
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        f"🖼 **Выбор фонов** (выбрано: {len(ALL_BACKDROPS)})",
        reply_markup=get_backdrops_filter_keyboard(0, ALL_BACKDROPS),
        parse_mode="Markdown"
    )
    await callback.answer("✅ Все фоны выбраны")


@router.callback_query(F.data.startswith("filter_reset_backdrops:"))
async def callback_reset_backdrops(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    filters["backdrops"] = []
    await db.save_user_filters(user_id, filters)
    
    await callback.message.edit_text(
        "🖼 **Выбор фонов** (выбрано: 0)",
        reply_markup=get_backdrops_filter_keyboard(0, []),
        parse_mode="Markdown"
    )
    await callback.answer("🗑 Фоны сброшены")


@router.callback_query(F.data == "filter_done_backdrops")
async def callback_done_backdrops(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = await db.get_user_filters(user_id)
    summary = format_filters_summary(filters)
    
    await callback.message.edit_text(
        f"**Парсинг по фильтрам**\n\n{summary}\n\nВыберите действие:",
        reply_markup=get_filter_main_keyboard(user_id, filters),
        parse_mode="Markdown"
    )
    await callback.answer("✅ Фоны сохранены")


@router.callback_query(F.data == "filter_reset_all")
async def callback_reset_all_filters(callback: CallbackQuery):
    user_id = callback.from_user.id
    filters = {"collections": [], "models": [], "backdrops": []}
    await db.save_user_filters(user_id, filters)
    summary = format_filters_summary(filters)
    
    await callback.message.edit_text(
        f"🔍 **Парсинг по фильтрам**\n\n{summary}\n\nВыберите действие:",
        reply_markup=get_filter_main_keyboard(user_id, filters),
        parse_mode="Markdown"
    )
    await callback.answer("🗑 Все фильтры сброшены")


@router.callback_query(F.data == "filter_start_parsing")
async def callback_start_filter_parsing(callback: CallbackQuery):
    """Запустить парсинг с фильтрами - асинхронная обработка"""
    user_id = callback.from_user.id
    
    if not check_rate_limit(user_id):
        await callback.answer(MESSAGES["rate_limit"], show_alert=True)
        return
    
    filters = await db.get_user_filters(user_id)
    collections = filters.get("collections", [])
    models = filters.get("models", [])
    backdrops = filters.get("backdrops", [])
    
    if not collections:
        await callback.answer("⚠️ Выберите хотя бы одну коллекцию", show_alert=True)
        return
    
    task_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
    
    added = await task_queue.add_task(
        task_id=task_id,
        user_id=user_id,
        task_type="filter",
        collection=f"{len(collections)}_collections",
        callback=lambda col, uid: parse_with_filters(collections, models, backdrops, uid)
    )
    
    if not added:
        await callback.message.edit_text(
            MESSAGES["queue_full"],
            reply_markup=get_filter_main_keyboard(user_id, filters)
        )
        await callback.answer()
        return
    
    filters_info = []
    filters_info.append(f"📦 Коллекции: {len(collections)}")
    if models:
        filters_info.append(f"🎨 Модели: {len(models)}")
    if backdrops:
        filters_info.append(f"🖼 Фоны: {len(backdrops)}")
    
    queue_size = task_queue.get_queue_size()
    await callback.message.edit_text(
        f"⏳ **Задача добавлена в очередь**\n\n"
        f"{chr(10).join(filters_info)}\n"
        f"🔢 Задача: \\#{task_id[:8]}\n"
        f"📋 В очереди: {queue_size} задач\n\n"
        f"Вы получите уведомление когда парсинг завершится\\.",
        reply_markup=get_task_status_keyboard(task_id),
        parse_mode="MarkdownV2"
    )
    await callback.answer("✅ Задача добавлена")
    
    asyncio.create_task(
        send_filter_parsing_result(callback.bot, user_id, task_id, collections, models, backdrops)
    )


@router.callback_query(F.data.startswith("filter_page:"))
async def callback_filter_page(callback: CallbackQuery):
    """Навигация по страницам результатов"""
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
    collections = cached["collections"]
    models = cached.get("models", [])
    backdrops = cached.get("backdrops", [])
    duration = cached["duration"]
    
    formatted_results, total_pages = format_owners_page(owners, page=page, per_page=10)
    
    escaped_duration = escape_markdown_v2(f"{duration:.1f}")
    
    filters_summary = []
    filters_summary.append(f"📦 Коллекции: {len(collections)}")
    if models:
        filters_summary.append(f"🎨 Модели: {len(models)}")
    if backdrops:
        filters_summary.append(f"🖼 Фоны: {len(backdrops)}")
    
    message_text = (
        f"✅ *Парсинг завершён\\!*\n\n"
        f"{escape_markdown_v2(chr(10).join(filters_summary))}\n"
        f"👥 Найдено владельцев: {len(owners)}\n"
        f"⏱ Время: {escaped_duration}с\n\n"
        f"{formatted_results}"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_pagination_keyboard("filter_page", page, total_pages, task_id),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data.startswith("refresh_filter"))
async def callback_refresh_filter(callback: CallbackQuery):
    """Обновить парсинг с фильтрами - асинхронная обработка"""
    user_id = callback.from_user.id
    
    if not check_rate_limit(user_id):
        await callback.answer(MESSAGES["rate_limit"], show_alert=True)
        return
    
    parts = callback.data.split(":")
    old_task_id = parts[1] if len(parts) > 1 else None
    
    collections = []
    models = []
    backdrops = []
    
    if old_task_id:
        cached = await redis_cache.redis_cache.get(old_task_id)
        if cached:
            collections = cached.get("collections", [])
            models = cached.get("models", [])
            backdrops = cached.get("backdrops", [])
    
    if not collections:
        filters = await db.get_user_filters(user_id)
        collections = filters.get("collections", [])
        models = filters.get("models", [])
        backdrops = filters.get("backdrops", [])
    
    if not collections:
        await callback.answer("⚠️ Фильтры не найдены. Настройте их заново.", show_alert=True)
        return
    
    task_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
    
    added = await task_queue.add_task(
        task_id=task_id,
        user_id=user_id,
        task_type="filter",
        collection=f"{len(collections)}_collections",
        callback=lambda col, uid: parse_with_filters(collections, models, backdrops, uid)
    )
    
    if not added:
        filters = await db.get_user_filters(user_id)
        await callback.message.edit_text(
            MESSAGES["queue_full"],
            reply_markup=get_filter_main_keyboard(user_id, filters)
        )
        await callback.answer()
        return
    
    filters_info = []
    filters_info.append(f"📦 Коллекции: {len(collections)}")
    if models:
        filters_info.append(f"🎨 Модели: {len(models)}")
    if backdrops:
        filters_info.append(f"🖼 Фоны: {len(backdrops)}")
    
    queue_size = task_queue.get_queue_size()
    await callback.message.edit_text(
        f"🔄 **Обновление: задача добавлена в очередь**\n\n"
        f"{chr(10).join(filters_info)}\n"
        f"🔢 Задача: \\#{task_id[:8]}\n"
        f"📋 В очереди: {queue_size} задач\n\n"
        f"Вы получите уведомление когда парсинг завершится\\.",
        reply_markup=get_task_status_keyboard(task_id),
        parse_mode="MarkdownV2"
    )
    await callback.answer("🔄 Обновление запущено")
    
    asyncio.create_task(
        send_filter_parsing_result(callback.bot, user_id, task_id, collections, models, backdrops)
    )
