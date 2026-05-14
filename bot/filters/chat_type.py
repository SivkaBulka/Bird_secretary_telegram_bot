from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery

class GroupChatFilter(Filter):
    """Разрешает только групповые чаты (включая супергруппы)"""
    async def __call__(self, message: Message) -> bool:
        return message.chat.type in ("group", "supergroup")

class PrivateChatFilter(Filter):
    """Разрешает только личные сообщения"""
    async def __call__(self, message: Message) -> bool:
        return message.chat.type == "private"

class GroupChatCallbackFilter(Filter):
    """Для колбэков: проверяет, что сообщение из группы"""
    async def __call__(self, callback: CallbackQuery) -> bool:
        return callback.message.chat.type in ("group", "supergroup")
