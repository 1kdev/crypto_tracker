import datetime
import aiosqlite

#Имя файла БД вынесено в константу, чтобы тесты могли подменять его на временную БД
DB_PATH = "telegram.db"

#Периодические интервалы оповещений, которые поддерживает бот (в минутах)
ALLOWED_PERIODIC_MINUTES = (5, 15, 30, 45, 60)

#Известные quote-валюты для разбора "слитных" тикеров без разделителя (BTCUSDT, BTCUSD, ...).
#Порядок важен: сначала более длинные/специфичные суффиксы, чтобы не отрезать лишнее
#(например USDT должен матчиться раньше USD).
KNOWN_QUOTES = ("USDT", "BUSD", "USDC", "USD", "EUR", "TRY", "GBP", "BTC", "ETH")
#Quote-валюта по умолчанию, которая подставляется, если юзер ввёл только имя монеты (BTC -> BTCUSDT)
DEFAULT_QUOTE = "USDT"


async def _migrate(db: aiosqlite.Connection):
    '''
    Добавляет недостающие колонки в уже существующие таблицы.
    Не трогает и не удаляет старые данные/колонки (например last_notifed_price
    остаётся ради обратной совместимости, но новый функционал её не использует).
    '''
    #users: колонка для отслеживания последней отправки почасового дайджеста
    cursor = await db.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in await cursor.fetchall()}
    await cursor.close()
    if "last_hourly_sent" not in user_columns:
        await db.execute("ALTER TABLE users ADD COLUMN last_hourly_sent TEXT")

    #user_tickers: колонки под персональные оповещения
    cursor = await db.execute("PRAGMA table_info(user_tickers)")
    ticker_columns = {row[1] for row in await cursor.fetchall()}
    await cursor.close()
    ticker_new_columns = {
        "periodic_minutes": "INTEGER",
        "last_periodic_sent": "TEXT",
        "change_percent": "REAL",
        "baseline_price": "REAL",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }
    ticker_new_columns.update({
        #Цена на момент последней отправки периодического (⏱ каждые N минут) оповещения —
        #нужна, чтобы показывать изменение цены с прошлого такого уведомления
        "last_periodic_price": "REAL",
        #Цена на момент последней отправки почасового дайджеста для этого тикера
        "last_hourly_price": "REAL",
    })
    for column, col_type in ticker_new_columns.items():
        if column not in ticker_columns:
            await db.execute(f"ALTER TABLE user_tickers ADD COLUMN {column} {col_type}")

    #users: глобальные переключатели уведомлений (не удаляют настройки, только пауза)
    if "notifications_enabled" not in user_columns:
        await db.execute("ALTER TABLE users ADD COLUMN notifications_enabled INTEGER DEFAULT 1")
    if "hourly_enabled" not in user_columns:
        await db.execute("ALTER TABLE users ADD COLUMN hourly_enabled INTEGER DEFAULT 1")

    await db.commit()


async def init_db():
    '''
    Создаёт таблицы (если их ещё нет) и прогоняет миграцию недостающих колонок.
    Вызывается один раз при старте приложения.
    '''
    async with aiosqlite.connect(DB_PATH) as db:
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
        await db.commit()
        await _migrate(db)


async def add_to_db(telegram_id, username):
    async with aiosqlite.connect(DB_PATH) as db:
        #Гарантируем, что таблицы и колонки существуют (например при первом запуске)
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
                         telegram_id BIGINT,
                         username TEXT,
                         date TEXT,
                         delay_time INTEGER DEFAULT 3600 
                         )""") 
        await db.execute("""CREATE TABLE IF NOT EXISTS user_tickers(
                         id INTEGER PRIMARY KEY,
                         user_id BIGINT,
                         user_symbol TEXT,
                         last_notifed_price
                         )""")
        await db.commit()
        await _migrate(db)
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
    Разбирает сырую строку от юзера и приводит её к формату биржи (например 'BTCUSDT').
    Поддерживаемые форматы ввода:
        BTC        -> BTCUSDT (голое имя монеты, quote по умолчанию USDT)
        BTCUSDT    -> BTCUSDT (quote указан явно и не меняется)
        BTC/USDT   -> BTCUSDT
        BTC-USDT   -> BTCUSDT
        BTCUSD     -> BTCUSD  (явный quote USD сохраняется как есть)
    Аргументы:
        ticker_symbol - сырая строка от юзера
    Возвращает: (Успех: bool, Итоговый тикер или текст ошибки: str)
    '''
    #Нормализация формата тикера в верхний регистр, без пробелов
    clean_ticker = ticker_symbol.upper().replace(" ", "")

    if not clean_ticker:
        return False, "Ошибка: не удалось распознать тикер. Пример: BTC, BTCUSDT, BTC/USDT"

    base = ""
    quote = ""

    #Вариант 1 и 2: юзер явно указал разделитель (BTC/USDT или BTC-USDT)
    if "/" in clean_ticker or "-" in clean_ticker:
        sep = "/" if "/" in clean_ticker else "-"
        parts = clean_ticker.split(sep)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False, "Ошибка: неверный формат. Пример: BTC/USDT или BTC-USDT"
        base, quote = parts[0], parts[1]
    else:
        #Вариант 3: юзер ввёл слитно — либо BASE+QUOTE (BTCUSDT/BTCUSD), либо просто BASE (BTC)
        matched_quote = None
        for known in KNOWN_QUOTES:
            if clean_ticker.endswith(known) and len(clean_ticker) > len(known):
                matched_quote = known
                break
        if matched_quote:
            base = clean_ticker[: -len(matched_quote)]
            quote = matched_quote
        else:
            #Явного quote не найдено — считаем, что ввели только имя монеты
            base = clean_ticker
            quote = DEFAULT_QUOTE

    if not base or not base.isalnum() or not quote.isalnum():
        return False, "Ошибка: не удалось распознать тикер. Пример: BTC, BTCUSDT, BTC/USDT"

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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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


async def get_ticker_owned(telegram_id: int, ticker_id: int) -> dict | None:
    '''
    Достаёт полную запись тикера, только если он принадлежит telegram_id.
    Используется перед ЛЮБЫМ действием с конкретным тикером (просмотр, изменение,
    удаление, настройка оповещений), чтобы никогда не доверять голому id из callback_data.
    Возвращает dict с ключами id, user_symbol, periodic_minutes, change_percent,
    baseline_price, last_periodic_sent, либо None, если тикер не найден/не принадлежит юзеру.
    '''
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT id, user_symbol, periodic_minutes, change_percent,
                      baseline_price, last_periodic_sent
               FROM user_tickers WHERE id = ? AND user_id = ?""",
            (ticker_id, telegram_id)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None


async def update_ticker_symbol(telegram_id: int, ticker_id: int, new_ticker_raw: str,
                                new_baseline_price: float | None) -> tuple[bool, str]:
    '''
    Заменяет тикер в уже существующей записи (не создаёт новую строку),
    сохраняя её настройки оповещений. Если для записи было настроено
    оповещение по % изменения, baseline_price пересчитывается на новую цену,
    чтобы % отсчитывался от актуальной цены нового тикера.
    '''
    ok, result = normalize_ticker(new_ticker_raw)
    if not ok:
        return False, result
    final_ticker = result

    async with aiosqlite.connect(DB_PATH) as db:
        #Убедимся что тикер принадлежит юзеру
        cursor = await db.execute(
            "SELECT id, change_percent FROM user_tickers WHERE id = ? AND user_id = ?",
            (ticker_id, telegram_id)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return False, "Тикер не найден."

        #Проверка на дубликат (нельзя поменять на тикер, который уже отслеживается)
        cursor = await db.execute(
            "SELECT id FROM user_tickers WHERE user_id = ? AND user_symbol = ? AND id != ?",
            (telegram_id, final_ticker, ticker_id)
        )
        dup = await cursor.fetchone()
        await cursor.close()
        if dup:
            return False, f"Тикер {final_ticker} уже есть в вашем списке!"

        change_percent = row[1]
        now = f'{datetime.datetime.now()}'
        #Если было настроено оповещение по %, обновляем базовую цену под новый тикер
        if change_percent is not None:
            await db.execute(
                """UPDATE user_tickers SET user_symbol = ?, baseline_price = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (final_ticker, new_baseline_price, now, ticker_id, telegram_id)
            )
        else:
            await db.execute(
                "UPDATE user_tickers SET user_symbol = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (final_ticker, now, ticker_id, telegram_id)
            )
        await db.commit()
        return True, final_ticker


async def set_periodic_notification(telegram_id: int, ticker_id: int, minutes: int | None) -> bool:
    '''
    Включает/выключает периодическое оповещение для конкретного тикера юзера.
    minutes=None выключает оповещение.
    '''
    now = f'{datetime.datetime.now()}'
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM user_tickers WHERE id = ? AND user_id = ?",
            (ticker_id, telegram_id)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return False
        await db.execute(
            """UPDATE user_tickers SET periodic_minutes = ?, last_periodic_sent = ?, updated_at = ?
               WHERE id = ? AND user_id = ?""",
            (minutes, now if minutes else None, now, ticker_id, telegram_id)
        )
        await db.commit()
        return True


async def set_change_percent_notification(telegram_id: int, ticker_id: int,
                                            percent: float | None,
                                            baseline_price: float | None) -> bool:
    '''
    Включает/выключает оповещение по % изменения цены для конкретного тикера юзера.
    percent=None выключает оповещение. baseline_price — цена, от которой отсчитывается %.
    '''
    now = f'{datetime.datetime.now()}'
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM user_tickers WHERE id = ? AND user_id = ?",
            (ticker_id, telegram_id)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return False
        await db.execute(
            """UPDATE user_tickers SET change_percent = ?, baseline_price = ?, updated_at = ?
               WHERE id = ? AND user_id = ?""",
            (percent, baseline_price if percent else None, now, ticker_id, telegram_id)
        )
        await db.commit()
        return True


async def get_active_periodic_tickers() -> list[dict]:
    '''
    Все тикеры (всех юзеров), у которых включено периодическое оповещение,
    и у юзера не стоит глобальная пауза уведомлений (notifications_enabled=1).
    Используется scheduler'ом раз в тик, чтобы не гонять запрос на каждый тикер отдельно.
    '''
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT ut.id, ut.user_id, ut.user_symbol, ut.periodic_minutes,
                      ut.last_periodic_sent, ut.last_periodic_price
               FROM user_tickers ut
               JOIN users u ON u.telegram_id = ut.user_id
               WHERE ut.periodic_minutes IS NOT NULL
                 AND COALESCE(u.notifications_enabled, 1) = 1"""
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]


async def get_active_change_tickers() -> list[dict]:
    '''
    Все тикеры (всех юзеров), у которых включено оповещение по % изменения цены,
    и у юзера не стоит глобальная пауза уведомлений.
    '''
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT ut.id, ut.user_id, ut.user_symbol, ut.change_percent, ut.baseline_price
               FROM user_tickers ut
               JOIN users u ON u.telegram_id = ut.user_id
               WHERE ut.change_percent IS NOT NULL AND ut.baseline_price IS NOT NULL
                 AND COALESCE(u.notifications_enabled, 1) = 1"""
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]


async def update_periodic_sent(ticker_id: int, sent_at: str, price: float | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_tickers SET last_periodic_sent = ?, last_periodic_price = ? WHERE id = ?",
            (sent_at, price, ticker_id)
        )
        await db.commit()


async def update_baseline_price(ticker_id: int, new_baseline: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_tickers SET baseline_price = ? WHERE id = ?",
            (new_baseline, ticker_id)
        )
        await db.commit()


async def get_users_for_hourly_digest() -> list[dict]:
    '''
    Все пользователи, у которых есть хотя бы один тикер, не стоит глобальная пауза
    уведомлений и отдельно включены почасовые обновления, и для которых пора
    отправить почасовой дайджест (now - last_hourly_sent >= delay_time).
    Возвращает [{telegram_id, delay_time, last_hourly_sent,
                 tickers: [{"id": int, "symbol": str, "last_hourly_price": float|None}, ...]}]
    '''
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT telegram_id, delay_time, last_hourly_sent
               FROM users
               WHERE COALESCE(notifications_enabled, 1) = 1
                 AND COALESCE(hourly_enabled, 1) = 1"""
        )
        users = await cursor.fetchall()
        await cursor.close()

        result = []
        for user in users:
            cursor = await db.execute(
                "SELECT id, user_symbol, last_hourly_price FROM user_tickers WHERE user_id = ?",
                (user["telegram_id"],)
            )
            ticker_rows = await cursor.fetchall()
            await cursor.close()
            tickers = [
                {"id": row["id"], "symbol": row["user_symbol"], "last_hourly_price": row["last_hourly_price"]}
                for row in ticker_rows
            ]
            if not tickers:
                continue
            result.append({
                "telegram_id": user["telegram_id"],
                "delay_time": user["delay_time"] or 3600,
                "last_hourly_sent": user["last_hourly_sent"],
                "tickers": tickers,
            })
        return result


async def update_hourly_sent(telegram_id: int, sent_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_hourly_sent = ? WHERE telegram_id = ?",
            (sent_at, telegram_id)
        )
        await db.commit()


async def update_hourly_prices(price_by_ticker_id: dict[int, float]):
    '''Обновляет last_hourly_price сразу для нескольких тикеров после отправки дайджеста.'''
    if not price_by_ticker_id:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "UPDATE user_tickers SET last_hourly_price = ? WHERE id = ?",
            [(price, ticker_id) for ticker_id, price in price_by_ticker_id.items()]
        )
        await db.commit()


async def get_user_settings(telegram_id: int) -> dict:
    '''Возвращает глобальные настройки уведомлений юзера (создаёт запись с дефолтами, если её нет).'''
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT notifications_enabled, hourly_enabled FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return {"notifications_enabled": True, "hourly_enabled": True}
        return {
            "notifications_enabled": bool(row["notifications_enabled"] if row["notifications_enabled"] is not None else 1),
            "hourly_enabled": bool(row["hourly_enabled"] if row["hourly_enabled"] is not None else 1),
        }


async def set_notifications_enabled(telegram_id: int, enabled: bool):
    '''Глобальная пауза/возобновление всех уведомлений. Ничего не удаляет — только флаг.'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET notifications_enabled = ? WHERE telegram_id = ?",
            (1 if enabled else 0, telegram_id)
        )
        await db.commit()


async def set_hourly_enabled(telegram_id: int, enabled: bool):
    '''Отдельная пауза/возобновление почасовых обновлений. Ничего не удаляет — только флаг.'''
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET hourly_enabled = ? WHERE telegram_id = ?",
            (1 if enabled else 0, telegram_id)
        )
        await db.commit()
