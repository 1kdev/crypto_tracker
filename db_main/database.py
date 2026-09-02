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


def normalize_ticker(ticker_symbol: str) -> tuple[bool, str]:
    '''
    Разбирает сырую строку от юзера (например 'BTC/USDT' или 'btcusdt')
    и приводит её к формату биржи (например 'BTCUSDT').
    Аргументы:
        ticker_symbol - сырая строка от юзера
    Возвращает: (Успех: bool, Итоговый тикер или текст ошибки: str)
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

    if not base:
        return False, "Ошибка: не удалось распознать тикер"

    #формируем итоговую строку: BTCUSDT
    return True, f"{base}{quote}"


async def add_ticker_to_db(telegram_id: int, ticker_symbol: str) -> tuple[bool, str]:
    '''
    Добавляет тикер юзера.
    Аргументы: 
        telegram_id - айди юзера
        ticker_symbol - сырая строка от юзера (например 'BTC USD') 
    Возвращает: (Успех: bool, Сообщение: str)
    '''
    ok, result = normalize_ticker(ticker_symbol)
    if not ok:
        #result в этом случае содержит текст ошибки
        return False, result

    final_ticker = result

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
            return True, f"✅ Тикер {final_ticker} успешно добавлен!"
        except Exception as e:
            return False, f"Ошибка базы данных: {str(e)}"

async def get_user_ticker(telegram_id: int) -> list:
    '''
    Получает список всех тикеров для конкретного юзера
    Возвращает список строк типа ['BTCUSDT', 'ETHUSDT']
    При пустом списке []
    '''
    async with aiosqlite.connect("telegram.db") as db:
        cursor = await db.cursor()
        
        #Выбираем только колонку user_symbol, где user_id совпадает
        await cursor.execute(
            "SELECT user_symbol FROM user_tickers WHERE user_id = ?",
            (telegram_id,)
        )
        
        #fetchall() возвращает список кортежей типа [(BTCUSDT,), (ETHUSDT,)]
        rows = await cursor.fetchall()
        
        #Превращаем список кортежей в простой список строк типа [BTCUSDT, ETHUSDT]
        #row[0] берет первый элемент кортежа
        #Важно: список должен быть материализован (не генератор!),
        #иначе проверка "if not tickers" в хендлере всегда будет False
        return [row[0] for row in rows]


async def get_user_tickers_full(telegram_id: int) -> list[tuple[int, str]]:
    '''
    Получает список тикеров юзера вместе с их id в таблице user_tickers.
    Нужно, чтобы построить инлайн-клавиатуру удаления с правильным callback_data.
    Возвращает список кортежей типа [(1, 'BTCUSDT'), (2, 'ETHUSDT')]
    '''
    async with aiosqlite.connect("telegram.db") as db:
        cursor = await db.cursor()

        await cursor.execute(
            "SELECT id, user_symbol FROM user_tickers WHERE user_id = ?",
            (telegram_id,)
        )

        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]


async def delete_ticker_from_db(telegram_id: int, ticker_id: int) -> tuple[bool, str]:
    '''
    Удаляет тикер юзера по его id в таблице user_tickers.
    Дополнительно проверяет, что тикер принадлежит именно этому юзеру,
    чтобы один пользователь не мог удалить чужой тикер, подставив id.
    Аргументы:
        telegram_id - айди юзера
        ticker_id - id записи в таблице user_tickers
    Возвращает: (Успех: bool, Сообщение: str)
    '''
    async with aiosqlite.connect("telegram.db") as db:
        cursor = await db.cursor()

        await cursor.execute(
            "SELECT user_symbol FROM user_tickers WHERE id = ? AND user_id = ?",
            (ticker_id, telegram_id)
        )
        row = await cursor.fetchone()
        if row is None:
            return False, "Тикер не найден или уже был удалён."

        symbol = row[0]

        await db.execute(
            "DELETE FROM user_tickers WHERE id = ? AND user_id = ?",
            (ticker_id, telegram_id)
        )
        await db.commit()
        return True, f"🗑 Тикер {symbol} удалён из списка."
