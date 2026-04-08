import asyncio
import os
import time
import sqlite3
import logging
import html as html_lib
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

TOKEN = os.environ.get("BOT_TOKEN")
ADMINS = [8394162540]
CHANNEL_ID = -1003285603970
PORT = int(os.environ.get("PORT", 10000))

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ===== БД =====
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    text TEXT,
    media_type TEXT,
    file_id TEXT,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
''')
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('forwarding', '1')")
conn.commit()

def get_forwarding():
    cursor.execute("SELECT value FROM settings WHERE key='forwarding'")
    row = cursor.fetchone()
    return row[0] == "1" if row else True

def set_forwarding(val):
    cursor.execute("UPDATE settings SET value=? WHERE key='forwarding'", (val,))
    conn.commit()

# ===== FSM =====
class ReplyState(StatesGroup):
    waiting = State()

# ===== Антиспам =====
last_msg = {}
SPAM_DELAY = 5

# ===== Кнопки =====
def forward_kb():
    status = get_forwarding()
    text = "🟢 Выключить пересылку" if status else "🔴 Включить пересылку"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="toggle")]]
    )

# ===== Команды =====
@dp.message(CommandStart())
async def start(msg: types.Message):
    me = await bot.get_me()
    await msg.answer(
        f"👋 Привет!\n\n📩 Напиши сюда — сообщение придёт анонимно\n\n"
        f"🔗 Твоя ссылка:\n<code>https://t.me/{me.username}</code>"
    )

@dp.message(Command("forward"))
async def forward_cmd(msg: types.Message):
    if msg.from_user.id not in ADMINS:
        return
    await msg.answer("⚙️ Управление пересылкой", reply_markup=forward_kb())

@dp.callback_query(F.data == "toggle")
async def toggle(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return await cb.answer("Нет доступа", show_alert=True)

    new = not get_forwarding()
    set_forwarding("1" if new else "0")

    await cb.message.edit_text("⚙️ Настройки обновлены", reply_markup=forward_kb())
    await cb.answer()

@dp.callback_query(F.data.startswith("reply_"))
async def reply_handler(cb: types.CallbackQuery, state: FSMContext):
    uid = int(cb.data.split("_")[1])
    await state.update_data(uid=uid)
    await state.set_state(ReplyState.waiting)
    await cb.message.answer("✍️ Напиши ответ")
    await cb.answer()

@dp.message(ReplyState.waiting)
async def send_reply(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        await bot.send_message(data["uid"], f"📬 Ответ:\n\n{msg.text}")
        await msg.answer("✅ Отправлено")
    except:
        await msg.answer("❌ Ошибка")
    await state.clear()

# ===== ГЛАВНЫЙ ОБРАБОТЧИК =====
@dp.message(~F.text.startswith("/") | ~F.text)
async def handle(msg: types.Message):
    user = msg.from_user
    now = time.time()

    if user.id in last_msg and now - last_msg[user.id] < SPAM_DELAY:
        return await msg.answer("⏳ Подожди")

    last_msg[user.id] = now

    text = msg.text or ""
    media_type = None
    file_id = None
    extra = ""

    if msg.photo:
        media_type = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        media_type = "video"
        file_id = msg.video.file_id
    elif msg.sticker:
        media_type = "sticker"
        file_id = msg.sticker.file_id
        extra = msg.sticker.emoji or ""
    elif msg.voice:
        media_type = "voice"
        file_id = msg.voice.file_id
        extra = f"({msg.voice.duration} сек)" if msg.voice.duration else ""
    elif msg.video_note:
        media_type = "video_note"
        file_id = msg.video_note.file_id
        extra = f"({msg.video_note.duration} сек)" if msg.video_note.duration else ""

    # ===== В канал =====
    if get_forwarding():
        try:
            if text:
                await bot.send_message(CHANNEL_ID, f"<blockquote>💬 {html_lib.escape(text)}</blockquote>")
            elif media_type == "photo":
                await bot.send_photo(CHANNEL_ID, file_id, caption="<blockquote>📸 Анонимное фото</blockquote>")
            elif media_type == "video":
                await bot.send_video(CHANNEL_ID, file_id, caption="<blockquote>🎥 Анонимное видео</blockquote>")
            elif media_type == "sticker":
                await bot.send_sticker(CHANNEL_ID, file_id)
            elif media_type == "voice":
                await bot.send_voice(CHANNEL_ID, file_id)
                await bot.send_message(CHANNEL_ID, f"<blockquote>🎤 Голосовое {extra}</blockquote>")
            elif media_type == "video_note":
                await bot.send_video_note(CHANNEL_ID, file_id)
                await bot.send_message(CHANNEL_ID, f"<blockquote>🔄 Кружочек {extra}</blockquote>")
        except Exception as e:
            logging.error(e)

    # ===== Админу =====
    username = f"@{user.username}" if user.username else "Нет юзернейма"
    full_name = html_lib.escape(user.full_name)

    admin_text = (
        f"📩 <b>Анонимное сообщение</b>\n\n"
        f"<b>Имя:</b> {full_name}\n"
        f"<b>Юзернейм:</b> {username}\n"
        f"<b>ID:</b> <code>{user.id}</code>\n\n"
    )

    if text:
        admin_text += html_lib.escape(text)
    elif media_type:
        em = "🎨" if media_type == "sticker" else "🎤" if media_type == "voice" else "🔄"
        admin_text += f"{em} {media_type.replace('_', ' ').title()} {extra}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="↩️ Ответить анонимно", callback_data=f"reply_{user.id}")]]
    )

    for admin in ADMINS:
        try:
            if text or media_type in ["sticker", "voice", "video_note"]:
                await bot.send_message(admin, admin_text, reply_markup=kb)

            if media_type == "photo":
                await bot.send_photo(admin, file_id, caption=admin_text, reply_markup=kb)
            elif media_type == "video":
                await bot.send_video(admin, file_id, caption=admin_text, reply_markup=kb)
            elif media_type == "sticker":
                await bot.send_sticker(admin, file_id)
            elif media_type == "voice":
                await bot.send_voice(admin, file_id)
            elif media_type == "video_note":
                await bot.send_video_note(admin, file_id)

        except Exception as e:
            logging.error(e)

    # ===== БД =====
    db_text = text if text else f"{media_type} {extra}".strip()
    cursor.execute(
        "INSERT INTO messages (user_id, text, media_type, file_id) VALUES (?, ?, ?, ?)",
        (user.id, db_text, media_type, file_id)
    )
    conn.commit()

    await msg.answer("✅ Отправлено анонимно")

# ===== WEB =====
async def start_web():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# ===== ЗАПУСК =====
async def main():
    await start_web()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
