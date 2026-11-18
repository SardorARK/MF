"""
Бот-зазывала для Telegram (aiogram 3.x).

Команда /r в группе тегает всех известных боту участников и созывает их.
Можно добавить свой текст:  /r Го играть в мафию!

Запуск:
    pip install aiogram
    вставьте токен в строку BOT_TOKEN ниже
    python main.py
"""

import asyncio
import html
import json
import logging
import os
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.filters.chat_member_updated import (
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
    ChatMemberUpdatedFilter,
)
from aiogram.types import ChatMemberUpdated, Message, User

# ---------------------------- НАСТРОЙКИ ----------------------------
BOT_TOKEN = "9165282045:AAG2N3oOoV4rwjXX6x_iQrtbV3483XYOrm8"  # замените текст в кавычках на свой токен
DATA_FILE = Path(__file__).with_name("members.json")  # тут хранятся участники
BATCH_SIZE = 5          # сколько людей тегать в одном сообщении
BATCH_DELAY = 1.1       # пауза между сообщениями (лимит Telegram ~1 сообщение/сек в чат)
COOLDOWN = 30           # секунд между вызовами /r в одной группе
MAX_NAME_LEN = 32       # максимальная длина имени в упоминании
# --------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zazyvala")

router = Router()
GROUPS = {ChatType.GROUP, ChatType.SUPERGROUP}


class MemberStore:
    """Хранилище участников групп: {chat_id: {user_id: имя}} в JSON-файле."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.exception("Не удалось прочитать %s, начинаем с пустого", self.path)
                self.data = {}

    def _write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # атомарная замена, файл не повредится при сбое

    async def save(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write)

    async def add(self, chat_id: int, user: User) -> None:
        if user.is_bot:
            return
        chat = self.data.setdefault(str(chat_id), {})
        name = user.full_name[:MAX_NAME_LEN] or "Участник"
        if chat.get(str(user.id)) != name:
            chat[str(user.id)] = name
            await self.save()

    async def remove(self, chat_id: int, user_id: int) -> None:
        chat = self.data.get(str(chat_id), {})
        if chat.pop(str(user_id), None) is not None:
            await self.save()

    def members(self, chat_id: int) -> dict[int, str]:
        return {int(uid): name for uid, name in self.data.get(str(chat_id), {}).items()}


store = MemberStore(DATA_FILE)
last_call: dict[int, float] = {}   # chat_id -> время последнего /r
running: set[int] = set()          # чаты, где /r выполняется прямо сейчас


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


async def safe_send(bot: Bot, chat_id: int, text: str) -> None:
    """Отправка с повтором при лимите Telegram (429)."""
    for _ in range(3):
        try:
            await bot.send_message(chat_id, text)
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramBadRequest:
            log.exception("Не удалось отправить сообщение в чат %s", chat_id)
            return


# ----------------------------- КОМАНДЫ -----------------------------
@router.message(Command("start", "help"), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Я бот-зазывала.\n\n"
        "Добавьте меня в группу и дайте права администратора, "
        "затем пишите <b>/r</b> — я отмечу всех участников.\n"
        "Свой текст: <code>/r Го играть!</code>"
    )


@router.message(Command("r"), F.chat.type == ChatType.PRIVATE)
async def cmd_r_private(message: Message) -> None:
    await message.answer("Эта команда работает только в группах!")


@router.message(Command("r"), F.chat.type.in_(GROUPS))
async def cmd_call(message: Message, command: CommandObject, bot: Bot) -> None:
    chat_id = message.chat.id
    caller = message.from_user

    if chat_id in running:
        return
    wait = COOLDOWN - (time.monotonic() - last_call.get(chat_id, -COOLDOWN))
    if wait > 0:
        await message.reply(f"⏳ Подождите ещё {int(wait) + 1} сек.")
        return

    running.add(chat_id)
    try:
        last_call[chat_id] = time.monotonic()

        # Запоминаем вызывающего и всех администраторов (их Telegram отдаёт боту)
        if caller:
            await store.add(chat_id, caller)
        try:
            for admin in await bot.get_chat_administrators(chat_id):
                await store.add(chat_id, admin.user)
        except TelegramBadRequest:
            log.warning("Не удалось получить список админов чата %s", chat_id)

        members = store.members(chat_id)
        if caller:
            members.pop(caller.id, None)  # самого вызывающего не тегаем

        if not members:
            await message.reply(
                "🤷 Я пока никого не знаю в этой группе. "
                "Пусть участники напишут хоть одно сообщение, "
                "и я их запомню (бот должен быть администратором)."
            )
            return

        caller_name = html.escape(caller.full_name) if caller else "Кто-то"
        extra = f"\n\n💬 {html.escape(command.args)}" if command.args else ""
        await safe_send(
            bot, chat_id,
            f"📢 <b>{caller_name} созывает всех!</b>{extra}",
        )

        items = [mention(uid, name) for uid, name in members.items()]
        for i in range(0, len(items), BATCH_SIZE):
            await asyncio.sleep(BATCH_DELAY)
            await safe_send(bot, chat_id, "🔔 " + " ".join(items[i:i + BATCH_SIZE]))
    finally:
        running.discard(chat_id)


# ------------------- ЗАПОМИНАНИЕ УЧАСТНИКОВ ГРУППЫ -------------------
@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION), F.chat.type.in_(GROUPS))
async def on_join(event: ChatMemberUpdated) -> None:
    await store.add(event.chat.id, event.new_chat_member.user)


@router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION), F.chat.type.in_(GROUPS))
async def on_leave(event: ChatMemberUpdated) -> None:
    await store.remove(event.chat.id, event.new_chat_member.user.id)


# Этот обработчик должен стоять ПОСЛЕ команд: он ловит все остальные сообщения
@router.message(F.chat.type.in_(GROUPS))
async def remember_members(message: Message) -> None:
    chat_id = message.chat.id
    if message.from_user:
        await store.add(chat_id, message.from_user)
    for user in message.new_chat_members or []:
        await store.add(chat_id, user)
    if message.left_chat_member:
        await store.remove(chat_id, message.left_chat_member.id)


# ------------------------------ ЗАПУСК ------------------------------
async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN.startswith("ВСТАВЬТЕ"):
        raise SystemExit("Вставьте токен бота в строку BOT_TOKEN в начале файла main.py.")

    store.load()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
