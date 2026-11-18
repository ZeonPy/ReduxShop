"""Клиент API SMSFast.

SMSFast поддерживает протокол SMS-Activate: все запросы идут GET-ом на
`handler_api.php` с параметром `api_key`. Клиент не хранит ключ в логах и
возвращает типизированные результаты, чтобы хендлеры не разбирали строки.

Документация: https://smsfast.io/doc (API активации).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass
from typing import Any

import aiohttp

from app.runtime import RuntimeConfig

logger = logging.getLogger(__name__)

PROVIDER_NAME = "smsfast"

SMSFAST_SERVICES: dict[str, str] = {
    "ot": "Любой другой",
    "tg": "Telegram",
    "wa": "WhatsApp",
    "go": "Google (YouTube, Gmail)",
    "lf": "TikTok / Douyin",
    "ds": "Discord",
    "am": "Amazon",
    "mt": "Steam",
    "wx": "Apple",
}

DEFAULT_SERVICE = "ot"

# Статусы, которые SMSFast может вернуть в getStatus.
STATUS_WAITING = "waiting"
STATUS_RETRY = "retry"
STATUS_OK = "ok"
STATUS_CANCEL = "cancel"


class SmsFastError(RuntimeError):
    """Провайдер вернул ошибку или недоступен."""


class SmsFastAuthError(SmsFastError):
    """Неверный API-ключ."""


class SmsFastBalanceError(SmsFastError):
    """На балансе SMSFast недостаточно средств."""


class SmsFastNoNumbersError(SmsFastError):
    """Для страны/сервиса нет свободных номеров."""


@dataclass(frozen=True, slots=True)
class Activation:
    activation_id: str
    phone: str


@dataclass(frozen=True, slots=True)
class SmsStatus:
    state: str
    code: str = ""
    raw: str = ""


@dataclass(frozen=True, slots=True)
class ProviderPrice:
    cost: float
    count: int = 0

    @property
    def cost_rub(self) -> int:
        """Закупка в целых рублях (вверх), чтобы не уйти в минус."""
        return max(1, math.ceil(self.cost))


_ERROR_MESSAGES: dict[str, str] = {
    "BAD_KEY": "SMSFast отклонил API-ключ.",
    "BAD_ACTION": "SMSFast не понял действие.",
    "BAD_SERVICE": "SMSFast не знает такой сервис.",
    "WRONG_SERVICE": "SMSFast не знает такой сервис.",
    "BAD_COUNTRY": "SMSFast не знает такую страну.",
    "WRONG_COUNTRY": "SMSFast не знает такую страну.",
    "NO_BALANCE": "На балансе SMSFast недостаточно средств.",
    "NO_NUMBERS": "У SMSFast нет свободных номеров для этого направления.",
    "BANNED": "Аккаунт SMSFast заблокирован.",
    "ERROR": "SMSFast вернул ошибку.",
    "BAD_STATUS": "SMSFast не принял статус активации.",
}


def describe_error(code: str) -> str:
    return _ERROR_MESSAGES.get(code.strip(), f"SMSFast: {code.strip()}")


def parse_balance(raw: str) -> float:
    text = raw.strip()
    if text == "BAD_KEY":
        raise SmsFastAuthError(describe_error(text))
    if not text.startswith("ACCESS_BALANCE:"):
        raise SmsFastError(describe_error(text))
    try:
        return float(text.split(":", 1)[1].replace(",", "."))
    except ValueError as exc:
        raise SmsFastError(f"SMSFast вернул непонятный баланс: {text}") from exc


def parse_activation(raw: str) -> Activation:
    text = raw.strip()
    if text.startswith("ACCESS_NUMBER:"):
        parts = text.split(":", 2)
        if len(parts) == 3 and parts[1].strip():
            return Activation(parts[1].strip(), parts[2].strip())
    raise SmsFastError(describe_error(text))


def parse_status(raw: str) -> SmsStatus:
    text = raw.strip()
    if text == "STATUS_WAIT_CODE":
        return SmsStatus(STATUS_WAITING, raw=text)
    if text.startswith("STATUS_WAIT_RETRY:"):
        return SmsStatus(STATUS_RETRY, text.split(":", 1)[1].strip(), text)
    if text.startswith("STATUS_OK:"):
        return SmsStatus(STATUS_OK, text.split(":", 1)[1].strip(), text)
    if text == "STATUS_CANCEL":
        return SmsStatus(STATUS_CANCEL, raw=text)
    raise SmsFastError(describe_error(text))


def _parse_cost(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def parse_prices(payload: Any, service: str | None = None) -> dict[int, ProviderPrice]:
    """Разбирает ответ getPrices в `{country_id: ProviderPrice}`.

    Поддерживаются оба известных формата:
    `{"2": {"ot": {"cost": 12.5, "count": 10}}}` и
    `{"2": {"cost": 12.5, "count": 10}}`.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SmsFastError("SMSFast вернул не JSON в getPrices") from exc

    if isinstance(payload, dict):
        for wrapper in ("data", "prices", "result"):
            nested = payload.get(wrapper)
            if isinstance(nested, dict):
                payload = nested
                break
        if payload.get("status") in {"error", "false", False}:
            raise SmsFastError(str(payload.get("message") or "SMSFast: ошибка цен"))

    if not isinstance(payload, dict):
        raise SmsFastError("SMSFast вернул неизвестный формат цен")

    result: dict[int, ProviderPrice] = {}
    for raw_country, services in payload.items():
        try:
            country_id = int(raw_country)
        except (TypeError, ValueError):
            continue
        if not isinstance(services, dict):
            continue

        entry: Any = services
        if "cost" in services:
            # Плоский формат: страна сразу содержит цену сервиса.
            pass
        elif service:
            entry = services.get(service)
            if entry is None and len(services) == 1:
                entry = next(iter(services.values()))
        elif any(isinstance(value, dict) and "cost" in value for value in services.values()):
            # Без фильтра берём самый дешёвый доступный сервис.
            candidates = [
                value
                for value in services.values()
                if isinstance(value, dict) and value.get("count", 1)
            ]
            entry = min(
                candidates,
                key=lambda value: _parse_cost(value.get("cost")) or float("inf"),
                default=None,
            )
        if not isinstance(entry, dict):
            continue

        cost = _parse_cost(entry.get("cost"))
        if cost is None or cost <= 0:
            continue
        count = _parse_count(entry.get("count", entry.get("physicalCount", 0)))
        result[country_id] = ProviderPrice(cost=cost, count=count)
    return result


class SmsFastClient:
    """Тонкая async-обёртка над API активаций SMSFast."""

    def __init__(self, config: RuntimeConfig, timeout: int = 30) -> None:
        self._config = config
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self._config.smsfast_ready

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=self._timeout,
                    headers={"User-Agent": "ReduxShop/2.2 (+https://t.me/reduxstore)"},
                )
            return self._session

    async def close(self) -> None:
        async with self._lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
            self._session = None

    async def _request(self, action: str, **params: Any) -> str:
        if not self.configured:
            raise SmsFastAuthError("SMSFast не настроен: добавь API-ключ.")
        query: dict[str, Any] = {
            "api_key": self._config.smsfast_api_key.strip(),
            "action": action,
        }
        query.update({key: value for key, value in params.items() if value is not None})
        session = await self._get_session()
        try:
            async with session.get(
                self._config.smsfast_base_url.strip(), params=query
            ) as response:
                body = (await response.text()).strip()
                if response.status >= 400:
                    logger.warning(
                        "SMSFast HTTP %s на %s: %s", response.status, action, body[:200]
                    )
                    raise SmsFastError(f"SMSFast HTTP {response.status}")
                return body
        except aiohttp.ClientError as exc:
            logger.warning("SMSFast недоступен (%s): %s", action, exc)
            raise SmsFastError("SMSFast временно недоступен.") from exc

    async def balance(self) -> float:
        raw = await self._request("getBalance")
        if raw == "BAD_KEY":
            raise SmsFastAuthError(describe_error(raw))
        return parse_balance(raw)

    async def get_number(self, service: str, country: int) -> Activation:
        raw = await self._request(
            "getNumber", service=service, country=country
        )
        if raw == "NO_NUMBERS":
            raise SmsFastNoNumbersError(describe_error(raw))
        if raw == "NO_BALANCE":
            raise SmsFastBalanceError(describe_error(raw))
        if raw == "BAD_KEY":
            raise SmsFastAuthError(describe_error(raw))
        return parse_activation(raw)

    async def get_status(self, activation_id: str) -> SmsStatus:
        raw = await self._request("getStatus", id=activation_id)
        return parse_status(raw)

    async def set_status(self, activation_id: str, status: int) -> str:
        raw = await self._request("setStatus", id=activation_id, status=status)
        if raw.startswith("ACCESS_") or raw in {"OK", "SUCCESS"}:
            return raw
        raise SmsFastError(describe_error(raw))

    async def prices(self, service: str | None = None) -> dict[int, ProviderPrice]:
        params: dict[str, Any] = {}
        if service:
            params["service"] = service
        raw = await self._request("getPrices", **params)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SmsFastError(describe_error(raw)) from exc
        return parse_prices(payload, service)

    async def countries(self) -> dict[int, str]:
        """Возвращает `{country_id: name}`. Ошибки справочника не критичны."""
        raw = await self._request("getCountries")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        data = payload.get("countries", payload) if isinstance(payload, dict) else {}
        result: dict[int, str] = {}
        if isinstance(data, dict):
            for key, value in data.items():
                try:
                    country_id = int(key)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    name = value.get("name") or value.get("country") or ""
                else:
                    name = str(value)
                if name:
                    result[country_id] = str(name)
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                try:
                    country_id = int(item.get("id") or item.get("api_id"))
                except (TypeError, ValueError):
                    continue
                name = item.get("name") or item.get("country") or ""
                if name:
                    result[country_id] = str(name)
        return result
