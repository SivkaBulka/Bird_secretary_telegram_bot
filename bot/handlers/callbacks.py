# bot/handlers/callbacks.py
import time
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from ..database import get_chat, save_chat, get_default_settings
from ..utils import escape_markdown
from ..config import RANK_ORDER, RIGHT_OPTIONS, UTC_OFFSETS
from .private_commands import common_chats_keyboard  # импорт для /menu и /anonim

router = Router()

# ---------- НАСТРОЙКИ (/setting) ----------
@router.callback_query(F.data == "setting_main")
async def setting_main(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    settings = chat_data["settings"]
    list_word_access = settings.get("list_word_access", "***")
    search_mode = "подстрока" if settings.get("search_mode") == "substring" else "точное совпадение"
    anon = "Вкл" if settings.get("anonymous") == "on" else "Выкл"
    filter_mode = settings.get("filter_mode", "off")
    filter_text = {"off": "Off", "only_del": "Only Del", "only_warn": "Only Warn", "del_warn": "Del & Warn"}.get(filter_mode, "Off")
    tz = settings.get("timezone", "+3")
    text = "**Настройки чата**"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Доступ /list_word {'$' if list_word_access == '$' else '***'}", callback_data="set_toggle_listword")],
        [InlineKeyboardButton(text=f"Фильтр: {search_mode}", callback_data="set_toggle_search")],
        [InlineKeyboardButton(text=f"Анонимный режим: {anon}", callback_data="set_toggle_anon")],
        [InlineKeyboardButton(text="Права /up и /down", callback_data="set_rights_menu")],
        [InlineKeyboardButton(text=f"Часовой пояс UTC{tz}", callback_data="set_tz_menu")],
        [InlineKeyboardButton(text="Режим фильтра", callback_data="set_filter_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "set_toggle_listword")
async def set_toggle_listword(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    current = chat_data["settings"].get("list_word_access", "***")
    new_val = "$" if current != "$" else "***"
    chat_data["settings"]["list_word_access"] = new_val
    await save_chat(chat_id, chat_data)
    await callback.answer(f"Доступ /list_word {'для всех' if new_val == '$' else 'ограничен'}")
    await setting_main(callback)

@router.callback_query(F.data == "set_toggle_search")
async def set_toggle_search(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    current = chat_data["settings"].get("search_mode", "substring")
    new_val = "exact" if current == "substring" else "substring"
    chat_data["settings"]["search_mode"] = new_val
    await save_chat(chat_id, chat_data)
    await callback.answer(f"Режим фильтра: {'подстрока' if new_val == 'substring' else 'точное совпадение'}")
    await setting_main(callback)

@router.callback_query(F.data == "set_toggle_anon")
async def set_toggle_anon(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    current = chat_data["settings"].get("anonymous", "off")
    new_val = "on" if current == "off" else "off"
    chat_data["settings"]["anonymous"] = new_val
    await save_chat(chat_id, chat_data)
    await callback.answer(f"Анонимный режим {'включён' if new_val == 'on' else 'выключен'}")
    await setting_main(callback)

@router.callback_query(F.data == "set_rights_menu")
async def set_rights_menu(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    variant = int(chat_data["settings"].get("updown_rights", "1"))
    buttons = []
    for i in range(1, 9):
        label = str(i)
        if i == variant:
            label = "🔴 " + label
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"set_rights_set|{i}"))
    # разбиваем на строки по 2 кнопки
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="setting_main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text("Выберите вариант прав для /up и /down:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("set_rights_set|"))
async def set_rights_set(callback: CallbackQuery):
    _, variant_str = callback.data.split("|")
    variant = int(variant_str)
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    chat_data["settings"]["updown_rights"] = str(variant)
    await save_chat(chat_id, chat_data)
    await callback.answer(f"Вариант {variant} установлен")
    await setting_main(callback)

@router.callback_query(F.data == "set_tz_menu")
async def set_tz_menu(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    current = chat_data["settings"].get("timezone", "+3")
    buttons = []
    for tz in UTC_OFFSETS:
        label = f"UTC{tz}"
        if tz == current.replace("UTC", "").replace("+", ""):
            label = "🔴 " + label
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"set_tz_set|{tz}"))
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="setting_main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text("Выберите часовой пояс:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("set_tz_set|"))
async def set_tz_set(callback: CallbackQuery):
    _, tz = callback.data.split("|")
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    chat_data["settings"]["timezone"] = f"+{tz}" if not tz.startswith('-') else tz
    await save_chat(chat_id, chat_data)
    await callback.answer(f"Часовой пояс UTC{tz} установлен")
    await setting_main(callback)

@router.callback_query(F.data == "set_filter_menu")
async def set_filter_menu(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    current = chat_data["settings"].get("filter_mode", "off")
    filters = [("off", "Off"), ("del_warn", "Del & Warn"), ("only_del", "Only Del"), ("only_warn", "Only Warn")]
    buttons = []
    for f_val, f_text in filters:
        label = f_text
        if f_val == current:
            label = "🔴 " + label
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"set_filter_set|{f_val}"))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="setting_main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text("Выберите режим фильтра:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("set_filter_set|"))
async def set_filter_set(callback: CallbackQuery):
    _, f_val = callback.data.split("|")
    chat_id = str(callback.message.chat.id)
    chat_data = await get_chat(chat_id)
    if chat_data["settings"].get("filter_mode") == f_val:
        await callback.answer("Режим уже выбран", show_alert=True)
        return
    chat_data["settings"]["filter_mode"] = f_val
    await save_chat(chat_id, chat_data)
    filter_text = {"off": "Off", "del_warn": "Del & Warn", "only_del": "Only Del", "only_warn": "Only Warn"}[f_val]
    await callback.answer(f"Режим {filter_text} установлен")
    await setting_main(callback)
