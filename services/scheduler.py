'''
Централизованный background-планировщик уведомлений.

Один asyncio-цикл, тикающий раз в CHECK_INTERVAL секунд, вместо отдельного
таска/цикла на каждого пользователя или каждый тикер. На каждый тик:

1. Собираем все тикеры с включённым периодическим оповещением и все тикеры
   с включённым оповещением по % — объединяем символы и делаем ОДИН
   batch-запрос цен к бирже (get_ticker_prices), чтобы не долбить API
   отдельным запросом на каждый тикер/пользователя.
2. Периодические: если прошло >= periodic_minutes с последней отправки — шлём.
3. По изменению цены: если |текущая - baseline| / baseline * 100 >= change_percent —
   шлём и переустанавливаем baseline на текущую цену (защита от повторного спама
   одним и тем же событием).
4. Почасовые: для каждого юзера с тикерами, если прошло >= delay_time секунд
   с последней отправки почасового дайджеста — шлём сводку по всем его тикерам.

Запускается одним asyncio.create_task(...) при старте бота и корректно
завершается при остановке (task.cancel() перехватывается через CancelledError).
'''
import asyncio
import datetime
import logging

from aiogram import Bot

from db_main.database import (
    get_active_periodic_tickers, get_active_change_tickers,
    update_periodic_sent, update_baseline_price,
    get_users_for_hourly_digest, update_hourly_sent,
)
from services.binance_api import get_ticker_prices

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 60  # секунд между тиками планировщика


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _now_str() -> str:
    return f'{_now()}'


def _parse_dt(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _seconds_since(value: str | None) -> float:
    dt = _parse_dt(value)
    if dt is None:
        #Если метки времени ещё не было — считаем, что интервал уже прошёл
        return float("inf")
    return (_now() - dt).total_seconds()


def format_price(price: float) -> str:
    return f"{price:,.2f}".replace(",", " ")


async def _check_periodic(bot: Bot, prices: dict[str, float]):
    tickers = await get_active_periodic_tickers()
    for ticker in tickers:
        if _seconds_since(ticker["last_periodic_sent"]) < ticker["periodic_minutes"] * 60:
            continue

        price = prices.get(ticker["user_symbol"])
        if price is None:
            continue

        try:
            await bot.send_message(
                ticker["user_id"],
                f"⏱ <b>{ticker['user_symbol']}</b>\n\n{format_price(price)} USDT",
                parse_mode="HTML",
            )
            await update_periodic_sent(ticker["id"], _now_str())
        except Exception as e:
            logger.warning(f"Не удалось отправить периодическое оповещение user={ticker['user_id']}: {e}")


async def _check_change_percent(bot: Bot, prices: dict[str, float]):
    tickers = await get_active_change_tickers()
    for ticker in tickers:
        price = prices.get(ticker["user_symbol"])
        baseline = ticker["baseline_price"]
        if price is None or not baseline:
            continue

        change_pct = (price - baseline) / baseline * 100
        if abs(change_pct) < ticker["change_percent"]:
            continue

        direction = "📈" if change_pct > 0 else "📉"
        sign = "+" if change_pct > 0 else ""
        try:
            await bot.send_message(
                ticker["user_id"],
                (
                    f"🔔 <b>{ticker['user_symbol']}</b>\n\n"
                    f"{direction} Цена изменилась более чем на {ticker['change_percent']}%.\n\n"
                    f"Было:\n{format_price(baseline)} USDT\n\n"
                    f"Сейчас:\n{format_price(price)} USDT\n\n"
                    f"Изменение:\n{sign}{change_pct:.2f}%"
                ),
                parse_mode="HTML",
            )
            #Переустанавливаем baseline на текущую цену, чтобы не спамить
            #тем же самым событием каждый следующий тик
            await update_baseline_price(ticker["id"], price)
        except Exception as e:
            logger.warning(f"Не удалось отправить %-оповещение user={ticker['user_id']}: {e}")


async def _check_hourly_digest(bot: Bot):
    users = await get_users_for_hourly_digest()
    for user in users:
        if _seconds_since(user["last_hourly_sent"]) < user["delay_time"]:
            continue

        prices = await get_ticker_prices(user["tickers"])
        if not prices:
            continue

        text = "⏰ <b>Ежечасное обновление</b>\n\n"
        for symbol in user["tickers"]:
            price = prices.get(symbol)
            price_text = f"{format_price(price)} USDT" if price is not None else "цена недоступна ⚠️"
            text += f"{symbol}\n{price_text}\n\n"

        try:
            await bot.send_message(user["telegram_id"], text.strip(), parse_mode="HTML")
            await update_hourly_sent(user["telegram_id"], _now_str())
        except Exception as e:
            logger.warning(f"Не удалось отправить почасовой дайджест user={user['telegram_id']}: {e}")


async def _tick(bot: Bot):
    periodic_tickers = await get_active_periodic_tickers()
    change_tickers = await get_active_change_tickers()

    symbols = {t["user_symbol"] for t in periodic_tickers} | {t["user_symbol"] for t in change_tickers}
    prices = await get_ticker_prices(list(symbols)) if symbols else {}

    await _check_periodic(bot, prices)
    await _check_change_percent(bot, prices)
    await _check_hourly_digest(bot)


async def run_scheduler(bot: Bot):
    '''
    Основной цикл планировщика. Запускать через asyncio.create_task(run_scheduler(bot)).
    Корректно завершается по CancelledError при остановке бота.
    '''
    logger.info("Notification scheduler started")
    try:
        while True:
            try:
                await _tick(bot)
            except Exception as e:
                #Ошибка в одном тике не должна убивать весь планировщик
                logger.exception(f"Ошибка в тике планировщика уведомлений: {e}")
            await asyncio.sleep(CHECK_INTERVAL)
    except asyncio.CancelledError:
        logger.info("Notification scheduler stopped")
        raise
