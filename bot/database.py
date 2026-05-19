import json
import os
import asyncio
from typing import Dict, Any
from .config import DATA_FILE, get_default_settings

_lock = asyncio.Lock()

async def load_data() -> Dict[str, Any]:
    async with _lock:
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

async def save_data(data: Dict[str, Any]) -> None:
    async with _lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

async def get_chat(chat_id: str) -> Dict[str, Any]:
    data = await load_data()
    if chat_id not in data:
        data[chat_id] = {
            "settings": get_default_settings(),
            "words": [],
            "users": {},
            "init": False
        }
        await save_data(data)
    chat = data[chat_id]
    # гарантия наличия ключей
    chat.setdefault("settings", get_default_settings())
    chat.setdefault("words", [])
    chat.setdefault("users", {})
    chat.setdefault("init", False)
    return chat

async def save_chat(chat_id: str, chat_data: Dict[str, Any]) -> None:
    data = await load_data()
    data[chat_id] = chat_data
    await save_data(data)

async def delete_chat(chat_id: str) -> None:
    data = await load_data()
    if chat_id in data:
        del data[chat_id]
        await save_data(data)

async def delete_user(chat_id: str, user_id: str) -> None:
    chat_data = await get_chat(chat_id)
    if "users" in chat_data and user_id in chat_data["users"]:
        del chat_data["users"][user_id]
        await save_chat(chat_id, chat_data)
