"""Обращения в поддержку."""

from __future__ import annotations

from app.constants import TicketSender
from app.db import Database
from app.models import Ticket


class TicketService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def open_for(self, user_id: int) -> Ticket:
        return await self._db.tickets.get_or_create_open(user_id)

    async def current(self, user_id: int) -> Ticket | None:
        return await self._db.tickets.find_open(user_id)

    async def relay_user_message(self, user_id: int, text: str) -> Ticket:
        ticket = await self.open_for(user_id)
        await self._db.tickets.add_message(ticket.id, TicketSender.USER, text)
        return ticket

    async def add_admin_reply(self, ticket_id: int, text: str) -> None:
        await self._db.tickets.add_message(ticket_id, TicketSender.ADMIN, text)

    async def close(self, ticket_id: int) -> bool:
        return await self._db.tickets.close(ticket_id)
