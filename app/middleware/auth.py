"""Authentication / user-registration middleware."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database import get_session
from app.services.user import get_or_create_user, reset_daily_counts_if_needed
from app.utils.logger import logger


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None: return await handler(event, data)
        try:
            async with get_session() as session:
                user = await get_or_create_user(session, telegram_id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name, last_name=tg_user.last_name)
                await reset_daily_counts_if_needed(session, user)
            data["db_user"] = user
        except Exception as exc:
            logger.error("auth_middleware_error", error=str(exc), exc_info=True)
        return await handler(event, data)
