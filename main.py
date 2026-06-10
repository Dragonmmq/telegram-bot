import asyncio
import os
import time
import sqlite3
import logging
import html as html_lib

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# ======================================================
# ENV
# ======================================================

def get_env(name: str, default=None, required=False):
    value = os.getenv(name, default)

    if required and (not value or str(value).strip() == ""):
        raise ValueError(f"❌ ENV '{name}' не найден")

    return str(value).strip() if value else value


TOKEN = (
    get_env("TELEGRAM_BOT_TOKEN")
    or get_env("BOT_TOKEN")
)

if not TOKEN:
    raise ValueError("❌ Не найден TELEGRAM_BOT_TOKEN или BOT_TOKEN")

PORT = int(get_env("PORT", 10000))

# ======================================================
# НАСТРОЙКИ
# ======================================================

ADMINS = [
    1206582825
]

CHANNEL_ID = -1002168740058

SPAM_DELAY = 3

BAD_WORDS = [
    # "слово"
]

# ======================================================
# LOGGING
# ======================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logging.info("🚀 Бот запускается...")

# ======================================================
# BOT
# ======================================================

bot = Bot(
    token=TOKEN,
    parse_mode=ParseMode.HTML
)

dp = Dispatcher()

# ======================================================
# DATABASE
# ======================================================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    text TEXT,
    media_type TEXT,
    file_id TEXT,
    forwarded INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cursor.execute("""
INSERT OR IGNORE INTO settings (key, value)
VALUES ('forwarding', '1')
""")

conn.commit()

# ======================================================
# HELPERS
# ======================================================

def get_forwarding():
    cursor.execute(
        "SELECT value FROM settings WHERE key='forwarding'"
    )
    row = cursor.fetchone()

    return row[0] == "1" if row else True


def set_forwarding(value: bool):
    cursor.execute(
        "UPDATE settings SET value=? WHERE key='forwarding'",
        ("1" if value else "0",)
    )
    conn.commit()


def is_bad(text: str):
    if not text:
        return False

    text = text.lower()

    return any(word in text for word in BAD_WORDS)


def admin_only(user_id):
    return user_id in ADMINS


def forwarding_kb():
    enabled = get_forwarding()

    text = (
        "🟢 Выключить пересылку"
        if enabled
        else "🔴 Включить пересылку"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data="toggle_forward"
                )
            ]
        ]
    )

# ======================================================
# STATES
# ======================================================

class ReplyState(StatesGroup):
    waiting = State()


class BroadcastState(StatesGroup):
    waiting = State()

# ======================================================
# ANTI SPAM
# ======================================================

last_messages = {}

# ======================================================
# COMMANDS
# ======================================================

@dp.message(CommandStart())
async def start(message: types.Message):

    user = message.from_user

    cursor.execute("""
    INSERT OR IGNORE INTO users
    (user_id, username, full_name)
    VALUES (?, ?, ?)
    """, (
        user.id,
        user.username,
        user.full_name
    ))

    conn.commit()

    me = await bot.get_me()

    await message.answer(
        f"""
👋 <b>Привет!</b>

📩 Сюда можно писать анонимно

🔗 Твоя ссылка:
<code>https://t.me/{me.username}</code>

✉️ Все сообщения полностью анонимны
"""
    )


@dp.message(Command("help"))
async def help_cmd(message: types.Message):

    if not admin_only(message.from_user.id):
        return

    await message.answer(
        """
⚙️ Команды админа:

/stats — статистика
/forward — пересылка
/broadcast — рассылка
/users — пользователи
/ping — проверка
"""
    )


@dp.message(Command("ping"))
async def ping_cmd(message: types.Message):

    if not admin_only(message.from_user.id):
        return

    await message.answer("🏓 Pong")


@dp.message(Command("users"))
async def users_cmd(message: types.Message):

    if not admin_only(message.from_user.id):
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]

    await message.answer(
        f"👥 Пользователей: <b>{total}</b>"
    )


@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):

    if not admin_only(message.from_user.id):
        return

    cursor.execute("SELECT COUNT(*) FROM messages")
    total_messages = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    await message.answer(
        f"""
📊 Статистика

👥 Пользователей: <b>{total_users}</b>
📩 Сообщений: <b>{total_messages}</b>
"""
    )


@dp.message(Command("forward"))
async def forward_cmd(message: types.Message):

    if not admin_only(message.from_user.id):
        return

    status = (
        "🟢 Включена"
        if get_forwarding()
        else "🔴 Выключена"
    )

    await message.answer(
        f"📡 Пересылка сейчас: {status}",
        reply_markup=forwarding_kb()
    )

# ======================================================
# FORWARD TOGGLE
# ======================================================

@dp.callback_query(F.data == "toggle_forward")
async def toggle_forward(callback: types.CallbackQuery):

    if not admin_only(callback.from_user.id):
        return await callback.answer(
            "Нет доступа",
            show_alert=True
        )

    current = get_forwarding()

    set_forwarding(not current)

    await callback.message.edit_text(
        "⚙️ Настройки обновлены",
        reply_markup=forwarding_kb()
    )

    await callback.answer()

# ======================================================
# REPLY SYSTEM
# ======================================================

@dp.callback_query(F.data.startswith("reply_"))
async def reply_callback(
    callback: types.CallbackQuery,
    state: FSMContext
):

    user_id = int(callback.data.split("_")[1])

    await state.update_data(target=user_id)

    await state.set_state(ReplyState.waiting)

    await callback.message.answer(
        "✍️ Напиши ответ:"
    )

    await callback.answer()


@dp.message(ReplyState.waiting)
async def reply_send(
    message: types.Message,
    state: FSMContext
):

    data = await state.get_data()

    user_id = data["target"]

    try:

        await bot.send_message(
            user_id,
            f"""
📬 <b>Вам ответили анонимно</b>

<blockquote expandable>
{html_lib.escape(message.text)}
</blockquote>
"""
        )

        await message.answer(
            "✅ Ответ отправлен"
        )

    except Exception as e:

        logging.error(e)

        await message.answer(
            "❌ Ошибка отправки"
        )

    await state.clear()

# ======================================================
# BROADCAST
# ======================================================

@dp.message(Command("broadcast"))
async def broadcast_cmd(
    message: types.Message,
    state: FSMContext
):

    if not admin_only(message.from_user.id):
        return

    await state.set_state(BroadcastState.waiting)

    await message.answer(
        "📢 Отправь сообщение для рассылки"
    )


@dp.message(BroadcastState.waiting)
async def broadcast_send(
    message: types.Message,
    state: FSMContext
):

    cursor.execute(
        "SELECT user_id FROM users"
    )

    users = cursor.fetchall()

    success = 0
    failed = 0

    for user in users:

        uid = user[0]

        try:

            if message.text:

                await bot.send_message(
                    uid,
                    f"""
📢 <b>Рассылка</b>

<blockquote expandable>
{html_lib.escape(message.text)}
</blockquote>
"""
                )

            elif message.photo:

                await bot.send_photo(
                    uid,
                    message.photo[-1].file_id,
                    caption=message.caption or "📢 Рассылка"
                )

            elif message.video:

                await bot.send_video(
                    uid,
                    message.video.file_id,
                    caption=message.caption or "📢 Рассылка"
                )

            success += 1

            await asyncio.sleep(0.05)

        except Exception:
            failed += 1

    await message.answer(
        f"""
✅ Рассылка завершена

🟢 Успешно: {success}
🔴 Ошибок: {failed}
"""
    )

    await state.clear()

# ======================================================
# MAIN HANDLER
# ======================================================

@dp.message()
async def handle_message(message: types.Message):

    if message.text and message.text.startswith("/"):
        return

    user = message.from_user

    cursor.execute("""
    INSERT OR IGNORE INTO users
    (user_id, username, full_name)
    VALUES (?, ?, ?)
    """, (
        user.id,
        user.username,
        user.full_name
    ))

    conn.commit()

    now = time.time()

    if (
        user.id in last_messages
        and now - last_messages[user.id] < SPAM_DELAY
    ):
        return await message.answer(
            "⏳ Подожди немного"
        )

    last_messages[user.id] = now

    if message.text and is_bad(message.text):

        return await message.answer(
            "🚫 Сообщение запрещено"
        )

    media_type = None
    file_id = None
    text = message.text or message.caption or ""

    if message.photo:
        media_type = "photo"
        file_id = message.photo[-1].file_id

    elif message.video:
        media_type = "video"
        file_id = message.video.file_id

    elif message.voice:
        media_type = "voice"
        file_id = message.voice.file_id

    elif message.video_note:
        media_type = "video_note"
        file_id = message.video_note.file_id

    elif message.sticker:
        media_type = "sticker"
        file_id = message.sticker.file_id

    # ==================================================
    # CHANNEL
    # ==================================================

    if get_forwarding():

        try:

            if text:

                await bot.send_message(
                    CHANNEL_ID,
                    f"""
💬 <b>Анонимное сообщение</b>

<blockquote expandable>
{html_lib.escape(text)}
</blockquote>
"""
                )

            elif media_type == "photo":

                await bot.send_photo(
                    CHANNEL_ID,
                    file_id,
                    caption="📸 Анонимное фото"
                )

            elif media_type == "video":

                await bot.send_video(
                    CHANNEL_ID,
                    file_id,
                    caption="🎥 Анонимное видео"
                )

            elif media_type == "voice":

                await bot.send_voice(
                    CHANNEL_ID,
                    file_id
                )

            elif media_type == "video_note":

                await bot.send_video_note(
                    CHANNEL_ID,
                    file_id
                )

            elif media_type == "sticker":

                await bot.send_sticker(
                    CHANNEL_ID,
                    file_id
                )

        except Exception as e:
            logging.error(e)

    # ==================================================
    # ADMIN MESSAGE
    # ==================================================

    username = (
        f"@{user.username}"
        if user.username
        else "нет"
    )

    admin_text = f"""
📩 <b>Новое сообщение</b>

👤 {html_lib.escape(user.full_name)}
🔗 {username}
🆔 <code>{user.id}</code>

"""

    if text:
        admin_text += f"""
<blockquote expandable>
{html_lib.escape(text)}
</blockquote>
"""
    else:
        admin_text += f"📎 {media_type}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Ответить",
                    callback_data=f"reply_{user.id}"
                )
            ]
        ]
    )

    for admin in ADMINS:

        try:

            if media_type == "photo":

                await bot.send_photo(
                    admin,
                    file_id,
                    caption=admin_text,
                    reply_markup=kb
                )

            elif media_type == "video":

                await bot.send_video(
                    admin,
                    file_id,
                    caption=admin_text,
                    reply_markup=kb
                )

            elif media_type == "voice":

                await bot.send_voice(
                    admin,
                    file_id
                )

                await bot.send_message(
                    admin,
                    admin_text,
                    reply_markup=kb
                )

            elif media_type == "video_note":

                await bot.send_video_note(
                    admin,
                    file_id
                )

                await bot.send_message(
                    admin,
                    admin_text,
                    reply_markup=kb
                )

            elif media_type == "sticker":

                await bot.send_sticker(
                    admin,
                    file_id
                )

                await bot.send_message(
                    admin,
                    admin_text,
                    reply_markup=kb
                )

            else:

                await bot.send_message(
                    admin,
                    admin_text,
                    reply_markup=kb
                )

        except Exception as e:
            logging.error(e)

    # ==================================================
    # SAVE MESSAGE
    # ==================================================

    cursor.execute("""
    INSERT INTO messages
    (user_id, text, media_type, file_id)
    VALUES (?, ?, ?, ?)
    """, (
        user.id,
        text,
        media_type,
        file_id
    ))

    conn.commit()

    await message.answer(
        "✅ Сообщение отправлено анонимно"
    )

# ======================================================
# BOT COMMANDS
# ======================================================

async def set_commands():

    commands = [
        BotCommand(
            command="start",
            description="Запустить бота"
        ),
        BotCommand(
            command="help",
            description="Команды"
        ),
        BotCommand(
            command="stats",
            description="Статистика"
        ),
        BotCommand(
            command="broadcast",
            description="Рассылка"
        ),
        BotCommand(
            command="forward",
            description="Пересылка"
        )
    ]

    await bot.set_my_commands(commands)

# ======================================================
# WEB SERVER
# ======================================================

async def health(request):
    return web.Response(text="OK")


async def start_web():

    app = web.Application()

    app.router.add_get("/", health)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

# ======================================================
# MAIN
# ======================================================

async def main():

    logging.info("🌐 WEB SERVER START")

    await start_web()

    logging.info("🤖 BOT START")

    await set_commands()

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    await dp.start_polling(bot)

# ======================================================
# START
# ======================================================

if __name__ == "__main__":
    asyncio.run(main())
