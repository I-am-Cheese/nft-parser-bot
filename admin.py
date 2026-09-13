"""
Админ панель бота
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError
import asyncio

from config import ADMIN_IDS, BUTTONS
from database import db
from async_queue import task_queue
from handlers import escape_markdown_v2

router = Router()


def is_admin(user_id: int) -> bool:
    return True   # временно открыто для всех

def get_admin_keyboard():
    """Клавиатура админ панели"""
    builder = InlineKeyboardBuilder()
    builder.button(text=BUTTONS["stats"], callback_data="admin_stats")
    builder.button(text=BUTTONS["proxy"], callback_data="admin_proxies")
    builder.button(text=BUTTONS["broadcast"], callback_data="admin_broadcast")
    builder.button(text=BUTTONS["back"], callback_data="back_to_main")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def get_back_to_admin_keyboard():
    """Клавиатура с кнопкой возврата в админку"""
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад в админку", callback_data="admin_panel")
    return builder.as_markup()


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Команда /admin - открыть админ панель"""
    user_id = message.from_user.id
    print(f"DEBUG ADMIN: пришёл user_id = {user_id}")
    print(f"DEBUG ADMIN: ADMIN_IDS = {ADMIN_IDS}")
    
    if not is_admin(user_id):
        await message.answer(f"❌ У вас нет доступа к админ панели\nТвой ID: `{user_id}`", parse_mode="Markdown")
        return
    
    await message.answer(
        "Админ панель",
        reply_markup=get_admin_keyboard(),
    )


@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery):
    """Вернуться в админ панель"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⚙️ **Админ панель**\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery):
    """Показать статистику"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Получаем статистику из БД
    total_users = await db.get_total_users()
    new_users_24h = await db.get_new_users_24h()
    blocked_users = await db.get_blocked_users_count()
    requests_today = await db.get_requests_today()
    
    # Статистика очереди
    queue_stats = task_queue.get_stats()
    
    # Топ пользователей
    top_users = await db.get_top_users(limit=5)
    top_users_text = "\n".join([
        f"{i}. {name}: {count} запросов"
        for i, (name, count) in enumerate(top_users, 1)
    ]) if top_users else "Нет данных"
    
    stats_text = f"""📊 **Статистика бота**

👥 **Пользователи:**
- Всего: {total_users}
- Новых за 24 часа: {new_users_24h}
- Заблокировали бота: {blocked_users}

📈 **Запросы:**
- За сегодня: {requests_today}
- Всего обработано: {escape_markdown_v2(str(queue_stats['total_processed']))}
- Ошибок: {escape_markdown_v2(str(queue_stats['total_failed']))}

⚙️ **Очередь:**
- В очереди: {escape_markdown_v2(str(queue_stats['queue_size']))}
- Ожидают: {escape_markdown_v2(str(queue_stats['pending_tasks']))}
- Обрабатываются: {escape_markdown_v2(str(queue_stats['processing_tasks']))}

🏆 **Топ пользователей:**
{escape_markdown_v2(top_users_text)}
"""
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=get_back_to_admin_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


# Состояние для рассылки
broadcast_waiting = {}


@router.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast(callback: CallbackQuery):
    """Начать рассылку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    broadcast_waiting[callback.from_user.id] = True
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад в админку", callback_data="admin_broadcast_cancel")
    
    await callback.message.edit_text(
        "📢 **Рассылка сообщений**\n\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям.\n\n"
        "Или отправьте /cancel для отмены.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel_broadcast(message: Message):
    """Отменить рассылку"""
    if message.from_user.id in broadcast_waiting:
        del broadcast_waiting[message.from_user.id]
        await message.answer(
            "❌ Рассылка отменена",
            reply_markup=get_admin_keyboard()
        )


@router.callback_query(F.data == "admin_broadcast_cancel")
async def callback_admin_broadcast_cancel(callback: CallbackQuery):
    """Отменить рассылку через кнопку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Очищаем состояние рассылки
    if user_id in broadcast_waiting:
        del broadcast_waiting[user_id]
    if f"{user_id}_text" in broadcast_waiting:
        del broadcast_waiting[f"{user_id}_text"]
    if f"{user_id}_photo" in broadcast_waiting:
        del broadcast_waiting[f"{user_id}_photo"]
    
    await callback.message.edit_text(
        "⚙️ **Админ панель**\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer("❌ Рассылка отменена")


# Состояние для добавления прокси
add_proxy_waiting = {}


@router.message(F.text)
async def handle_text_messages(message: Message):
    """Обработать текстовые сообщения (рассылка или добавление прокси)"""
    user_id = message.from_user.id
    
    # Проверяем, ждём ли рассылку от этого админа
    if user_id in broadcast_waiting:
        if not is_admin(user_id):
            return
        
        # Убираем из ожидания
        del broadcast_waiting[user_id]
        
        # Подтверждение
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, отправить", callback_data="confirm_broadcast")
        builder.button(text="❌ Отмена", callback_data="admin_panel")
        builder.adjust(2)
        
        from html import escape as html_escape
        safe_text = html_escape(message.text)
        
        await message.answer(
            f"📢 <b>Подтверждение рассылки</b>\n\n"
            f"Сообщение:\n{safe_text}\n\n"
            f"Отправить всем пользователям?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
        # Сохраняем текст сообщения
        broadcast_waiting[f"{user_id}_text"] = message.text
        return
    
    # Проверяем, ждём ли добавление прокси
    if user_id in add_proxy_waiting:
        if not is_admin(user_id):
            return
        
        # Импортируем proxy_manager внутри функции
        from proxy_manager import proxy_manager
        
        # Проверка proxy_manager
        if not proxy_manager:
            await message.answer("❌ ProxyManager не инициализирован")
            del add_proxy_waiting[user_id]
            return
        
        # Убираем из ожидания
        del add_proxy_waiting[user_id]
        
        # Разбиваем текст на строки (поддержка списка прокси)
        proxy_lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        
        if not proxy_lines:
            await message.answer("❌ Не найдено прокси для добавления")
            return
        
        # Добавляем прокси (с проверкой)
        status_msg = await message.answer(f"🔍 Проверяю {len(proxy_lines)} прокси...")
        
        added = 0
        failed = 0
        
        for proxy in proxy_lines:
            result = await proxy_manager.add_proxy(proxy, user_id, check_before_add=True)
            if result['success']:
                added += 1
            else:
                failed += 1
        
        await status_msg.delete()
        
        # Формируем результат
        result_text = f"✅ Добавлено: {added}\n❌ Ошибок: {failed}\n📊 Всего обработано: {len(proxy_lines)}"
        
        # Клавиатура возврата к прокси
        builder = InlineKeyboardBuilder()
        builder.button(text="Назад к прокси", callback_data="admin_proxies")
        
        await message.answer(
            result_text,
            reply_markup=builder.as_markup()
        )
        return


@router.message(F.photo)
async def handle_photo_messages(message: Message):
    """Обработать фото сообщения (рассылка)"""
    user_id = message.from_user.id
    
    # Проверяем, ждём ли рассылку от этого админа
    if user_id in broadcast_waiting:
        if not is_admin(user_id):
            return
        
        # Убираем из ожидания
        del broadcast_waiting[user_id]
        
        # Получаем file_id и caption
        photo_id = message.photo[-1].file_id
        caption = message.caption or ""
        
        # Подтверждение
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, отправить", callback_data="confirm_broadcast")
        builder.button(text="❌ Отмена", callback_data="admin_panel")
        builder.adjust(2)
        
        from html import escape as html_escape
        safe_caption = html_escape(caption) if caption else "Без подписи"
        
        await message.answer_photo(
            photo=photo_id,
            caption=f"📢 <b>Подтверждение рассылки</b>\n\n{safe_caption}\n\nОтправить всем пользователям?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
        # Сохраняем фото и текст
        broadcast_waiting[f"{user_id}_photo"] = photo_id
        broadcast_waiting[f"{user_id}_text"] = caption
        return


async def run_broadcast_task(bot, admin_chat_id: int, message_id: int, broadcast_text: str, photo_id: str = None):
    """Фоновая задача рассылки"""
    success = 0
    failed = 0
    blocked = 0
    
    batch_size = 100
    offset = 0
    
    try:
        while True:
            # Получаем пользователей батчами
            user_ids = await db.get_user_ids_batch(limit=batch_size, offset=offset)
            
            if not user_ids:
                break
            
            # Рассылка с rate limiting
            for uid in user_ids:
                try:
                    if photo_id:
                        await bot.send_photo(uid, photo=photo_id, caption=broadcast_text, parse_mode=None)
                    else:
                        await bot.send_message(uid, broadcast_text, parse_mode=None)
                    success += 1
                    await asyncio.sleep(0.05)  # 20 сообщений в секунду
                    
                except TelegramForbiddenError:
                    # Пользователь заблокировал бота
                    blocked += 1
                    await db.mark_user_blocked(uid)
                    
                except TelegramRetryAfter as e:
                    # Rate limit от Telegram
                    await asyncio.sleep(e.retry_after)
                    try:
                        if photo_id:
                            await bot.send_photo(uid, photo=photo_id, caption=broadcast_text, parse_mode=None)
                        else:
                            await bot.send_message(uid, broadcast_text, parse_mode=None)
                        success += 1
                    except TelegramForbiddenError:
                        blocked += 1
                        await db.mark_user_blocked(uid)
                    except:
                        failed += 1
                        
                except Exception as e:
                    failed += 1
                    print(f"❌ Ошибка отправки пользователю {uid}: {e}")
            
            offset += batch_size
            
            # Обновляем прогресс каждые 100 пользователей
            if offset % 100 == 0:
                try:
                    await bot.edit_message_text(
                        f"⏳ **Рассылка в процессе...**\n\n"
                        f"📊 Обработано: {offset}\n"
                        f"✅ Успешно: {success}\n"
                        f"❌ Ошибок: {failed}\n"
                        f"🚫 Заблокировали: {blocked}",
                        chat_id=admin_chat_id,
                        message_id=message_id,
                        parse_mode="Markdown"
                    )
                except:
                    pass
        
        # Результат
        result_text = f"""✅ **Рассылка завершена!**

📊 Статистика:
• Успешно: {success}
• Ошибок: {failed}
• Заблокировали бота: {blocked}
• Всего обработано: {offset}
"""
        
        await bot.edit_message_text(
            result_text,
            chat_id=admin_chat_id,
            message_id=message_id,
            reply_markup=get_back_to_admin_keyboard(),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        print(f"❌ Критическая ошибка в рассылке: {e}")
        try:
            await bot.edit_message_text(
                f"❌ **Ошибка рассылки**\n\n{str(e)}",
                chat_id=admin_chat_id,
                message_id=message_id,
                reply_markup=get_back_to_admin_keyboard(),
                parse_mode="Markdown"
            )
        except:
            pass


@router.callback_query(F.data == "confirm_broadcast")
async def callback_confirm_broadcast(callback: CallbackQuery):
    """Подтвердить рассылку"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Получаем текст сообщения и фото
    broadcast_text = broadcast_waiting.get(f"{user_id}_text")
    photo_id = broadcast_waiting.get(f"{user_id}_photo")
    
    if not broadcast_text and not photo_id:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    # Удаляем временные данные
    if f"{user_id}_text" in broadcast_waiting:
        del broadcast_waiting[f"{user_id}_text"]
    if f"{user_id}_photo" in broadcast_waiting:
        del broadcast_waiting[f"{user_id}_photo"]
    
    # Удаляем сообщение с подтверждением и отправляем новое
    await callback.message.delete()
    msg = await callback.bot.send_message(
        callback.message.chat.id,
        "⏳ **Рассылка запущена в фоне...**\n\n"
        "📊 Инициализация...",
        parse_mode="Markdown"
    )
    await callback.answer()
    
    # Запускаем рассылку в фоне
    asyncio.create_task(
        run_broadcast_task(
            callback.bot,
            callback.message.chat.id,
            msg.message_id,
            broadcast_text,
            photo_id
        )
    )


@router.callback_query(F.data == "admin_proxies")
async def callback_admin_proxies(callback: CallbackQuery):
    """Управление прокси"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Импортируем proxy_manager внутри функции
    from proxy_manager import proxy_manager
    
    # Проверка proxy_manager
    if not proxy_manager:
        await callback.answer("❌ ProxyManager не инициализирован", show_alert=True)
        await callback.message.edit_text(
            "❌ **Ошибка**\n\nProxyManager не инициализирован. Перезапустите бота.",
            reply_markup=get_admin_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Получаем статистику
    stats = await proxy_manager.get_proxies_stats()
    
    # Клавиатура управления прокси
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Показать все", callback_data="admin_proxies_list")
    builder.button(text="➕ Добавить прокси", callback_data="admin_add_proxy")
    builder.button(text="🔄 Проверить сейчас", callback_data="admin_check_proxies")
    builder.button(text="Назад в админку", callback_data="admin_panel")
    builder.adjust(2, 1, 1)
    
    text = (
        f"📡 **Управление прокси**\n\n"
        f"📊 Всего в базе: {stats['total']}\n"
        f"✅ Активных: {stats['active']}\n"
        f"❌ Неактивных: {stats['inactive']}\n\n"
        f"Проверка происходит автоматически каждые 6 часов."
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_proxies_list")
async def callback_admin_proxies_list(callback: CallbackQuery):
    """Показать список всех прокси"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Импортируем proxy_manager внутри функции
    from proxy_manager import proxy_manager
    
    # Проверка proxy_manager
    if not proxy_manager:
        await callback.answer("❌ ProxyManager не инициализирован", show_alert=True)
        return
    
    all_proxies = await proxy_manager.db.get_all_proxies()
    
    if not all_proxies:
        text = "📡 **Список прокси**\n\n❌ Прокси не найдены"
    else:
        text = f"📡 **Список прокси** ({len(all_proxies)})\n\n"
        for i, proxy in enumerate(all_proxies[:20], 1):  # Показываем первые 20
            masked = proxy_manager._mask_proxy(proxy)
            text += f"{i}. `{masked}`\n"
        
        if len(all_proxies) > 20:
            text += f"\n... и ещё {len(all_proxies) - 20}"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад к прокси", callback_data="admin_proxies")
    
    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add_proxy")
async def callback_admin_add_proxy(callback: CallbackQuery):
    """Начать добавление прокси"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Импортируем proxy_manager внутри функции
    from proxy_manager import proxy_manager
    
    # Проверка proxy_manager
    if not proxy_manager:
        await callback.answer("❌ ProxyManager не инициализирован", show_alert=True)
        return
    
    add_proxy_waiting[callback.from_user.id] = True
    
    await callback.message.edit_text(
        "➕ **Добавление прокси**\n\n"
        "Отправьте прокси в формате:\n"
        "`http://user:pass@host:port`\n\n"
        "Можно отправить несколько прокси (каждый с новой строки)\n\n"
        "Или /cancel для отмены.",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_check_proxies")
async def callback_admin_check_proxies(callback: CallbackQuery):
    """Запустить проверку прокси вручную"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Импортируем proxy_manager внутри функции
    from proxy_manager import proxy_manager
    
    # Проверка proxy_manager
    if not proxy_manager:
        await callback.answer("❌ ProxyManager не инициализирован", show_alert=True)
        return
    
    await callback.answer("🔍 Запускаю проверку...", show_alert=True)
    
    await callback.message.edit_text(
        "🔍 **Проверка прокси запущена**\n\n"
        "Это может занять несколько минут...",
        parse_mode="Markdown"
    )
    
    # Запускаем проверку
    result = await proxy_manager.check_all_proxies()
    
    # Удаляем мертвые
    removed = await proxy_manager.remove_dead_proxies(result['dead_list'])
    
    # Формируем ответ
    text = (
        f"✅ **Проверка завершена**\n\n"
        f"✅ Живых: {result['alive']}\n"
        f"❌ Мертвых: {result['dead']}\n"
        f"🗑 Удалено: {removed}\n"
        f"📊 Осталось: {result['alive']}"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад к прокси", callback_data="admin_proxies")
    
    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
