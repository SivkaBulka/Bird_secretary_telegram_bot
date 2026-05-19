from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated
from ..database import delete_chat, delete_user

router = Router()

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    if event.new_chat_member.status in ("left", "kicked"):
        await delete_chat(str(event.chat.id))

@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated, bot: Bot):
    if event.new_chat_member.status in ("left", "kicked"):
        user_id = str(event.new_chat_member.user.id)
        if user_id != str(bot.id):
            await delete_user(str(event.chat.id), user_id)
