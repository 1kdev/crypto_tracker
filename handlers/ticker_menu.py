'''
Интерактивное меню "💼 Мои тикеры" на inline-кнопках.

Вся навигация (список -> карточка тикера -> оповещения -> периодичность/%)
происходит через редактирование ОДНОГО сообщения (edit_text), чтобы не
засорять чат новыми сообщениями на каждый клик.

Владение проверяется на каждом действии через get_ticker_owned(user_id, ticker_id) —
callback_data с голым id никогда не считается достаточным основанием для действия.
'''
import datetime
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from forms.ticker import CryptoState
from kbds.inline import (
    TickerCB, PeriodicCB, PercentCB, SettingsCB,
    tickers_list_keyboard, ticker_card_keyboard, edit_cancel_keyboard,
    delete_confirm_keyboard, alerts_menu_keyboard, periodic_menu_keyboard,
    change_percent_menu_keyboard, change_custom_cancel_keyboard,
    add_ticker_cancel_keyboard, settings_keyboard,
)
from db_main.database import (
    get_user_tickers_full, get_ticker_owned, update_ticker_symbol,
    delete_ticker_from_db, set_periodic_notification, set_change_percent_notification,
    normalize_ticker, get_user_settings, set_notifications_enabled, set_hourly_enabled,
)
from services.binance_api import get_ticker_price, get_24h_stats, get_24h_stats_batch

logger = logging.getLogger(__name__)
router = Router()


def format_price(price: float) -> str:
    #Для цен от 1 USDT и выше двух знаков достаточно (BTC, ETH),
    #для дешёвых монет (например мелкие альткоины) нужна большая точность
    decimals = 2 if price >= 1 else 6
    text = f"{price:,.{decimals}f}".replace(",", " ")
    if decimals == 6:
        #Обрезаем незначащие нули, но оставляем минимум 2 знака после запятой
        text = text.rstrip("0")
        if text.endswith("."):
            text += "00"
        else:
            head, _, tail = text.partition(".")
            if len(tail) < 2:
                text = f"{head}.{tail.ljust(2, '0')}"
    return text


def format_change(current: float, previous: float | None) -> str:
    '''
    Строка вида "📈 +0.09% | +18.00 USDT" / "📉 -1.24% | -950.00 USDT".
    Возвращает пустую строку, если предыдущей цены ещё нет (нельзя показывать фальшивую статистику).
    '''
    if not previous:
        return ""
    diff = current - previous
    pct = (diff / previous) * 100
    icon = "📈" if diff >= 0 else "📉"
    sign = "+" if diff >= 0 else ""
    return f"{icon} {sign}{pct:.2f}% | {sign}{format_price(diff)} USDT"


def format_percent(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def build_alerts_status_text(ticker: dict) -> str:
    lines = []
    if ticker.get("periodic_minutes"):
        lines.append(f"⏱ Каждые {ticker['periodic_minutes']} минут")
    if ticker.get("change_percent"):
        lines.append(f"📈 При изменении ±{format_percent(ticker['change_percent'])}%")
    if not lines:
        lines.append("не настроены")
    return "\n".join(lines)


def symbol_icon(symbol: str) -> str:
    icons = {"BTC": "₿", "ETH": "Ξ", "SOL": "◎"}
    for base, icon in icons.items():
        if symbol.startswith(base):
            return icon
    return "🔸"


# ==================================================
# 1. Точка входа: "💼 Мои тикеры"
# ==================================================
@router.message(F.text.lower() == "💼 мои тикеры")
@router.message(Command("mytickers"))
async def open_tickers_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    tickers = await get_user_tickers_full(user_id)

    if not tickers:
        await message.answer(
            "💼 <b>Мои тикеры</b>\n\nУ вас пока нет отслеживаемых тикеров.",
            parse_mode="HTML",
            reply_markup=tickers_list_keyboard(tickers),
        )
        return

    await message.answer(
        "💼 <b>Мои тикеры</b>\n\nВыберите тикер, чтобы посмотреть детали и оповещения.",
        parse_mode="HTML",
        reply_markup=tickers_list_keyboard(tickers),
    )


# ==================================================
# 2. Список тикеров (возврат "⬅️ Назад к тикерам")
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "list"))
async def cb_tickers_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    tickers = await get_user_tickers_full(user_id)

    text = "💼 <b>Мои тикеры</b>\n\n"
    text += "У вас пока нет отслеживаемых тикеров." if not tickers \
        else "Выберите тикер, чтобы посмотреть детали и оповещения."

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tickers_list_keyboard(tickers))
    await callback.answer()


# ==================================================
# 3. Закрыть меню
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "close"))
async def cb_close_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("💼 Меню тикеров закрыто. Откройте его снова через кнопку ниже.")
    await callback.answer()


# ==================================================
# 4. Начать добавление тикера (переиспользуем существующий FSM-флоу)
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "add"))
async def cb_add_ticker(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
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
        reply_markup=add_ticker_cancel_keyboard(),
    )
    await state.set_state(CryptoState.ticker_choice)
    await callback.answer()


@router.callback_query(TickerCB.filter(F.action == "add_cancel"))
async def cb_add_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    tickers = await get_user_tickers_full(user_id)
    text = "💼 <b>Мои тикеры</b>\n\n"
    text += "У вас пока нет отслеживаемых тикеров." if not tickers \
        else "Выберите тикер, чтобы посмотреть детали и оповещения."
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tickers_list_keyboard(tickers))
    await callback.answer("Отменено")


def format_24h_change(change_percent: float, change_abs: float) -> str:
    '''"📈 +0.30% | +50.00 USDT" за последние 24 часа, по данным Binance 24hr ticker.'''
    icon = "📈" if change_percent >= 0 else "📉"
    pct_sign = "+" if change_percent >= 0 else ""  #для отрицательных % минус уже даёт сам format-spec
    abs_sign = "+" if change_abs >= 0 else "-"
    return f"{icon} {pct_sign}{change_percent:.2f}% | {abs_sign}{format_price(abs(change_abs))} USDT"


# ==================================================
# 5. Карточка конкретного тикера
# ==================================================
async def render_ticker_card(callback: CallbackQuery, ticker_id: int):
    user_id = callback.from_user.id
    ticker = await get_ticker_owned(user_id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден или больше вам не принадлежит.", show_alert=True)
        return

    stats = await get_24h_stats(ticker["user_symbol"])
    icon = symbol_icon(ticker["user_symbol"])

    if stats is not None:
        price_text = f"{format_price(stats['price'])} USDT"
        change_line = f"\n{format_24h_change(stats['change_percent'], stats['change_abs'])} (24ч)"
    else:
        price_text = "цена недоступна ⚠️"
        change_line = ""

    text = (
        f"{icon} <b>{ticker['user_symbol']}</b>\n\n"
        f"💰 Цена: {price_text}{change_line}\n\n"
        f"🔔 Оповещения:\n{build_alerts_status_text(ticker)}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=ticker_card_keyboard(ticker_id))


@router.callback_query(TickerCB.filter(F.action == "open"))
async def cb_open_ticker(callback: CallbackQuery, callback_data: TickerCB, state: FSMContext):
    await state.clear()
    await render_ticker_card(callback, callback_data.id)
    await callback.answer()


# ==================================================
# 6. Изменить тикер
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "edit_start"))
async def cb_edit_start(callback: CallbackQuery, callback_data: TickerCB, state: FSMContext):
    ticker_id = callback_data.id
    ticker = await get_ticker_owned(callback.from_user.id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return

    await state.set_state(CryptoState.editing_ticker)
    await state.update_data(
        ticker_id=ticker_id,
        menu_chat_id=callback.message.chat.id,
        menu_message_id=callback.message.message_id,
    )
    await callback.message.edit_text(
        f"✏️ Текущий тикер: <b>{ticker['user_symbol']}</b>\n\nВведите новый тикер:",
        parse_mode="HTML",
        reply_markup=edit_cancel_keyboard(ticker_id),
    )
    await callback.answer()


@router.callback_query(TickerCB.filter(F.action == "edit_cancel"))
async def cb_edit_cancel(callback: CallbackQuery, callback_data: TickerCB, state: FSMContext):
    await state.clear()
    await render_ticker_card(callback, callback_data.id)
    await callback.answer("Отменено")


@router.message(CryptoState.editing_ticker, F.text)
async def process_edit_ticker(message: Message, state: FSMContext):
    data = await state.get_data()
    ticker_id = data["ticker_id"]
    menu_chat_id = data["menu_chat_id"]
    menu_message_id = data["menu_message_id"]
    user_id = message.from_user.id

    # Сначала нормализуем и валидируем именно то, что реально запишем в БД
    ok, normalized = normalize_ticker(message.text)
    if not ok:
        await message.answer(f"{normalized}\n\nПопробуйте ещё раз или нажмите «Отмена» в меню выше.")
        return

    price = await get_ticker_price(normalized)
    if price is None:
        await message.answer(
            f"❌ Тикер {normalized} не найден.\n\nДайте корректный тикер, или нажмите «Отмена» в меню выше."
        )
        return

    success, result = await update_ticker_symbol(user_id, ticker_id, message.text, price)
    if not success:
        await message.answer(f"{result}\n\nПопробуйте ещё раз или нажмите «Отмена» в меню выше.")
        return

    await state.clear()
    ticker = await get_ticker_owned(user_id, ticker_id)
    icon = symbol_icon(ticker["user_symbol"])
    text = (
        f"{icon} <b>{ticker['user_symbol']}</b>\n\n"
        f"💰 Цена: {format_price(price)} USDT\n\n"
        f"🔔 Оповещения:\n{build_alerts_status_text(ticker)}"
    )
    try:
        await message.bot.edit_message_text(
            text, chat_id=menu_chat_id, message_id=menu_message_id,
            parse_mode="HTML", reply_markup=ticker_card_keyboard(ticker_id),
        )
    except Exception as e:
        logger.warning(f"Не удалось отредактировать меню после смены тикера: {e}")
        await message.answer(text, parse_mode="HTML", reply_markup=ticker_card_keyboard(ticker_id))


# ==================================================
# 7. Удаление тикера
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "delete_ask"))
async def cb_delete_ask(callback: CallbackQuery, callback_data: TickerCB):
    ticker_id = callback_data.id
    ticker = await get_ticker_owned(callback.from_user.id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Удалить {ticker['user_symbol']}?",
        reply_markup=delete_confirm_keyboard(ticker_id),
    )
    await callback.answer()


@router.callback_query(TickerCB.filter(F.action == "delete_no"))
async def cb_delete_no(callback: CallbackQuery, callback_data: TickerCB):
    await render_ticker_card(callback, callback_data.id)
    await callback.answer("Отменено")


@router.callback_query(TickerCB.filter(F.action == "delete_yes"))
async def cb_delete_yes(callback: CallbackQuery, callback_data: TickerCB):
    user_id = callback.from_user.id
    ticker_id = callback_data.id
    success, result_message = await delete_ticker_from_db(user_id, ticker_id)
    if not success:
        await callback.answer(result_message, show_alert=True)
        return

    tickers = await get_user_tickers_full(user_id)
    text = "💼 <b>Мои тикеры</b>\n\n"
    text += "У вас пока нет отслеживаемых тикеров." if not tickers \
        else "Выберите тикер, чтобы посмотреть детали и оповещения."
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tickers_list_keyboard(tickers))
    await callback.answer(result_message)


# ==================================================
# 8. Меню оповещений тикера
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "alerts"))
async def cb_alerts_menu(callback: CallbackQuery, callback_data: TickerCB, state: FSMContext):
    await state.clear()
    ticker_id = callback_data.id
    ticker = await get_ticker_owned(callback.from_user.id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return

    text = f"🔔 <b>Оповещения для {ticker['user_symbol']}</b>\n\nТекущие настройки:\n{build_alerts_status_text(ticker)}"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=alerts_menu_keyboard(ticker_id))
    await callback.answer()


@router.callback_query(TickerCB.filter(F.action == "alerts_summary"))
async def cb_alerts_summary(callback: CallbackQuery, callback_data: TickerCB):
    ticker = await get_ticker_owned(callback.from_user.id, callback_data.id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return
    summary = f"{ticker['user_symbol']}:\n{build_alerts_status_text(ticker)}"
    await callback.answer(summary, show_alert=True)


# ==================================================
# 9. Периодические оповещения
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "periodic_menu"))
async def cb_periodic_menu(callback: CallbackQuery, callback_data: TickerCB):
    ticker_id = callback_data.id
    ticker = await get_ticker_owned(callback.from_user.id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Как часто отправлять цену {ticker['user_symbol']}?",
        reply_markup=periodic_menu_keyboard(ticker_id),
    )
    await callback.answer()


@router.callback_query(PeriodicCB.filter())
async def cb_periodic_set(callback: CallbackQuery, callback_data: PeriodicCB):
    user_id = callback.from_user.id
    ticker_id = callback_data.id
    minutes = callback_data.minutes or None

    ticker = await get_ticker_owned(user_id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return

    ok = await set_periodic_notification(user_id, ticker_id, minutes)
    if not ok:
        await callback.answer("Не удалось сохранить настройку.", show_alert=True)
        return

    icon = symbol_icon(ticker["user_symbol"])
    if minutes:
        text = f"⏱ {icon} <b>{ticker['user_symbol']}</b>\n\nОповещение установлено:\nкаждые {minutes} минут."
    else:
        text = f"⏱ {icon} <b>{ticker['user_symbol']}</b>\n\nПериодическое оповещение выключено."

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=TickerCB(action="alerts", id=ticker_id).pack()))

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


# ==================================================
# 10. Оповещение по изменению цены
# ==================================================
@router.callback_query(TickerCB.filter(F.action == "change_menu"))
async def cb_change_menu(callback: CallbackQuery, callback_data: TickerCB):
    ticker_id = callback_data.id
    ticker = await get_ticker_owned(callback.from_user.id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        f"На сколько % должна измениться цена {ticker['user_symbol']}, чтобы вы получили оповещение?",
        reply_markup=change_percent_menu_keyboard(ticker_id),
    )
    await callback.answer()


@router.callback_query(PercentCB.filter())
async def cb_percent_set(callback: CallbackQuery, callback_data: PercentCB):
    user_id = callback.from_user.id
    ticker_id = callback_data.id

    ticker = await get_ticker_owned(user_id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=TickerCB(action="alerts", id=ticker_id).pack()))

    if callback_data.value == "off":
        ok = await set_change_percent_notification(user_id, ticker_id, None, None)
        if not ok:
            await callback.answer("Не удалось сохранить настройку.", show_alert=True)
            return
        text = f"📈 <b>{ticker['user_symbol']}</b>\n\nОповещение по изменению цены выключено."
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        await callback.answer()
        return

    percent = float(callback_data.value)
    price = await get_ticker_price(ticker["user_symbol"])
    if price is None:
        await callback.answer("Не удалось получить текущую цену, попробуйте позже.", show_alert=True)
        return

    ok = await set_change_percent_notification(user_id, ticker_id, percent, price)
    if not ok:
        await callback.answer("Не удалось сохранить настройку.", show_alert=True)
        return

    text = (
        f"📈 Оповещение установлено.\n\n"
        f"{ticker['user_symbol']} будет отправлять уведомление при изменении цены на ±{format_percent(percent)}%."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(TickerCB.filter(F.action == "change_custom"))
async def cb_change_custom_start(callback: CallbackQuery, callback_data: TickerCB, state: FSMContext):
    ticker_id = callback_data.id
    ticker = await get_ticker_owned(callback.from_user.id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return

    await state.set_state(CryptoState.waiting_custom_percentage)
    await state.update_data(
        ticker_id=ticker_id,
        menu_chat_id=callback.message.chat.id,
        menu_message_id=callback.message.message_id,
    )
    await callback.message.edit_text(
        "Введите процент изменения цены.\n\nНапример:\n0.5\n1\n2.5\n7.5",
        reply_markup=change_custom_cancel_keyboard(ticker_id),
    )
    await callback.answer()


@router.callback_query(TickerCB.filter(F.action == "change_cancel"))
async def cb_change_custom_cancel(callback: CallbackQuery, callback_data: TickerCB, state: FSMContext):
    await state.clear()
    ticker_id = callback_data.id
    ticker = await get_ticker_owned(callback.from_user.id, ticker_id)
    if ticker is None:
        await callback.answer("Тикер не найден.", show_alert=True)
        return
    text = f"🔔 <b>Оповещения для {ticker['user_symbol']}</b>\n\nТекущие настройки:\n{build_alerts_status_text(ticker)}"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=alerts_menu_keyboard(ticker_id))
    await callback.answer("Отменено")


@router.message(CryptoState.waiting_custom_percentage, F.text)
async def process_custom_percentage(message: Message, state: FSMContext):
    data = await state.get_data()
    ticker_id = data["ticker_id"]
    menu_chat_id = data["menu_chat_id"]
    menu_message_id = data["menu_message_id"]
    user_id = message.from_user.id

    raw = message.text.strip().replace(",", ".")
    try:
        percent = float(raw)
    except ValueError:
        percent = None

    if percent is None or percent <= 0:
        await message.answer(
            "❌ Введите положительное число больше 0.\n\nНапример: 0.5, 1, 2.5, 7.5"
        )
        return

    ticker = await get_ticker_owned(user_id, ticker_id)
    if ticker is None:
        await state.clear()
        await message.answer("Тикер не найден или был удалён.")
        return

    price = await get_ticker_price(ticker["user_symbol"])
    if price is None:
        await message.answer("⚠️ Не удалось получить текущую цену, попробуйте немного позже.")
        return

    ok = await set_change_percent_notification(user_id, ticker_id, percent, price)
    if not ok:
        await message.answer("⚠️ Не удалось сохранить настройку.")
        return

    await state.clear()
    text = (
        f"📈 Оповещение установлено.\n\n"
        f"{ticker['user_symbol']} будет отправлять уведомление при изменении цены на ±{format_percent(percent)}%."
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=TickerCB(action="alerts", id=ticker_id).pack()))

    try:
        await message.bot.edit_message_text(
            text, chat_id=menu_chat_id, message_id=menu_message_id,
            parse_mode="HTML", reply_markup=builder.as_markup(),
        )
    except Exception as e:
        logger.warning(f"Не удалось отредактировать меню после установки %: {e}")
        await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())


# ==================================================
# 11. Глобальные настройки (⚙️ Настройки)
# ==================================================
def settings_text(settings: dict) -> str:
    notif = "✅ ВКЛ" if settings["notifications_enabled"] else "🔕 ВЫКЛ"
    hourly = "✅ ВКЛ" if settings["hourly_enabled"] else "🔕 ВЫКЛ"
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"🔔 Все уведомления: {notif}\n\n"
        f"⏰ Ежечасные обновления: {hourly}\n\n"
        "Выключение ставит уведомления на паузу — ваши тикеры и настройки не удаляются."
    )


@router.message(F.text.lower() == "⚙️ настройки")
async def open_settings_menu(message: Message, state: FSMContext):
    await state.clear()
    settings = await get_user_settings(message.from_user.id)
    await message.answer(
        settings_text(settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(settings["notifications_enabled"], settings["hourly_enabled"]),
    )


@router.callback_query(SettingsCB.filter(F.action == "toggle_notifications"))
async def cb_toggle_notifications(callback: CallbackQuery):
    user_id = callback.from_user.id
    settings = await get_user_settings(user_id)
    new_value = not settings["notifications_enabled"]
    await set_notifications_enabled(user_id, new_value)
    settings["notifications_enabled"] = new_value
    await callback.message.edit_text(
        settings_text(settings), parse_mode="HTML",
        reply_markup=settings_keyboard(settings["notifications_enabled"], settings["hourly_enabled"]),
    )
    await callback.answer("🔔 Уведомления включены" if new_value else "🔕 Уведомления на паузе")


@router.callback_query(SettingsCB.filter(F.action == "toggle_hourly"))
async def cb_toggle_hourly(callback: CallbackQuery):
    user_id = callback.from_user.id
    settings = await get_user_settings(user_id)
    new_value = not settings["hourly_enabled"]
    await set_hourly_enabled(user_id, new_value)
    settings["hourly_enabled"] = new_value
    await callback.message.edit_text(
        settings_text(settings), parse_mode="HTML",
        reply_markup=settings_keyboard(settings["notifications_enabled"], settings["hourly_enabled"]),
    )
    await callback.answer("⏰ Ежечасные обновления включены" if new_value else "⏰ Ежечасные обновления на паузе")


@router.callback_query(SettingsCB.filter(F.action == "open_tickers"))
async def cb_settings_open_tickers(callback: CallbackQuery, state: FSMContext):
    #Переход из настроек к списку тикеров, чтобы настроить оповещения конкретного
    #тикера. В отличие от "💼 Мои тикеры" (полная карточка тикера с ✏️/🗑),
    #здесь выбор тикера сразу открывает меню его оповещений — без лишних кнопок.
    await state.clear()
    user_id = callback.from_user.id
    tickers = await get_user_tickers_full(user_id)

    text = "💼 <b>Мои тикеры</b>\n\n"
    text += "У вас пока нет отслеживаемых тикеров. Сначала добавьте тикер." if not tickers \
        else "Выберите тикер, чтобы настроить его оповещения."

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=tickers_list_keyboard(
            tickers, ticker_action="alerts", back_callback=SettingsCB(action="reopen").pack()
        ),
    )
    await callback.answer()


@router.callback_query(SettingsCB.filter(F.action == "reopen"))
async def cb_settings_reopen(callback: CallbackQuery):
    settings = await get_user_settings(callback.from_user.id)
    await callback.message.edit_text(
        settings_text(settings), parse_mode="HTML",
        reply_markup=settings_keyboard(settings["notifications_enabled"], settings["hourly_enabled"]),
    )
    await callback.answer()


@router.callback_query(SettingsCB.filter(F.action == "back"))
async def cb_settings_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ Настройки закрыты. Откройте их снова через кнопку ниже.",
    )
    await callback.answer()


# ==================================================
# 12. Общая статистика по всем тикерам (📊 Статистика)
# ==================================================
@router.message(F.text.lower() == "📊 статистика")
async def show_stats(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    tickers = await get_user_tickers_full(user_id)

    if not tickers:
        await message.answer("У вас пока нет добавленных тикеров. Добавьте их через «➕ Добавить тикер».")
        return

    symbols = [symbol for _, symbol in tickers]
    stats = await get_24h_stats_batch(symbols)

    lines = ["📊 <b>Статистика за 24 часа</b>\n"]
    for _, symbol in tickers:
        s = stats.get(symbol)
        if s is None:
            lines.append(f"{symbol}\nцена недоступна ⚠️\n")
            continue
        lines.append(
            f"{symbol}\n{format_price(s['price'])} USDT\n"
            f"{format_24h_change(s['change_percent'], s['change_abs'])} (24ч)\n"
        )

    await message.answer("\n".join(lines).strip(), parse_mode="HTML")
