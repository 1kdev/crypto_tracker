from aiogram.types import (ReplyKeyboardMarkup, 
                           KeyboardButton, 
                           InlineKeyboardButton, 
                           InlineKeyboardMarkup,)

#Главная клавиатура
def get_main_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💼 Мои тикеры")],
            [
            KeyboardButton(text="➕ Добавить тикер"),
            KeyboardButton(text="❌ Удалить тикер")
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )
    return keyboard

#Inline клавиатура удаления, строится из реального списка тикеров юзера
def inline_delete_keyboard(tickers: list[tuple[int, str]]):
    '''
    Аргументы:
        tickers - список кортежей (id, symbol), например [(1, 'BTCUSDT'), (2, 'ETHUSDT')],
                  получаемый из db_main.database.get_user_tickers_full
    '''
    inline_kb_list = [
        [InlineKeyboardButton(text=f"❌ {symbol}", callback_data=f"del_ticker_{ticker_id}")]
        for ticker_id, symbol in tickers
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_kb_list)
