# bot/handlers/events.py
from aiogram import Router, Bot, F
from aiogram.types import ChatMemberUpdated
from ..database import delete_chat, delete_user

router = Router()

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    """Бот удалён из чата -> удаляем все данные чата"""
    if event.new_chat_member.status in ("left", "kicked"):
        chat_id = str(event.chat.id)
        await delete_chat(chat_id)

@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated, bot: Bot):
    """Участник покинул чат -> удаляем его данные"""
    if event.new_chat_member.status in ("left", "kicked"):
        chat_id = str(event.chat.id)
        user_id = str(event.new_chat_member.user.id)
        # Удаляем только если это не сам бот
        if user_id != str(bot.id):
            await delete_user(chat_id, user_id)
