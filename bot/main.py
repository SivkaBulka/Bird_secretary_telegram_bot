# bot/main.py
import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
# В самом верху после других импортов
from .handlers import events

from .config import BOT_TOKEN
from .handlers import group_commands, private_commands, callbacks, message_filter
from .middlewares.error_handler import ErrorHandlerMiddleware
# После регистрации остальных роутеров
dp.include_router(events.router)

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2))
dp = Dispatcher(storage=MemoryStorage())

# Подключаем middleware для глобальной обработки ошибок
dp.message.middleware(ErrorHandlerMiddleware())
dp.callback_query.middleware(ErrorHandlerMiddleware())

# Подключаем роутеры хендлеров
dp.include_router(group_commands.router)
dp.include_router(private_commands.router)
dp.include_router(callbacks.router)
dp.include_router(message_filter.router)

# Веб-сервер для пинга (aiohttp)
async def handle_ping(request):
    return web.Response(text="OK")

async def handle_home(request):
    return web.Response(text="Bot is running.")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/ping', handle_ping)
    app.router.add_get('/', handle_home)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 5000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")
    # бесконечное ожидание
    await asyncio.Event().wait()

async def main():
    # Запускаем веб-сервер в отдельной задаче
    web_task = asyncio.create_task(start_web_server())
    # Запускаем бота (поллинг)
    await dp.start_polling(bot)
    await web_task

if __name__ == "__main__":
    asyncio.run(main())
