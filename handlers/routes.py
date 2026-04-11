from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext 
from kbds import reply #модуль клавиатур
from forms.ticker import CryptoState #модуль трека крипты
from db_main.database import add_to_db #модуль базы данных


#Роутер
router = Router()

#Хэндлер старт
@router.message(Command("start"))
async def start(message: Message):
    telegram_id = message.from_user.id #Сбор айди юзера
    username = message.from_user.username #Сбор имени юзера
    await add_to_db(telegram_id, username) #Внос сбора в БД
    await message.answer("Выберите действие из кнопочного меню", reply_markup=reply.get_main_reply_keyboard())


#Хэндлер хелп
@router.message(Command("mytickers"))
@router.message(F.text.lower() == "💼мои тикеры")
async def help(message: Message): 
    await message.answer(f"Список <b>ваших</b> тикеров:\n\n[my_ticker_1]:\nТекущая цена: [price]\nИзменение за 24h - [price_change_perday]\n\n[my_ticker_2]\nТекущая цена: [price]\nИзменение за 24h - [price_change_perday]",
                         parse_mode="HTML")

#Хэндлер на выбор тикета
@router.message(Command("addticker"))
@router.message(F.text.lower() == "➕добавить тикер")
async def ticker(message: Message, state: FSMContext):
    await message.answer("Введите название интересующего тикера")
    await state.set_state(CryptoState.ticker_choice)
    
@router.message(CryptoState.ticker_choice, F.text)
async def proccess_ticker(message: Message, state: FSMContext):
    await state.update_data(ticker_choice = message.text)
    data = await state.get_data()
    added_ticker = data["ticker_choice"]
    await message.answer(f"Тикер <b><i>{added_ticker}</i></b> добавлен успешно!",
                         parse_mode="HTML")
    await state.clear()
    


#Хэндлер удаления тикеров
@router.message(Command("ticker_delete"))
@router.message(F.text.lower() == "❌удалить тикер")
async def ticker_delete(message: Message):
    await message.answer("Выберите тикер, который хотите удалить",
                  reply_markup = reply.inline_delete_keyboard())

#Обработчик неверной команды
@router.message()
async def user_text(message: Message):
    await message.reply("Команда <b>не найдена</b> 😢\n\nВыберите команду из кнопочного меню.",
                        parse_mode="HTML", reply_markup=reply.get_main_reply_keyboard())