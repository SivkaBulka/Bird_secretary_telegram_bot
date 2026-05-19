import time
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ..database import get_chat, save_chat, get_default_settings
from ..utils import escape_markdown
from ..config import RANK_ORDER, RIGHT_OPTIONS, UTC_OFFSETS

router = Router()

# ---------- НАСТРОЙКИ (/setting) ----------
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

# ---------- Пагинация для /list_word ----------
async def show_list_word_page(target, chat_id: str, page: int):
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

@router.callback_query(F.data.startswith("listword_page|"))
async def listword_page_callback(callback: CallbackQuery):
    _, chat_id, page_str = callback.data.split("|")
    page = int(page_str)
    chat_data = await get_chat(chat_id)
    settings = chat_data["settings"]
    access = settings.get("list_word_access", "***")
    caller_rank = chat_data.get("users", {}).get(str(callback.from_user.id), {}).get("rank", "$")
    if access != "$" and RANK_ORDER.index(caller_rank) < RANK_ORDER.index("***"):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await show_list_word_page(callback.message, chat_id, page)
    await callback.answer()
