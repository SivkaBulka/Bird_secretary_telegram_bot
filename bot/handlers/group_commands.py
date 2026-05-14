import re
import time
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from ..database import get_chat, save_chat, get_default_settings
from ..utils import normalize_text, build_pattern, escape_markdown, get_user_mention
from ..config import RANK_ORDER, RANK_NAMES, RIGHT_OPTIONS, UTC_OFFSETS
from ..filters.chat_type import GroupChatFilter
from ..filters.bot_rights import BotHasRights

router = Router()
router.message.filter(GroupChatFilter(), BotHasRights())  # все команды в группе требуют прав бота

# ---------- Вспомогательные функции для команд ----------
async def get_user_id_by_username(bot: Bot, chat_id: int, username: str):
    try:
        member = await bot.get_chat_member(chat_id, f"@{username}")
        return member.user.id, member.user.username
    except:
        return None, None

def get_user_rank(chat_data: dict, user_id: str) -> str:
    return chat_data.get("users", {}).get(user_id, {}).get("rank", "$")

async def update_creator(bot: Bot, chat_id: str, chat_data: dict):
    """Синхронизирует создателя чата с API"""
    try:
        admins = await bot.get_chat_administrators(int(chat_id))
        api_creator = None
        for admin in admins:
            if admin.status == "creator":
                api_creator = str(admin.user.id)
                break
        if not api_creator:
            return
        users = chat_data.setdefault("users", {})
        # Понижаем старого создателя, если он не совпадает
        for uid, data in users.items():
            if data.get("rank") == "#" and uid != api_creator:
                data["rank"] = "****"
        # Устанавливаем нового создателя
        if api_creator not in users:
            users[api_creator] = {"rank": "#", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0, "last_msg_date": ""}
        else:
            users[api_creator]["rank"] = "#"
    except:
        pass

async def extract_target(message: Message, bot: Bot):
    """Возвращает (user_id, username_or_name, user_rank) из reply или аргумента"""
    chat_id = message.chat.id
    chat_data = await get_chat(str(chat_id))
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        user_id = str(user.id)
        user_name = get_user_mention(user)
        user_rank = get_user_rank(chat_data, user_id)
        return user_id, user_name, user_rank
    args = message.text.split()
    if len(args) < 2:
        return None, None, None
    username = args[1].lstrip('@')
    uid, uname = await get_user_id_by_username(bot, chat_id, username)
    if not uid:
        return None, None, None
    user_name = f"@{uname}" if uname else f"id{uid}"
    user_rank = get_user_rank(chat_data, str(uid))
    return str(uid), user_name, user_rank

def has_rights(caller_rank: str, variant: int) -> bool:
    min_rank, _ = RIGHT_OPTIONS[variant]
    return RANK_ORDER.index(caller_rank) >= RANK_ORDER.index(min_rank)

def can_up(caller_rank: str, target_rank: str, variant: int) -> bool:
    _, limit = RIGHT_OPTIONS[variant]
    caller_idx = RANK_ORDER.index(caller_rank)
    target_idx = RANK_ORDER.index(target_rank)
    if target_idx >= caller_idx - (0 if limit == "мсу" else 1):
        return False
    return True

def can_down(caller_rank: str, target_rank: str) -> bool:
    # Вызывающий должен быть строго выше
    return RANK_ORDER.index(caller_rank) > RANK_ORDER.index(target_rank)

def can_warn(caller_rank: str, target_rank: str) -> bool:
    # Нельзя себе, нельзя выше или равно
    return RANK_ORDER.index(caller_rank) > RANK_ORDER.index(target_rank)

def parse_block_time(time_str: str, tz_offset: int):
    try:
        dt = datetime.strptime(time_str, '%d.%m.%y %H.%M')
        utc_dt = dt - timedelta(hours=tz_offset)
        now_utc = datetime.utcnow()
        if utc_dt <= now_utc:
            return None, "Ошибка: дата в прошлом"
        if (utc_dt - now_utc).total_seconds() < 300:
            return None, "Ошибка: указанный срок менее 5 минут"
        if (utc_dt - now_utc).total_seconds() > 730 * 86400:
            return None, "Ошибка: указанный срок более 730 дней"
        return int(utc_dt.timestamp()), None
    except:
        return None, "Ошибка: синтаксис времени, укажите в формате XX.XX.XX XX.XX"

# ---------- Команды ----------

@router.message(Command("help"))
async def help_command(message: Message):
    short_text = (
        "Список команд\n"
        "/help список команд\n"
        "/user информация о пользователе\n"
        "/chat информация о чате\n"
        "/ranks список администраторов\n"
        "/up повысить\n"
        "/down понизить\n"
        "/warn выдать варн\n"
        "/del_warn удалить варн\n"
        "/del_all_warn удалить все варны\n"
        "/block заблокировать\n"
        "/del_block удалить блокировку\n"
        "/list_word показать ЧС\n"
        "/add_word добавить слова в ЧС\n"
        "/del_word удалить слова из ЧС\n"
        "/setting настройки чата"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Расширенный список", callback_data="help_expand")]
    ])
    await message.reply(short_text, reply_markup=keyboard)

@router.callback_query(F.data == "help_expand")
async def help_expand(callback: CallbackQuery):
    # проверка, что нажал тот же пользователь
    if callback.from_user.id != callback.message.reply_to_message.from_user.id:
        await callback.answer(f"Взаимодействовать может только {callback.message.reply_to_message.from_user.first_name}", show_alert=True)
        return
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    variant = int(chat_data["settings"].get("updown_rights", "1"))
    up_icon = RIGHT_OPTIONS[variant][0]
    list_word_icon = chat_data["settings"].get("list_word_access", "***")
    expanded = (
        "Список команд\n"
        "/help список команд $\n"
        "/user [ник] информация о пользователе $\n"
        "/chat информация о чате $\n"
        "/ranks список администраторов $\n"
        f"/up [ник] повысить {up_icon}\n"
        f"/down [ник] понизить {up_icon}\n"
        "/warn [ник] выдать варн *\n"
        "/del_warn [ник] удалить варн *\n"
        "/del_all_warn [ник] удалить все варны *\n"
        "/block [ник] [время] заблокировать **\n"
        "/del_block [ник] удалить блокировку **\n"
        f"/list_word показать ЧС {list_word_icon}\n"
        "/add_word [текст] добавить слова в ЧС ***\n"
        "/del_word [текст] удалить слова из ЧС ***\n"
        "/setting настройки чата ****\n\n"
        "* значки отображают минимальный ранг для использования"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сокращённый список", callback_data="help_collapse")]
    ])
    await callback.message.edit_text(expanded, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "help_collapse")
async def help_collapse(callback: CallbackQuery):
    if callback.from_user.id != callback.message.reply_to_message.from_user.id:
        await callback.answer(f"Взаимодействовать может только {callback.message.reply_to_message.from_user.first_name}", show_alert=True)
        return
    short_text = (
        "Список команд\n"
        "/help список команд\n"
        "/user информация о пользователе\n"
        "/chat информация о чате\n"
        "/ranks список администраторов\n"
        "/up повысить\n"
        "/down понизить\n"
        "/warn выдать варн\n"
        "/del_warn удалить варн\n"
        "/del_all_warn удалить все варны\n"
        "/block заблокировать\n"
        "/del_block удалить блокировку\n"
        "/list_word показать ЧС\n"
        "/add_word добавить слова в ЧС\n"
        "/del_word удалить слова из ЧС\n"
        "/setting настройки чата"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Расширенный список", callback_data="help_expand")]
    ])
    await callback.message.edit_text(short_text, reply_markup=keyboard)
    await callback.answer()

# Команда /user (сокращённо, остальные команды аналогично – из-за лимита я напишу только ключевые, но для полного кода нужно продолжение. Продолжу следующим сообщением)
# ---------- /user ----------
@router.message(Command("user"))
async def user_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    target_id, target_name, target_rank = await extract_target(message, bot)
    if not target_id:
        await message.reply("Ошибка: пользователь не найден")
        return
    user_data = chat_data.get("users", {}).get(target_id, {})
    rank = user_data.get("rank", "$")
    warns = user_data.get("warns", 0)
    blocked_until = user_data.get("blocked_until")
    msg_total = user_data.get("msg_total", 0)
    msg_30d = user_data.get("msg_last_30d", 0)
    msg_7d = user_data.get("msg_last_7d", 0)
    tz = int(chat_data["settings"].get("timezone", "+3"))
    lines = [f"**Статистика пользователя {escape_markdown(target_name)}**"]
    lines.append(f"• Ранг: {RANK_NAMES.get(rank, 'участник')}")
    if warns:
        lines.append(f"• Всего варнов: {warns}")
    else:
        lines.append("• Варны отсутствуют")
    if blocked_until and blocked_until > time.time():
        local_time = datetime.utcfromtimestamp(blocked_until) + timedelta(hours=tz)
        lines.append(f"• Заблокирован до {local_time.strftime('%d.%m.%y %H:%M')}")
    else:
        lines.append("• Блокировки отсутствуют")
    if msg_total:
        lines.append(f"• Всего сообщений: {msg_total}")
        lines.append(f"• Сообщений за 30 дней: {msg_30d}")
        lines.append(f"• Сообщений за 7 дней: {msg_7d}")
    else:
        lines.append("• Сообщения отсутствуют")
    await message.reply("\n".join(lines), parse_mode="MarkdownV2")

# ---------- /chat ----------
@router.message(Command("chat"))
async def chat_command(message: Message):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
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
    await message.reply("\n".join(lines), parse_mode="MarkdownV2")

# ---------- /ranks ----------
@router.message(Command("ranks"))
async def ranks_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    users = chat_data.get("users", {})
    if not users:
        await message.reply("**Ранги**\n• Пользователи отсутствуют", parse_mode="MarkdownV2")
        return
    rank_lists = {"*": [], "**": [], "***": [], "****": [], "#": []}
    for uid, data in users.items():
        rank = data.get("rank", "$")
        if rank in rank_lists:
            try:
                member = await bot.get_chat_member(int(chat_id), int(uid))
                uname = get_user_mention(member.user)
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
    await message.reply("\n".join(lines), parse_mode="MarkdownV2")

# ---------- /up ----------
@router.message(Command("up"))
async def up_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_data, caller_id)
    variant = int(chat_data["settings"].get("updown_rights", "1"))
    if not has_rights(caller_rank, variant):
        await message.reply("Ошибка: недостаточно прав")
        return
    target_id, target_name, target_rank = await extract_target(message, bot)
    if not target_id:
        await message.reply("Ошибка: пользователь не найден")
        return
    if target_id == caller_id:
        await message.reply("Ошибка: нельзя повысить себя")
        return
    if target_id == str(bot.id):
        await message.reply("Ошибка: нельзя применить команду к боту")
        return
    if target_rank == "#":
        await message.reply("Ошибка: пользователь уже является создателем")
        return
    if not can_up(caller_rank, target_rank, variant):
        await message.reply("Ошибка: недостаточно прав для повышения этого пользователя")
        return
    new_idx = RANK_ORDER.index(target_rank) + 1
    new_rank = RANK_ORDER[new_idx]
    users = chat_data.setdefault("users", {})
    if target_id not in users:
        users[target_id] = {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0}
    users[target_id]["rank"] = new_rank
    await save_chat(chat_id, chat_data)
    await message.reply(f"Пользователь {target_name} повышен до {RANK_NAMES[new_rank]}")

# ---------- /down ----------
@router.message(Command("down"))
async def down_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_data, caller_id)
    variant = int(chat_data["settings"].get("updown_rights", "1"))
    if not has_rights(caller_rank, variant):
        await message.reply("Ошибка: недостаточно прав")
        return
    target_id, target_name, target_rank = await extract_target(message, bot)
    if not target_id:
        await message.reply("Ошибка: пользователь не найден")
        return
    if target_id == str(bot.id):
        await message.reply("Ошибка: нельзя применить команду к боту")
        return
    if target_rank == "$":
        await message.reply("Ошибка: нельзя понизить участника")
        return
    if target_rank == "#":
        await message.reply("Ошибка: нельзя понизить создателя")
        return
    if target_id == caller_id:
        await message.reply("Ошибка: нельзя применить команду к себе")
        return
    if not can_down(caller_rank, target_rank):
        await message.reply("Ошибка: нельзя понизить пользователя с равным или более высоким рангом")
        return
    new_idx = RANK_ORDER.index(target_rank) - 1
    new_rank = RANK_ORDER[new_idx]
    users = chat_data.setdefault("users", {})
    if target_id in users:
        users[target_id]["rank"] = new_rank
    await save_chat(chat_id, chat_data)
    await message.reply(f"Пользователь {target_name} понижен до {RANK_NAMES[new_rank]}")

# ---------- /warn ----------
@router.message(Command("warn"))
async def warn_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_data, caller_id)
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("*"):
        await message.reply("Ошибка: недостаточно прав")
        return
    target_id, target_name, target_rank = await extract_target(message, bot)
    if not target_id:
        await message.reply("Ошибка: пользователь не найден")
        return
    if target_id == caller_id:
        await message.reply("Ошибка: нельзя выдать варн себе")
        return
    if target_id == str(bot.id):
        await message.reply("Ошибка: нельзя выдать варн боту")
        return
    if not can_warn(caller_rank, target_rank):
        await message.reply("Ошибка: нельзя выдать варн пользователю с равным или более высоким рангом")
        return
    users = chat_data.setdefault("users", {})
    if target_id not in users:
        users[target_id] = {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0}
    users[target_id]["warns"] = users[target_id].get("warns", 0) + 1
    await save_chat(chat_id, chat_data)
    await message.reply(f"**Выдан варн {target_name}**\nВсего варнов: {users[target_id]['warns']}", parse_mode="MarkdownV2")

# ---------- /del_warn ----------
@router.message(Command("del_warn"))
async def del_warn_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_data, caller_id)
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("*"):
        await message.reply("Ошибка: недостаточно прав")
        return
    target_id, target_name, target_rank = await extract_target(message, bot)
    if not target_id:
        await message.reply("Ошибка: пользователь не найден")
        return
    if target_id == caller_id:
        await message.reply("Ошибка: нельзя снять варн себе")
        return
    if target_id == str(bot.id):
        await message.reply("Ошибка: нельзя применить команду к боту")
        return
    if not can_warn(caller_rank, target_rank):
        await message.reply("Ошибка: нельзя снять варн пользователю с равным или более высоким рангом")
        return
    users = chat_data.get("users", {})
    if target_id not in users or users[target_id].get("warns", 0) == 0:
        await message.reply("Ошибка: у пользователя отсутствуют варны")
        return
    users[target_id]["warns"] -= 1
    await save_chat(chat_id, chat_data)
    await message.reply(f"**Варн {target_name} отозван**\nВсего варнов: {users[target_id]['warns']}", parse_mode="MarkdownV2")

# ---------- /del_all_warn ----------
@router.message(Command("del_all_warn"))
async def del_all_warn_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_data, caller_id)
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("*"):
        await message.reply("Ошибка: недостаточно прав")
        return
    target_id, target_name, target_rank = await extract_target(message, bot)
    if not target_id:
        await message.reply("Ошибка: пользователь не найден")
        return
    if target_id == caller_id:
        await message.reply("Ошибка: нельзя снять варны себе")
        return
    if target_id == str(bot.id):
        await message.reply("Ошибка: нельзя применить команду к боту")
        return
    if not can_warn(caller_rank, target_rank):
        await message.reply("Ошибка: нельзя снять варны пользователю с равным или более высоким рангом")
        return
    users = chat_data.get("users", {})
    if target_id not in users or users[target_id].get("warns", 0) == 0:
        await message.reply("Ошибка: у пользователя отсутствуют варны")
        return
    users[target_id]["warns"] = 0
    await save_chat(chat_id, chat_data)
    await message.reply(f"**Все варны {target_name} отозваны**", parse_mode="MarkdownV2")
    @router.message(Command("setting"))
async def setting_command(message: Message):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_rank = get_user_rank(chat_data, str(message.from_user.id))
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("****"):
        await message.reply("Ошибка: недостаточно прав")
        return
    # вызов главного меню настроек
    await setting_main(message)  # но setting_main – это колбэк, нужно переделать. Лучше создать функцию show_settings
