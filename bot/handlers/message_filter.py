# bot/handlers/message_filter.py
import re
import time
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from ..database import get_chat, save_chat, delete_user
from ..config import get_default_settings
from ..utils import normalize_text, build_pattern, escape_markdown
from ..config import RANK_ORDER

router = Router()

# Этот хендлер будет срабатывать на любое сообщение в группах
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def message_counter_and_filter(message: Message, bot: Bot):
    chat_id = str(message.chat.id)
    user_id = str(message.from_user.id)
    
    # Загружаем данные чата
    chat_data = await get_chat(chat_id)
    settings = chat_data.get("settings", get_default_settings())
    
    # Обновляем создателя чата (синхронизация)
    await update_creator(bot, chat_id, chat_data)
    
    # Инициализация чата, если первый раз
    if not chat_data.get("init"):
        chat_data["init"] = True
        await save_chat(chat_id, chat_data)
        # Проверяем права бота перед отправкой приветствия
        try:
            bot_member = await bot.get_chat_member(message.chat.id, bot.id)
            if bot_member.status in ("administrator", "creator") and bot_member.can_restrict_members and bot_member.can_delete_messages:
                await message.answer(
                    "**Бот готов к работе!**\n"
                    "Для поиска команд используйте /help\n"
                    "Для настройки чата используйте /setting\n"
                    "Используйте /up чтобы назначить админов",
                    parse_mode="MarkdownV2"
                )
            else:
                await message.answer("Ошибка: у бота недостаточно прав для работы")
        except:
            pass
        return
    
    # Обновляем счётчики сообщений пользователя
    users = chat_data.setdefault("users", {})
    if user_id not in users:
        users[user_id] = {
            "rank": "$",
            "warns": 0,
            "blocked_until": None,
            "msg_total": 0,
            "msg_last_30d": 0,
            "msg_last_7d": 0,
            "last_msg_date": ""
        }
    user = users[user_id]
    user["msg_total"] = user.get("msg_total", 0) + 1
    now = datetime.utcnow()
    last_date_str = user.get("last_msg_date", "")
    if last_date_str:
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
        if (now - last_date).days >= 30:
            user["msg_last_30d"] = 0
        if (now - last_date).days >= 7:
            user["msg_last_7d"] = 0
    user["msg_last_30d"] = user.get("msg_last_30d", 0) + 1
    user["msg_last_7d"] = user.get("msg_last_7d", 0) + 1
    user["last_msg_date"] = now.strftime("%Y-%m-%d")
    await save_chat(chat_id, chat_data)
    
    # Фильтр слов
    filter_mode = settings.get("filter_mode", "off")
    if filter_mode == "off" or not message.text:
        return
    
    words = chat_data.get("words", [])
    if not words:
        return
    
    text_to_check = normalize_text(message.text)
    search_mode = settings.get("search_mode", "substring")
    found_words = []
    for word in words:
        if search_mode == "substring":
            pattern = build_pattern(word)
            if re.search(pattern, text_to_check):
                found_words.append(word)
        else:
            pattern = r'\b' + build_pattern(word) + r'\b'
            if re.search(pattern, text_to_check):
                found_words.append(word)
    
    if not found_words:
        return
    
    # Ограничиваем количество найденных слов для вывода
    unique_found = list(set(found_words))
    word_count = len(unique_found)
    
    # Выдаём варн (один, независимо от количества слов)
    if filter_mode in ("only_warn", "del_warn"):
        user["warns"] = user.get("warns", 0) + 1
        await save_chat(chat_id, chat_data)
    
    # Удаляем сообщение, если нужно
    if filter_mode in ("only_del", "del_warn"):
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
    
    # Формируем ответ пользователю
    user_name = escape_markdown(message.from_user.first_name)
    if filter_mode in ("only_del", "del_warn"):
        response = f"**{user_name} получает варн, в его сообщении {word_count} запрещённых слов**\nВсего варнов: {user['warns']}"
    else:  # only_warn
        if word_count <= 16:
            words_list = "\n".join(escape_markdown(w) for w in unique_found)
            response = f"**{user_name} получает варн, в его сообщении были запрещённые слова:**\n{words_list}\nВсего варнов: {user['warns']}"
        else:
            first_16 = "\n".join(escape_markdown(w) for w in unique_found[:16])
            remaining = word_count - 16
            response = f"**{user_name} получает варн, в его сообщении были запрещённые слова:**\n{first_16}\nи ещё {remaining} запрещённых слов\nВсего варнов: {user['warns']}"
    
    await message.reply(response, parse_mode="MarkdownV2")

async def update_creator(bot: Bot, chat_id: str, chat_data: dict):
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
