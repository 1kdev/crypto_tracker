'''
Inline-клавиатуры и CallbackData для интерактивного меню "Мои тикеры".

Вся навигация построена на редактировании ОДНОГО сообщения (edit_text /
edit_reply_markup), поэтому здесь только билдеры клавиатур — сама логика
переходов живёт в handlers/ticker_menu.py.
'''
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db_main.database import ALLOWED_PERIODIC_MINUTES

#Готовые проценты для оповещения по изменению цены
PRESET_PERCENTS = ("0.5", "1", "2", "3", "5", "10")


class TickerCB(CallbackData, prefix="tk"):
    '''
    Универсальный callback для навигации по меню тикеров.
    action:
        list           - список тикеров ("Мои тикеры")
        open           - открыть карточку конкретного тикера
        add            - начать добавление нового тикера (делегируется в старый FSM-флоу)
        close          - закрыть инлайн-меню (вернуться в "обычный" режим)
        edit_start     - начать замену тикера (запрос ввода)
        edit_cancel    - отмена замены тикера
        delete_ask     - запросить подтверждение удаления
        delete_yes     - подтвердить удаление
        delete_no      - отменить удаление, вернуться к карточке тикера
        alerts         - открыть меню оповещений тикера
        alerts_summary - показать текущие настройки оповещений (всплывающая подсказка)
        periodic_menu  - открыть меню выбора периода
        change_menu    - открыть меню выбора % изменения
        change_custom  - начать ввод своего % (запрос ввода)
        change_cancel  - отмена ввода своего %
        add_cancel     - отмена ввода тикера при добавлении (кнопка "↩️ Отмена")
    '''
    action: str
    id: int = 0


class PeriodicCB(CallbackData, prefix="per"):
    id: int
    minutes: int  # 0 = выключить


class PercentCB(CallbackData, prefix="pct"):
    id: int
    value: str  # "0.5" / "1" / ... / "off"


class SettingsCB(CallbackData, prefix="stg"):
    '''
    action:
        toggle_notifications - переключить глобальную паузу всех уведомлений
        toggle_hourly        - переключить паузу почасовых обновлений
        open_tickers          - перейти к списку тикеров, чтобы настроить оповещения конкретного тикера
        reopen                - вернуться к экрану настроек (кнопка "⬅️ Назад" из списка тикеров)
        back                  - закрыть меню настроек
    '''
    action: str


def tickers_list_keyboard(
    tickers: list[tuple[int, str]],
    ticker_action: str = "open",
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    '''
    tickers: список (ticker_id, symbol)
    ticker_action: какой TickerCB.action повесить на кнопку тикера —
        "open" (по умолчанию, полная карточка тикера с ✏️/🗑/🔔/⬅️, вход через "💼 Мои тикеры")
        "alerts" (сразу меню оповещений конкретного тикера, вход через "⚙️ Настройки")
    back_callback: готовый packed callback_data для кнопки "⬅️ Назад".
        Если не передан — используется закрытие меню тикеров (поведение по умолчанию).
    '''
    builder = InlineKeyboardBuilder()
    for ticker_id, symbol in tickers:
        builder.row(InlineKeyboardButton(
            text=symbol,
            callback_data=TickerCB(action=ticker_action, id=ticker_id).pack()
        ))
    builder.row(InlineKeyboardButton(
        text="➕ Добавить тикер",
        callback_data=TickerCB(action="add").pack()
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=back_callback or TickerCB(action="close").pack()
    ))
    return builder.as_markup()


def ticker_card_keyboard(ticker_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="✏️ Изменить тикер",
        callback_data=TickerCB(action="edit_start", id=ticker_id).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="🗑 Удалить тикер",
        callback_data=TickerCB(action="delete_ask", id=ticker_id).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="🔔 Настроить оповещения",
        callback_data=TickerCB(action="alerts", id=ticker_id).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Назад к тикерам",
        callback_data=TickerCB(action="list").pack()
    ))
    return builder.as_markup()


def edit_cancel_keyboard(ticker_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=TickerCB(action="edit_cancel", id=ticker_id).pack()
    ))
    return builder.as_markup()


def delete_confirm_keyboard(ticker_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить",
                              callback_data=TickerCB(action="delete_yes", id=ticker_id).pack()),
        InlineKeyboardButton(text="❌ Отмена",
                              callback_data=TickerCB(action="delete_no", id=ticker_id).pack()),
    )
    return builder.as_markup()


def alerts_menu_keyboard(ticker_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="⏱ Периодическое оповещение",
        callback_data=TickerCB(action="periodic_menu", id=ticker_id).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="📈 Изменение цены",
        callback_data=TickerCB(action="change_menu", id=ticker_id).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="📋 Мои оповещения",
        callback_data=TickerCB(action="alerts_summary", id=ticker_id).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=TickerCB(action="open", id=ticker_id).pack()
    ))
    return builder.as_markup()


def periodic_menu_keyboard(ticker_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes in ALLOWED_PERIODIC_MINUTES:
        builder.row(InlineKeyboardButton(
            text=f"{minutes} минут",
            callback_data=PeriodicCB(id=ticker_id, minutes=minutes).pack()
        ))
    builder.row(InlineKeyboardButton(
        text="🔕 Выключить",
        callback_data=PeriodicCB(id=ticker_id, minutes=0).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=TickerCB(action="alerts", id=ticker_id).pack()
    ))
    return builder.as_markup()


def change_percent_menu_keyboard(ticker_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row = []
    for value in PRESET_PERCENTS:
        row.append(InlineKeyboardButton(
            text=f"{value}%",
            callback_data=PercentCB(id=ticker_id, value=value).pack()
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(
        text="✏️ Свой процент",
        callback_data=TickerCB(action="change_custom", id=ticker_id).pack()
    ))
    builder.row(InlineKeyboardButton(
        text="🔕 Выключить",
        callback_data=PercentCB(id=ticker_id, value="off").pack()
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=TickerCB(action="alerts", id=ticker_id).pack()
    ))
    return builder.as_markup()


def change_custom_cancel_keyboard(ticker_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=TickerCB(action="change_cancel", id=ticker_id).pack()
    ))
    return builder.as_markup()


def add_ticker_cancel_keyboard() -> InlineKeyboardMarkup:
    '''Кнопка отмены при вводе тикера на добавление (без привязки к конкретному ticker_id).'''
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="↩️ Отмена",
        callback_data=TickerCB(action="add_cancel").pack()
    ))
    return builder.as_markup()


def settings_keyboard(notifications_enabled: bool, hourly_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    notif_label = "🔔 Все уведомления: ✅ ВКЛ" if notifications_enabled else "🔔 Все уведомления: 🔕 ВЫКЛ"
    hourly_label = "⏰ Ежечасные обновления: ✅ ВКЛ" if hourly_enabled else "⏰ Ежечасные обновления: 🔕 ВЫКЛ"
    builder.row(InlineKeyboardButton(
        text=notif_label,
        callback_data=SettingsCB(action="toggle_notifications").pack()
    ))
    builder.row(InlineKeyboardButton(
        text=hourly_label,
        callback_data=SettingsCB(action="toggle_hourly").pack()
    ))
    builder.row(InlineKeyboardButton(
        text="🔧 Настроить оповещения тикера",
        callback_data=SettingsCB(action="open_tickers").pack()
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=SettingsCB(action="back").pack()
    ))
    return builder.as_markup()


def _symbol_icon(symbol: str) -> str:
    #Больше не используется в списке тикеров (по запросу убраны иконки),
    #оставлено на случай использования в другом месте UI в будущем.
    icons = {"BTC": "₿", "ETH": "Ξ", "SOL": "◎"}
    for base, icon in icons.items():
        if symbol.startswith(base):
            return icon
    return "🔸"
