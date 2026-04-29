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

async def add_ticker_to_db(telegram_id: int, ticker_symbol: str) -> tuple[bool, str]:
    '''
    Добавляет тикер юзера.
    Аргументы: 
        telegram_id - айди юзера
        ticker_symbol - сырая строка от юзера (например 'BTC USD') 
    Возвращает: (Успех: bool, Сообщение: str)
    '''
    #Нормализация формата тикера в верхний регистр
    clean_ticker = ticker_symbol.upper().replace(" ", "")
    
    base = ""
    quote = ""

    #Логика разделения
    if "/" in clean_ticker:
        #Вариант 1: юзер ввел BTC/USDT
        parts = clean_ticker.split("/")
        if len(parts) == 2 and parts[1] == "USDT":
            base = parts[0]
            quote = "USDT"
        else:
            return False, "Ошибка: поддерживаются только пары с USDT (например, BTC/USDT)"
    else:
        #Вариант 2: юзер ввел BTCUSDT
        if clean_ticker.endswith("USDT"):
            base = clean_ticker[:-4] #Всё, что до последних 4х букв
            quote = "USDT"
        else:
            return False, "Ошибка: поддерживаются пары только с USDT (например, BTCUSDT)"
    
    #формируем итоговую строку: BTCUSDT
    final_ticker = f"{base}{quote}"
    
    #Проверка на дубликаты + внос в базу
    async with aiosqlite.connect("telegram.db") as db:
        cursor = await db.cursor()
        #Проверка на дубликат
        await cursor.execute(
            "SELECT id FROM user_tickers WHERE user_id = ? and user_symbol = ?",
            (telegram_id, final_ticker)
        )
        exists = await cursor.fetchone()
        if exists:
            return False, f"Тикер {final_ticker} уже есть в вашем списке!"
        
        #Вставка нового тикера
        try:
            await db.execute(
                "INSERT INTO user_tickers (user_id, user_symbol) VALUES (?, ?)",
                (telegram_id, final_ticker)
                )
            await db.commit()
            return True, f"✅Тикер {final_ticker} успешно добавлен!"
        except Exception as e:
            return False, f"Ошибка базы данных: {str(e)}"