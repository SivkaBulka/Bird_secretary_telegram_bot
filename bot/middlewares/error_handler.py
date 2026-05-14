from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable

class ErrorHandlerMiddleware(BaseMiddleware):
    """Глобальный перехват ошибок – если что-то пошло не так, отвечаем 'Ошибка: ошибка'"""
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as e:
            print(f"Unhandled error: {e}")
            if isinstance(event, Message):
                await event.answer("Ошибка: ошибка")
            elif isinstance(event, CallbackQuery):
                await event.answer("Ошибка: ошибка", show_alert=True)
            return
