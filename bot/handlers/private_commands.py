import time
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from ..database import get_chat, load_data
from ..config import get_default_settings
from ..utils import escape_markdown
from ..config import RANK_ORDER, RANK_NAMES
from ..filters.chat_type import PrivateChatFilter

router = Router()
router.message.filter(PrivateChatFilter())

# ---------- FSM для анонимных сообщений ----------
class AnonStates(StatesGroup):
    waiting_for_chat = State()

# ---------- /start ----------
@router.message(Command("start"))
async def start_private(message: Message):
    await message.reply("**Бот готов к работе!**\nЗдесь вы можете использовать команды /menu и /anonim", parse_mode="MarkdownV2")

# ---------- Общая клавиатура общих чатов ----------
async def common_chats_keyboard(user_id: int, bot: Bot, for_anon: bool = False):
    all_data = await load_data()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for chat_id_str, chat_data in all_data.items():
        try:
            member = await bot.get_chat_member(int(chat_id_str), user_id)
            if member:
                title = (await bot.get_chat(int(chat_id_str))).title
                anon_enabled = chat_data.get("settings", get_default_settings()).get("anonymous", "off") == "on"
                if for_anon and not anon_enabled:
                    callback = f"anon_denied|{title}"
                else:
                    callback = f"menu_chat|{chat_id_str}" if not for_anon else f"anon_confirm|{chat_id_str}"
                keyboard.inline_keyboard.append([InlineKeyboardButton(text=title, callback_data=callback)])
        except:
            continue
    keyboard.inline_keyboard.sort(key=lambda x: x[0].text.lower())
    return keyboard

# ---------- /menu ----------
@router.message(Command("menu"))
async def menu_command(message: Message, bot: Bot):
    user_id = message.from_user.id
    keyboard = await common_chats_keyboard(user_id, bot, for_anon=False)
    if not keyboard.inline_keyboard:
        await message.reply("Нет общих чатов")
        return
    await message.reply("Выберите чат:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("menu_chat|"))
async def menu_chat_callback(callback: CallbackQuery, bot: Bot):
    chat_id = callback.data.split("|")[1]
    chat_data = await get_chat(chat_id)
    user_rank = chat_data.get("users", {}).get(str(callback.from_user.id), {}).get("rank", "$")
    settings = chat_data["settings"]
    list_word_allowed = settings.get("list_word_access") == "$" or RANK_ORDER.index(user_rank) >= RANK_ORDER.index("***")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="My Stats", callback_data=f"menu_action|{chat_id}|mystats"),
         InlineKeyboardButton(text="Chat", callback_data=f"menu_action|{chat_id}|chat")],
        [InlineKeyboardButton(text="Ranks", callback_data=f"menu_action|{chat_id}|ranks"),
         InlineKeyboardButton(text="List Word", callback_data=f"menu_action|{chat_id}|listword" if list_word_allowed else f"menu_action_denied|{chat_id}")],
        [InlineKeyboardButton(text="← Назад", callback_data="menu_back")]
    ])
    await callback.message.edit_text("Выберите действие:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("menu_action_denied"))
async def menu_action_denied(callback: CallbackQuery):
    await callback.answer("Просмотр недоступен", show_alert=True)

@router.callback_query(F.data.startswith("menu_action|"))
async def menu_action_callback(callback: CallbackQuery, bot: Bot):
    _, chat_id, action = callback.data.split("|")
    chat_data = await get_chat(chat_id)
    if action == "mystats":
        user_id = str(callback.from_user.id)
        user_data = chat_data.get("users", {}).get(user_id, {})
        rank = user_data.get("rank", "$")
        warns = user_data.get("warns", 0)
        blocked_until = user_data.get("blocked_until")
        msg_total = user_data.get("msg_total", 0)
        msg_30d = user_data.get("msg_last_30d", 0)
        msg_7d = user_data.get("msg_last_7d", 0)
        tz = int(chat_data["settings"].get("timezone", "+3"))
        lines = [f"**Статистика пользователя @{callback.from_user.username or callback.from_user.first_name}**"]
        lines.append(f"• Ранг: {RANK_NAMES.get(rank, 'участник')}")
        if warns:
            lines.append(f"• Всего варнов: {warns}")
        else:
            lines.append("• Варны отсутствуют")
        if blocked_until and blocked_until > time.time():
            local = datetime.utcfromtimestamp(blocked_until) + timedelta(hours=tz)
            lines.append(f"• Заблокирован до {local.strftime('%d.%m.%y %H:%M')}")
        else:
            lines.append("• Блокировки отсутствуют")
        if msg_total:
            lines.append(f"• Всего сообщений: {msg_total}")
            lines.append(f"• Сообщений за 30 дней: {msg_30d}")
            lines.append(f"• Сообщений за 7 дней: {msg_7d}")
        else:
            lines.append("• Сообщения отсутствуют")
        await callback.message.reply("\n".join(lines), parse_mode="MarkdownV2")
    elif action == "chat":
        users = chat_data.get("users", {})
        settings = chat_data.get("settings", get_default_settings())
        total_msgs = sum(u.get("msg_total", 0) for u in users.values())
        msgs_30d = sum(u.get("msg_last_30d", 0) for u in users.values())
        msgs_7d = sum(u.get("msg_last_7d", 0) for u in users.values())
        participants = len(users)
        blocked_now = sum(1 for u in users.values() if u.get("blocked_until") and u["blocked_until"] > time.time())
        total_warns = sum(u.get("warns", 0) for u in users.values())
        warned_users = sum(1 for u in users.values() if u.get("warns", 0) > 0)
        anon = "да" if settings.get("anonymous") == "on" else "нет"
        list_word_access = "все" if settings.get("list_word_access") == "$" else "ограничен"
        filter_mode = settings.get("filter_mode", "off")
        filter_text = {"off": "Off", "only_del": "Only Del", "only_warn": "Only Warn", "del_warn": "Del & Warn"}.get(filter_mode, filter_mode)
        search_mode = "подстрока" if settings.get("search_mode") == "substring" else "точное совпадение"
        tz = settings.get("timezone", "+3")
        lines = [
            "**Статистика чата**",
            f"• Всего сообщений: {total_msgs}",
            f"• Сообщений за 30 дней: {msgs_30d}",
            f"• Сообщений за 7 дней: {msgs_7d}",
            f"• Участников: {participants}",
            f"• Заблокировано сейчас: {blocked_now}",
            f"• Выдано {total_warns} предупреждений {warned_users} пользователям",
            f"• Анонимные сообщения: {anon}",
            f"• Просмотр ЧС слов: {list_word_access}",
            f"• Режим фильтра: {filter_text}",
            f"• Тип фильтра: {search_mode}",
            f"• Часовой пояс: UTC{tz}"
        ]
        await callback.message.reply("\n".join(lines), parse_mode="MarkdownV2")
    elif action == "ranks":
        rank_lists = {"*": [], "**": [], "***": [], "****": [], "#": []}
        for uid, data in chat_data.get("users", {}).items():
            rank = data.get("rank", "$")
            if rank in rank_lists:
                try:
                    member = await bot.get_chat_member(int(chat_id), int(uid))
                    uname = f"@{member.user.username}" if member.user.username else member.user.first_name
                except:
                    uname = f"id{uid}"
                rank_lists[rank].append(uname)
        for r in rank_lists:
            rank_lists[r].sort()
        lines = ["**Ранги**"]
        rank_names = {
            "*": "Младшие модераторы",
            "**": "Старшие модераторы",
            "***": "Младшие администраторы",
            "****": "Старшие администраторы",
            "#": "Создатель"
        }
        for r in ["*", "**", "***", "****", "#"]:
            names = "; ".join(rank_lists[r]) if rank_lists[r] else "отсутствуют"
            lines.append(f"• {rank_names[r]}: {names}")
        await callback.message.reply("\n".join(lines), parse_mode="MarkdownV2")
    elif action == "listword":
        words = chat_data.get("words", [])
        text = "**Чёрный список слов**\n" + "\n".join(f"• {w}" for w in words) if words else "Список пуст"
        await callback.message.reply(text, parse_mode="MarkdownV2")
    await callback.answer()

@router.callback_query(F.data == "menu_back")
async def menu_back_callback(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    keyboard = await common_chats_keyboard(user_id, bot, for_anon=False)
    if not keyboard.inline_keyboard:
        await callback.message.edit_text("Нет общих чатов")
    else:
        await callback.message.edit_text("Выберите чат:", reply_markup=keyboard)
    await callback.answer()

# ---------- /anonim (полностью реализован здесь) ----------
@router.message(Command("anonim"))
async def anonim_command(message: Message, bot: Bot, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Ошибка: неверный формат сообщения\nИспользуйте: /anonim текст сообщения")
        return
    text = parts[1]
    await state.update_data(anon_text=text)
    keyboard = await common_chats_keyboard(message.from_user.id, bot, for_anon=True)
    if not keyboard.inline_keyboard:
        await message.reply("Нет общих чатов с включённым анонимным режимом")
        await state.clear()
        return
    await message.reply("Выберите чат для анонимного сообщения:", reply_markup=keyboard)
    await state.set_state(AnonStates.waiting_for_chat)

@router.callback_query(AnonStates.waiting_for_chat, F.data.startswith("anon_confirm|"))
async def anon_confirm_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, chat_id = callback.data.split("|")
    user_data = await state.get_data()
    text = user_data.get("anon_text")
    if not text:
        await callback.answer("Ошибка: текст сообщения утерян", show_alert=True)
        await state.clear()
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=f"anon_send|{chat_id}"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="anon_cancel")]
    ])
    await callback.message.edit_text(
        f"**Вы действительно хотите отправить в чат анонимное сообщение?**\n{escape_markdown(text[:200])}",
        parse_mode="MarkdownV2",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data.startswith("anon_send|"))
async def anon_send_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, chat_id = callback.data.split("|")
    user_data = await state.get_data()
    text = user_data.get("anon_text")
    if not text:
        await callback.answer("Ошибка", show_alert=True)
        await state.clear()
        return
    await bot.send_message(int(chat_id), f"**Новое анонимное сообщение**\n{text}", parse_mode="MarkdownV2")
    await callback.message.edit_text("✅ Сообщение отправлено")
    await callback.answer()
    await state.clear()

@router.callback_query(F.data == "anon_cancel")
async def anon_cancel_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отправка отменена")
    await callback.answer()
    await state.clear()

@router.callback_query(F.data.startswith("anon_denied|"))
async def anon_denied(callback: CallbackQuery):
    chat_title = callback.data.split("|")[1]
    await callback.answer(f"Функция недоступна в {chat_title}", show_alert=True)
