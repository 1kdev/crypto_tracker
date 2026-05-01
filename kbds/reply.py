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

#Inline клавиатура 
def inline_delete_keyboard():
    inline_kb_list = [
        [InlineKeyboardButton(text="Название тикера 1", callback_data = "del_ticker_1")],
        [InlineKeyboardButton(text="Название тикера 2", callback_data = "del_ticker_2")],
        [InlineKeyboardButton(text="Название тикера 3", callback_data = "del_ticker_3")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_kb_list)