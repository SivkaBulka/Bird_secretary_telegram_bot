from aiogram import Bot
from aiogram.filters import Filter
from aiogram.types import Message

class BotHasRights(Filter):
    """Проверяет, есть ли у бота права администратора с возможностью удалять/ограничивать"""
    async def __call__(self, message: Message, bot: Bot) -> bool:
        try:
            bot_member = await bot.get_chat_member(message.chat.id, bot.id)
            if bot_member.status not in ("administrator", "creator"):
                return False
            return (bot_member.can_restrict_members and
                    bot_member.can_delete_messages)
        except:
            return False
