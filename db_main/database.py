import datetime
import aiosqlite


async def add_to_db(telegram_id, username):
    async with aiosqlite.connect("telegram.db") as db:
        #Создание основной БД
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
                         telegram_id BIGINT,
                         username TEXT,
                         date TEXT,
                         delay_time INTEGER DEFAULT 3600 
                         )""") 
        #Создание tickers БД
        await db.execute("""CREATE TABLE IF NOT EXISTS user_tickers(
                         id INTEGER PRIMARY KEY,
                         user_id BIGINT,
                         user_symbol TEXT,
                         last_notifed_price
                         )""")
        #Проверка регистрации
        cursor = await db.execute("SELECT *FROM users WHERE telegram_id = ?", (telegram_id,)) 
        data = await cursor.fetchone()
        await cursor.close()
        if data is not None:
            return
        #Определение даты регистрации
        date = f'{datetime.date.today()}' 
        #Внесение данных о юзере
        await db.execute("INSERT INTO users (telegram_id, username, date) VALUES (?, ?, ?)", 
                          (telegram_id, username, date))
        await db.commit()

