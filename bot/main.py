import asyncio
import os
import sys
import traceback
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import BOT_TOKEN
from .handlers import group_commands, private_commands, callbacks, message_filter, events
from .middlewares.error_handler import ErrorHandlerMiddleware

print("Starting bot...")
print("Python version:", sys.version)

if not BOT_TOKEN:
    print("FATAL: BOT_TOKEN not set")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

dp.message.middleware(ErrorHandlerMiddleware())
dp.callback_query.middleware(ErrorHandlerMiddleware())

dp.include_router(group_commands.router)
dp.include_router(private_commands.router)
dp.include_router(callbacks.router)
dp.include_router(message_filter.router)
dp.include_router(events.router)

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
    await asyncio.Event().wait()

async def main():
    web_task = asyncio.create_task(start_web_server())
    await dp.start_polling(bot)
    await web_task

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print("FATAL ERROR:")
        traceback.print_exc()
        sys.exit(1)
