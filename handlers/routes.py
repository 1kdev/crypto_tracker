from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext 
from kbds import reply, inline #модуль клавиатур
from forms.ticker import CryptoState #модуль трека крипты
from db_main.database import (add_to_db, add_ticker_to_db,
                               get_user_tickers_full, delete_ticker_from_db,
                               normalize_ticker) #модуль базы данных
from services.binance_api import get_ticker_price #модуль биржевого API


#Роутер
router = Router()

#Хэндлер старт
@router.message(Command("start"))
async def start(message: Message):
    telegram_id = message.from_user.id #Сбор айди юзера
    username = message.from_user.username #Сбор имени юзера
    await add_to_db(telegram_id, username) #Внос сбора в БД
    await message.answer("Выберите действие из кнопочного меню", reply_markup=reply.get_main_reply_keyboard())


#Хэндлер "Мои тикеры" теперь реализован в handlers/ticker_menu.py (интерактивное inline-меню)
#(команда /mytickers и текст "💼 Мои тикеры" обрабатываются там)

#Хэндлер на выбор тикера
@router.message(Command("addticker"))
@router.message(F.text.lower() == "➕ добавить тикер")
async def ticker(message: Message, state: FSMContext):
    await message.answer(
        "➕ <b>Добавление тикера</b>\n\n"
        "Введите название монеты или торговую пару.\n\n"
        "Поддерживаемые форматы:\n"
        "• BTC\n"
        "• BTCUSDT\n"
        "• BTC/USDT\n"
        "• BTC-USDT\n"
        "• BTCUSD\n\n"
        "💡 Если указать только название монеты, например BTC, бот автоматически добавит USDT:\n"
        "BTC → BTCUSDT",
        parse_mode="HTML",
        reply_markup=inline.add_ticker_cancel_keyboard(),
    )
    await state.set_state(CryptoState.ticker_choice)
    
@router.message(CryptoState.ticker_choice, F.text)
async def proccess_ticker(message: Message, state: FSMContext):
    #Получение id юзера + тикера в чат
    user_input = message.text
    user_id = message.from_user.id

    #Сначала приводим строку к формату биржи (BTCUSDT), не трогая базу
    ok, result = normalize_ticker(user_input)
    if not ok:
        #result содержит текст ошибки формата
        await message.answer(result)
        return

    final_ticker = result

    #Проверяем на бирже, что такая пара реально существует
    price = await get_ticker_price(final_ticker)
    if price is None:
        await message.answer(
            f"⚠️ Тикер {final_ticker} не найден на Binance.\n"
            "Проверьте название и попробуйте снова."
        )
        return

    #Вызов фукнции БД с нормализацией и проверкой на дубли
    success, response_message = await add_ticker_to_db(user_id, user_input)

    #Ответ юзеру
    if success:
        #Если успешно: берем сообщение из БД и дополняем текущей ценой.
        #Явно возвращаем reply_markup с главной клавиатурой, чтобы она гарантированно
        #выехала снизу чата (иначе на некоторых клиентах, например iOS, остаётся
        #открытой системная клавиатура ввода текста от предыдущего запроса).
        await message.answer(
            f"{response_message}\n💰 Текущая цена: {price} USDT",
            parse_mode="HTML",
            reply_markup=reply.get_main_reply_keyboard(),
        )
        #Очистка машины состояний, чтобы бот ждал новую команду
        await state.clear()
    else:
        #Если ошибка или дубль: сообщаем юзеру
        await message.answer(response_message)    


#Хэндлер удаления тикеров
@router.message(Command("ticker_delete"))
@router.message(F.text.lower() == "❌ удалить тикер")
async def ticker_delete(message: Message):
    user_id = message.from_user.id

    #Получаем список тикеров юзера вместе с их id в БД
    tickers = await get_user_tickers_full(user_id)

    if not tickers:
        await message.answer("У вас пока нет добавленных тикеров для удаления.")
        return

    await message.answer("Выберите тикер, который хотите удалить",
                  reply_markup = reply.inline_delete_keyboard(tickers))


#Хэндлер обработки нажатия на инлайн-кнопку удаления
@router.callback_query(F.data.startswith("del_ticker_"))
async def process_ticker_deletion(callback: CallbackQuery):
    user_id = callback.from_user.id
    ticker_id = int(callback.data.removeprefix("del_ticker_"))

    success, response_message = await delete_ticker_from_db(user_id, ticker_id)

    #Убираем клавиатуру и показываем результат прямо в том же сообщении
    await callback.message.edit_text(response_message)
    #Обязательно отвечаем на callback, иначе у юзера будет "часики" на кнопке
    await callback.answer()


#Хэндлер отмены удаления тикера (юзер передумал)
@router.callback_query(F.data == "cancel_ticker_delete")
async def cancel_ticker_deletion(callback: CallbackQuery):
    await callback.message.edit_text("↩️ Удаление отменено.")
    await callback.answer("Отменено")


#Обработчик неверной команды
@router.message()
async def user_text(message: Message):
    await message.reply("Команда <b>не найдена</b> 😢\n\nВыберите команду из кнопочного меню.",
                        parse_mode="HTML", reply_markup=reply.get_main_reply_keyboard())
