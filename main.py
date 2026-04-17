import asyncio
import logging
import os
import random
import time
from dotenv import load_dotenv
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AD_TEXT = os.getenv("AD_TEXT", "🍌 Выращивай бананы!")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "bot.db"

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                bananas INTEGER DEFAULT 0,
                banana_coins INTEGER DEFAULT 0,
                farm_m2 INTEGER DEFAULT 0,
                last_collect_time INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def get_or_create_user(user_id: int, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            current_time = int(time.time())
            await db.execute(
                "INSERT INTO users (user_id, username, bananas, banana_coins, farm_m2, last_collect_time) "
                "VALUES (?, ?, 0, 0, 0, ?)", (user_id, username, current_time)
            )
            await db.commit()
            return (user_id, username, 0, 0, 0, current_time)
        return row

async def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    set_clause = ", ".join(f"{key} = ?" for key in kwargs)
    values = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
        await db.commit()

def calculate_earned(farm_m2: int, last_collect_time: int) -> int:
    if last_collect_time == 0:
        return 0
    hours_passed = (int(time.time()) - last_collect_time) / 3600.0
    return int(hours_passed * (100 + farm_m2 * 5))

def format_message(text: str) -> str:
    return f"{text}\n\n{AD_TEXT}" if AD_TEXT else text

# ==================== КОМАНДЫ В СТИЛЕ КОНОПЛЯНКИ ====================
EMOJIS = ['🍌', '🥥', '🌴', '🍍']
collect_cooldown = {}
roulette_cooldown = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await init_db()
    user = message.from_user
    await get_or_create_user(user.id, user.username or f"User{user.id}")

    text = (
        "🌿 **Добро пожаловать в Выращиватель Бананов!**\n\n"
        "Выбери команду ниже или используй слеш-команды:"
    )

    if message.chat.type == "private":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍌 /collect — Собрать бананы", callback_data="collect")],
            [InlineKeyboardButton(text="💰 /sell — Продать бананы", callback_data="sell")],
            [InlineKeyboardButton(text="🏪 /shop — Магазин ферм", callback_data="shop")],
            [InlineKeyboardButton(text="👤 /profile — Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="🎰 /roulette — Рулетка", callback_data="roulette")],
            [InlineKeyboardButton(text="🏆 /top_bananas — Топ по бананам", callback_data="top_bananas")],
            [InlineKeyboardButton(text="🏆 /top_coins — Топ по коинам", callback_data="top_coins")],
        ])
        await message.answer(format_message(text), parse_mode="MarkdownV2", reply_markup=keyboard)
    else:
        await message.answer(format_message(text), parse_mode="MarkdownV2")


# Основные слеш-команды
@dp.message(Command("collect"))
async def cmd_collect(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or f"User{user_id}"
    await get_or_create_user(user_id, username)

    if user_id in collect_cooldown and time.time() - collect_cooldown[user_id] < 45:
        await message.answer("⏳ Подожди 45 секунд перед следующим сбором!")
        return
    collect_cooldown[user_id] = time.time()

    row = await get_or_create_user(user_id, username)
    earned = calculate_earned(row[4], row[5])
    new_bananas = row[2] + earned

    await update_user(user_id, bananas=new_bananas, last_collect_time=int(time.time()))

    text = f"**🍌 Сбор бананов**\n\nТы собрал **{earned}** бананов!\nТеперь у тебя: **{new_bananas}** 🍌"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


@dp.message(Command("sell"))
async def cmd_sell(message: types.Message):
    # Для простоты сейчас продаём всё. Позже можно добавить с аргументом.
    row = await get_or_create_user(message.from_user.id, "dummy")
    if row[2] < 10:
        await message.answer("❌ У тебя меньше 10 бананов!")
        return

    amount = row[2]
    coins = amount // 10
    await update_user(message.from_user.id, bananas=0, banana_coins=row[3] + coins)

    text = f"**💰 Продажа**\n\nТы продал **{amount}** бананов\nПолучил **{coins}** Банан-коинов"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    row = await get_or_create_user(message.from_user.id, "dummy")
    income = 100 + row[4] * 5
    earned_now = calculate_earned(row[4], row[5])

    text = (
        f"**👤 Твой профиль**\n\n"
        f"🍌 Бананы: **{row[2]}** (+{earned_now})\n"
        f"🪙 Коины: **{row[3]}**\n"
        f"🌱 Ферма: **{row[4]} м²**\n"
        f"📈 Доход в час: **{income}** бананов"
    )
    await message.answer(format_message(text), parse_mode="MarkdownV2")


@dp.message(Command("roulette"))
async def cmd_roulette(message: types.Message):
    await message.answer("🎰 Напиши: `/roulette 50` — где 50 это ставка в коинах")


@dp.message(Command("top_bananas"))
async def cmd_top_bananas(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT username, bananas FROM users ORDER BY bananas DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    text = "**🏆 Топ по бананам**\n\n" + "\n".join([f"{i+1}. {row[0] or 'Аноним'} — **{row[1]}** 🍌" for i, row in enumerate(rows)])
    await message.answer(format_message(text), parse_mode="MarkdownV2")


@dp.message(Command("top_coins"))
async def cmd_top_coins(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT username, banana_coins FROM users ORDER BY banana_coins DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    text = "**🏆 Топ по коинам**\n\n" + "\n".join([f"{i+1}. {row[0] or 'Аноним'} — **{row[1]}** 🪙" for i, row in enumerate(rows)])
    await message.answer(format_message(text), parse_mode="MarkdownV2")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "🌿 **Доступные команды:**\n\n"
        "/collect — Собрать бананы\n"
        "/sell — Продать все бананы\n"
        "/profile — Посмотреть профиль\n"
        "/roulette 50 — Крутить рулетку\n"
        "/top_bananas — Топ по бананам\n"
        "/top_coins — Топ по коинам\n"
        "/help — Эта помощь"
    )
    await message.answer(format_message(text), parse_mode="MarkdownV2")


# ==================== ЗАПУСК ====================
async def on_startup(bot: Bot):
    await init_db()
    if WEBHOOK_HOST:
        await bot.set_webhook(f"{WEBHOOK_HOST.rstrip('/')}{WEBHOOK_PATH}")
        logging.info("Webhook установлен")
    logging.info("Бот запущен в стиле Коноплянки 🍌")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if WEBHOOK_HOST:
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        web.run_app(app, host="0.0.0.0", port=PORT)
    else:
        asyncio.run(dp.start_polling(bot))
