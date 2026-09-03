from aiogram.fsm.state import StatesGroup, State

class CryptoState(StatesGroup):
    ticker_choice = State()
    #Ожидание ввода нового тикера при замене существующего (кнопка "✏️ Изменить тикер")
    editing_ticker = State()
    #Ожидание ввода своего % изменения цены (кнопка "✏️ Свой процент")
    waiting_custom_percentage = State()