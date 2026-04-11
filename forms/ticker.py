from aiogram.fsm.state import StatesGroup, State

class CryptoState(StatesGroup):
    ticker_choice = State()