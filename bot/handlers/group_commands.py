# bot/handlers/group_commands.py
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

# ---------- Вспомогательные функции ----------
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
        for uid, data in users.items():
            if data.get("rank") == "#" and uid != api_creator:
                data["rank"] = "****"
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
    if limit == "мунс":
        # максимум на один ниже своего
        return target_idx < caller_idx - 1
    else:  # мсу
        # максимум свой уровень (можно повысить до своего ранга, но не выше)
        return target_idx < caller_idx

def can_down(caller_rank: str, target_rank: str) -> bool:
    return RANK_ORDER.index(caller_rank) > RANK_ORDER.index(target_rank)

def can_warn(caller_rank: str, target_rank: str) -> bool:
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

# ---------- /help ----------
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

# ---------- /block ----------
@router.message(Command("block"))
async def block_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_data, caller_id)
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("**"):
        await message.reply("Ошибка: недостаточно прав")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Ошибка: неверный формат сообщения\nПример: /block @username 31.12.25 23.59")
        return
    target_username = args[1].lstrip('@')
    time_str = args[2]
    try:
        member = await bot.get_chat_member(message.chat.id, f"@{target_username}")
        target_id = str(member.user.id)
        target_name = get_user_mention(member.user)
    except:
        await message.reply("Ошибка: пользователь не найден")
        return
    if target_id == caller_id:
        await message.reply("Ошибка: нельзя заблокировать себя")
        return
    if target_id == str(bot.id):
        await message.reply("Ошибка: нельзя заблокировать бота")
        return
    tz = int(chat_data["settings"].get("timezone", "+3"))
    timestamp, error = parse_block_time(time_str, tz)
    if error:
        await message.reply(error)
        return
    try:
        await bot.restrict_chat_member(
            message.chat.id, int(target_id),
            until_date=timestamp,
            can_send_messages=False
        )
    except Exception:
        await message.reply("Ошибка: у бота недостаточно прав")
        return
    users = chat_data.setdefault("users", {})
    if target_id not in users:
        users[target_id] = {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0}
    old_block = users[target_id].get("blocked_until")
    users[target_id]["blocked_until"] = timestamp
    await save_chat(chat_id, chat_data)
    local_dt = datetime.utcfromtimestamp(timestamp) + timedelta(hours=tz)
    time_str_formatted = local_dt.strftime('%d.%m.%y %H:%M')
    if old_block and old_block > time.time():
        old_local = datetime.utcfromtimestamp(old_block) + timedelta(hours=tz)
        old_str = old_local.strftime('%d.%m.%y %H:%M')
        await message.reply(f"**Время блокировки {target_name} обновлено с {old_str} до {time_str_formatted}**", parse_mode="MarkdownV2")
    else:
        await message.reply(f"**{target_name} выдана блокировка до {time_str_formatted}**", parse_mode="MarkdownV2")

# ---------- /del_block ----------
@router.message(Command("del_block"))
async def del_block_command(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_data, caller_id)
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("**"):
        await message.reply("Ошибка: недостаточно прав")
        return
    if message.reply_to_message:
        target_id = str(message.reply_to_message.from_user.id)
        target_name = get_user_mention(message.reply_to_message.from_user)
    else:
        args = message.text.split()
        if len(args) < 2:
            await message.reply("Ошибка: укажите пользователя (reply или @ник)")
            return
        username = args[1].lstrip('@')
        try:
            member = await bot.get_chat_member(message.chat.id, f"@{username}")
            target_id = str(member.user.id)
            target_name = get_user_mention(member.user)
        except:
            await message.reply("Ошибка: пользователь не найден")
            return
    if target_id == caller_id:
        await message.reply("Ошибка: нельзя применить команду к себе")
        return
    if target_id == str(bot.id):
        await message.reply("Ошибка: нельзя применить команду к боту")
        return
    users = chat_data.get("users", {})
    if target_id not in users or not users[target_id].get("blocked_until") or users[target_id]["blocked_until"] <= time.time():
        await message.reply("Ошибка: пользователь не заблокирован")
        return
    try:
        await bot.restrict_chat_member(
            message.chat.id, int(target_id),
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
    except Exception:
        await message.reply("Ошибка: у бота недостаточно прав")
        return
    users[target_id]["blocked_until"] = None
    await save_chat(chat_id, chat_data)
    await message.reply(f"**Блокировка {target_name} снята**", parse_mode="MarkdownV2")

# ---------- /list_word (команда отправляет первую страницу) ----------
@router.message(Command("list_word"))
async def list_word_command(message: Message):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    settings = chat_data["settings"]
    access = settings.get("list_word_access", "***")
    caller_rank = get_user_rank(chat_data, str(message.from_user.id))
    if access != "$" and RANK_ORDER.index(caller_rank) < RANK_ORDER.index("***"):
        await message.reply("Ошибка: недостаточно прав")
        return
    words = chat_data.get("words", [])
    if not words:
        await message.reply("**Чёрный список слов пуст**", parse_mode="MarkdownV2")
        return
    # Вызываем функцию показа первой страницы (определена в callbacks, но для избежания циклического импорта
    # просто реализуем здесь локальную функцию)
    await show_list_word_page(message, chat_id, 1)

async def show_list_word_page(target, chat_id: str, page: int):
    """Отправляет или редактирует сообщение со страницей чёрного списка (дубль из callbacks)"""
    chat_data = await get_chat(chat_id)
    words = chat_data.get("words", [])
    items_per_page = 32
    total_pages = max(1, (len(words) + items_per_page - 1) // items_per_page) if words else 1
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * items_per_page
    end = start + items_per_page
    page_words = words[start:end]
    text = f"**Чёрный список слов, страница {page}/{total_pages}:**\n"
    if page_words:
        text += "\n".join(f"• {w}" for w in page_words)
    else:
        text += "• Список пуст"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="<", callback_data=f"listword_page|{chat_id}|{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text=">", callback_data=f"listword_page|{chat_id}|{page+1}"))
        if nav_buttons:
            keyboard.inline_keyboard.append(nav_buttons)
    if hasattr(target, 'edit_text'):
        await target.edit_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)
    else:
        await target.reply(text, parse_mode="MarkdownV2", reply_markup=keyboard)

# ---------- /add_word ----------
@router.message(Command("add_word"))
async def add_word_command(message: Message):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_rank = get_user_rank(chat_data, str(message.from_user.id))
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("***"):
        await message.reply("Ошибка: недостаточно прав")
        return
    lines = message.text.split('\n', 1)
    if len(lines) < 2 or not lines[1].strip():
        await message.reply("Ошибка: неверный формат сообщения\nВведите слова после команды на новой строке, каждое с новой строки")
        return
    new_words_raw = lines[1].strip().split('\n')
    words_list = chat_data.setdefault("words", [])
    added = []
    not_added = []
    for raw in new_words_raw:
        raw = raw.strip()
        if not raw:
            continue
        normalized = normalize_text(raw)
        if normalized in words_list:
            not_added.append(raw)
        else:
            words_list.append(normalized)
            added.append(raw)
    await save_chat(chat_id, chat_data)
    response = ""
    if added:
        response += "**Успешно добавлено:**\n" + "\n".join(added) + "\n"
    if not_added:
        response += "**Уже есть в списке:**\n" + "\n".join(not_added)
    if not response:
        response = "Ошибка: неверный формат"
    await message.reply(response, parse_mode="MarkdownV2")

# ---------- /del_word ----------
@router.message(Command("del_word"))
async def del_word_command(message: Message):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_rank = get_user_rank(chat_data, str(message.from_user.id))
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("***"):
        await message.reply("Ошибка: недостаточно прав")
        return
    lines = message.text.split('\n', 1)
    if len(lines) < 2 or not lines[1].strip():
        await message.reply("Ошибка: неверный формат сообщения\nВведите слова после команды на новой строке")
        return
    del_words_raw = lines[1].strip().split('\n')
    words_list = chat_data.get("words", [])
    deleted = []
    not_found = []
    for raw in del_words_raw:
        raw = raw.strip()
        if not raw:
            continue
        normalized = normalize_text(raw)
        if normalized in words_list:
            words_list.remove(normalized)
            deleted.append(raw)
        else:
            not_found.append(raw)
    await save_chat(chat_id, chat_data)
    response = ""
    if deleted:
        response += "**Удалено:**\n" + "\n".join(deleted) + "\n"
    if not_found:
        response += "**Не найдено в списке:**\n" + "\n".join(not_found)
    if not response:
        response = "Ошибка: неверный формат"
    await message.reply(response, parse_mode="MarkdownV2")

# ---------- /setting ----------
@router.message(Command("setting"))
async def setting_command(message: Message):
    chat_id = str(message.chat.id)
    chat_data = await get_chat(chat_id)
    caller_rank = get_user_rank(chat_data, str(message.from_user.id))
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index("****"):
        await message.reply("Ошибка: недостаточно прав")
        return
    # Вызываем главное меню настроек (функция из callbacks)
    from ..callbacks import setting_main
    class FakeCallback:
        def __init__(self, message):
            self.message = message
            self.from_user = message.from_user
        async def answer(self, text=None, show_alert=False):
            pass
    fake = FakeCallback(message)
    await setting_main(fake)
