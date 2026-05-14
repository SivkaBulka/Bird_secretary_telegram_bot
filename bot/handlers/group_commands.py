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
