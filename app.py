import asyncio
import datetime
import logging
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from handlers.routes import router


#Логгинг
logging.basicConfig(level=logging.INFO)
#Подгрузка секрета из env
load_dotenv()
#Секретный ключ
TOKEN = getenv("BOT_TOKEN")
#Диспетчер
dp = Dispatcher()
#роутер
dp.include_router(router)

#Запуск процесса поллинга новых апдейтов
async def main():
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)



if __name__ == "__main__":
    asyncio.run(main())