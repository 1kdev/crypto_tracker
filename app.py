import asyncio
import datetime
import logging
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from handlers.routes import router
from handlers.ticker_menu import router as ticker_menu_router
from db_main.database import init_db
from services.scheduler import run_scheduler


#Логгинг
logging.basicConfig(level=logging.INFO)
#Подгрузка секрета из env
load_dotenv()
#Секретный ключ
TOKEN = getenv("BOT_TOKEN")
#Диспетчер
dp = Dispatcher()
#Роутеры: ticker_menu (новое inline-меню) регистрируется ПЕРВЫМ, т.к. в routes.py
#есть catch-all хэндлер @router.message(), который иначе перехватит все апдейты
dp.include_router(ticker_menu_router)
dp.include_router(router)


#Запуск процесса поллинга новых апдейтов
async def main():
    #Создаём таблицы / прогоняем миграцию колонок перед стартом
    await init_db()

    bot = Bot(token=TOKEN)

    #Централизованный background-планировщик уведомлений (один таск, не один на юзера/тикер)
    scheduler_task = asyncio.create_task(run_scheduler(bot))

    try:
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass



if __name__ == "__main__":
    asyncio.run(main())