import asyncio
import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com/api/v3/ticker/price"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=5)


async def get_ticker_price(symbol: str) -> float | None:
    '''
    Получает актуальную цену одного тикера с Binance.
    Используется в том числе для валидации: существует ли такая пара на бирже.
    Аргументы:
        symbol - тикер в формате BTCUSDT
    Возвращает:
        float с ценой, либо None если тикер не найден или произошла ошибка запроса
    '''
    params = {"symbol": symbol}
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(BASE_URL, params=params) as response:
                #Binance отдает 400 с кодом -1121, если тикер не существует
                if response.status != 200:
                    return None
                data = await response.json()
                return float(data["price"])
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError) as e:
        logger.warning(f"Ошибка при запросе цены к Binance API ({symbol}): {e}")
        return None


async def get_ticker_prices(symbols: list[str]) -> dict[str, float]:
    '''
    Получает актуальные цены сразу для списка тикеров одним запросом
    (используется, например, для показа списка "Мои тикеры").
    Аргументы:
        symbols - список тикеров в формате ['BTCUSDT', 'ETHUSDT']
    Возвращает:
        Словарь {symbol: price}. Тикеры, которые не удалось получить, в словарь не попадают.
    '''
    if not symbols:
        return {}

    #Binance ожидает список тикеров как JSON-строку в query-параметре symbols
    params = {"symbols": json.dumps(symbols).replace(" ", "")}
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(BASE_URL, params=params) as response:
                if response.status != 200:
                    return {}
                data = await response.json()
                return {item["symbol"]: float(item["price"]) for item in data}
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError, TypeError) as e:
        logger.warning(f"Ошибка при батч-запросе цен к Binance API: {e}")
        return {}
