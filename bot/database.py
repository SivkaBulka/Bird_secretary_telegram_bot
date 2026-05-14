import json
import os
import asyncio
from typing import Dict, Any, Optional
from .config import DATA_FILE, RANK_ORDER, RANK_NAMES

# блокировка для конкурентного доступа к файлу
_lock = asyncio.Lock()

def get_default_settings() -> Dict[str, str]:
    return {
        "updown_rights": "1",
        "list_word_access": "***",
        "filter_mode": "off",
        "timezone": "+3",
        "search_mode": "substring",
        "anonymous": "off"
    }

async def load_data() -> Dict[str, Any]:
    """Асинхронно загружает данные из JSON"""
    async with _lock:
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

async def save_data(data: Dict[str, Any]) -> None:
    """Асинхронно сохраняет данные в JSON"""
    async with _lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

async def get_chat(chat_id: str) -> Dict[str, Any]:
    """Возвращает данные чата с инициализацией по умолчанию"""
    data = await load_data()
    if chat_id not in data:
        data[chat_id] = {
            "settings": get_default_settings(),
            "words": [],
            "users": {},
            "init": False
        }
        await save_data(data)
    return data[chat_id]

async def save_chat(chat_id: str, chat_data: Dict[str, Any]) -> None:
    """Сохраняет данные конкретного чата"""
    data = await load_data()
    data[chat_id] = chat_data
    await save_data(data)

async def delete_chat(chat_id: str) -> None:
    """Удаляет все данные чата (при выходе бота)"""
    data = await load_data()
    if chat_id in data:
        del data[chat_id]
        await save_data(data)

async def delete_user(chat_id: str, user_id: str) -> None:
    """Удаляет пользователя из чата (при его выходе)"""
    chat_data = await get_chat(chat_id)
    if "users" in chat_data and user_id in chat_data["users"]:
        del chat_data["users"][user_id]
        await save_chat(chat_id, chat_data)
