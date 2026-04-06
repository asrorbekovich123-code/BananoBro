import asyncio
import logging
import os
import random
import time
from dotenv import load_dotenv
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AD_TEXT = os.getenv("AD_TEXT", "🍌 Выращивай бананы!")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PORT = int(os.getenv("PORT", 8080))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан в .env")

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

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def format_message(text: str) -> str:
    if AD_TEXT:
        return f"{text}\n\n{AD_TEXT}"
    return text

async def get_or_create_user(user_id: int, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            current_time = int(time.time())
            await db.execute(
                "INSERT INTO users (user_id, username, bananas, banana_coins, farm_m2, last_collect_time) "
                "VALUES (?, ?, 0, 0, 0, ?)",
                (user_id, username, current_time)
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
    current_time = int(time.time())
    hours_passed = (current_time - last_collect_time) / 3600.0
    income_per_hour = 100 + farm_m2 * 5
    return int(hours_passed * income_per_hour)

# ==================== КОМАНДЫ ====================
EMOJIS = ['🍌', '🥥', '🌴', '🍍']
collect_cooldown = {}
roulette_cooldown = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await init_db()
    user_id = message.from_user.id
    username = message.from_user.username or f"User{user_id}"
    await get_or_create_user(user_id, username)

    text = "**🍌 Добро пожаловать в Выращиватель Бананов!**\n\nСобирай бананы, прокачивай ферму и крути рулетку!"

    if message.chat.type == "private":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍌 Сбор", callback_data="collect")],
            [InlineKeyboardButton(text="🏪 Магазин ферм", callback_data="shop")],
            [InlineKeyboardButton(text="🎰 Рулетка", callback_data="roulette_btn")],
            [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="🏆 Топы", callback_data="tops")],
        ])
        await message.answer(format_message(text), parse_mode="MarkdownV2", reply_markup=keyboard)
    else:
        await message.answer(format_message(text), parse_mode="MarkdownV2")


@dp.message(F.text)
async def handle_text_commands(message: types.Message):
    if not message.text:
        return
    text_lower = message.text.lower().strip()
    user_id = message.from_user.id
    username = message.from_user.username or f"User{user_id}"
    await get_or_create_user(user_id, username)

    try:
        if text_lower == "сбор":
            await do_collect(user_id, username, message)
        elif text_lower.startswith("продать "):
            await do_sell(user_id, text_lower, message)
        elif text_lower.startswith("рулетка "):
            await do_roulette(user_id, text_lower, message)
        elif text_lower in ["профиль", "/профиль"]:
            await do_profile(user_id, message)
        elif text_lower in ["топ бананов", "топ бабанов"]:
            await do_top_bananas(message)
        elif text_lower == "топ коинов":
            await do_top_coins(message)
        elif text_lower in ["/help", "/меню", "меню"]:
            await do_help(message)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("⚠️ Произошла ошибка. Попробуй ещё раз.")


async def do_collect(user_id: int, username: str, message: types.Message):
    if user_id in collect_cooldown and time.time() - collect_cooldown[user_id] < 45:
        await message.answer("⏳ Подожди 45 секунд перед следующим сбором!")
        return
    collect_cooldown[user_id] = time.time()

    row = await get_or_create_user(user_id, username)
    bananas, banana_coins, farm_m2, last_collect_time = row[2], row[3], row[4], row[5]

    earned = calculate_earned(farm_m2, last_collect_time)
    new_bananas = bananas + earned
    current_time = int(time.time())

    await update_user(user_id, bananas=new_bananas, last_collect_time=current_time)

    income = 100 + farm_m2 * 5
    text = f"**🍌 Сбор урожая**\n\nВы собрали **{earned}** бананов!\nТеперь у тебя: **{new_bananas}** 🍌\nДоход в час: **{income}** бананов"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


async def do_sell(user_id: int, text_lower: str, message: types.Message):
    row = await get_or_create_user(user_id, "dummy")
    bananas, banana_coins = row[2], row[3]

    if "все" in text_lower:
        amount = bananas
    else:
        try:
            amount = int(text_lower.split()[1])
        except:
            await message.answer("❌ Неверный формат! Пример: `продать 150` или `продать ВСЕ`")
            return

    if amount < 10 and amount != bananas:
        await message.answer("❌ Минимум 10 бананов для продажи!")
        return
    if amount > bananas or amount <= 0:
        await message.answer("❌ Недостаточно бананов!")
        return

    coins_add = amount // 10
    new_bananas = bananas - amount
    new_coins = banana_coins + coins_add

    await update_user(user_id, bananas=new_bananas, banana_coins=new_coins)

    text = f"**💰 Продажа**\n\nПродано **{amount}** 🍌\nПолучено **{coins_add}** коинов\nБананы: **{new_bananas}**\nКоины: **{new_coins}**"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


async def do_roulette(user_id: int, text_lower: str, message: types.Message):
    if user_id in roulette_cooldown and time.time() - roulette_cooldown[user_id] < 45:
        await message.answer("⏳ Подожди 45 секунд перед следующей рулеткой!")
        return
    roulette_cooldown[user_id] = time.time()

    try:
        stake = int(text_lower.split()[1])
    except:
        await message.answer("❌ Пример: `Рулетка 50`")
        return

    row = await get_or_create_user(user_id, "dummy")
    banana_coins = row[3]

    if stake < 1 or stake > banana_coins:
        await message.answer("❌ Недостаточно Банан-коинов!")
        return

    spin = random.choices(EMOJIS, k=3)
    spin_text = " ".join(spin)

    counter = {}
    for e in spin:
        counter[e] = counter.get(e, 0) + 1
    max_count = max(counter.values())

    if max_count == 3:
        multiplier = 3
        result = "🎉 ДЖЕКПОТ! ×3"
    elif max_count == 2:
        multiplier = 1.5
        result = "👍 Хорошо! ×1.5"
    else:
        multiplier = 0
        result = "😢 Не повезло..."

    win = int(stake * multiplier) if multiplier > 0 else -stake
    new_coins = banana_coins + win

    await update_user(user_id, banana_coins=new_coins)

    text = f"**🎰 Рулетка**\n\n{spin_text}\n\n{result}\nСтавка: **{stake}**\nИтог: **{win:+}** коинов\nТеперь: **{new_coins}**"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


async def do_profile(user_id: int, message: types.Message):
    row = await get_or_create_user(user_id, "dummy")
    bananas, banana_coins, farm_m2, last_collect_time = row[2], row[3], row[4], row[5]
    income = 100 + farm_m2 * 5
    earned_now = calculate_earned(farm_m2, last_collect_time)

    text = f"**👤 Профиль**\n\n🍌 Бананы: **{bananas}** (+{earned_now})\n🪙 Коины: **{banana_coins}**\n🌱 Ферма: **{farm_m2} м²**\n📈 Доход/час: **{income}**"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


async def do_top_bananas(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT username, bananas FROM users ORDER BY bananas DESC LIMIT 20") as cursor:
            rows = await cursor.fetchall()

    lines = ["**🏆 ТОП-20 по бананам** 🍌\n"]
    for i, (uname, b) in enumerate(rows, 1):
        name = uname or "Аноним"
        lines.append(f"{i}. {name} — **{b}** 🍌")
    text = "\n".join(lines) if rows else "**Топ пока пустой**"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


async def do_top_coins(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT username, banana_coins FROM users ORDER BY banana_coins DESC LIMIT 20") as cursor:
            rows = await cursor.fetchall()

    lines = ["**🏆 ТОП-20 по коинам** 🪙\n"]
    for i, (uname, c) in enumerate(rows, 1):
        name = uname or "Аноним"
        lines.append(f"{i}. {name} — **{c}** 🪙")
    text = "\n".join(lines) if rows else "**Топ пока пустой**"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


async def do_help(message: types.Message):
    text = "**📋 Команды:**\n\n`сбор` — собрать бананы\n`продать 150` или `продать ВСЕ`\n`Рулетка 50`\n`профиль`\n`Топ бананов`\n`Топ коинов`\n\nВ ЛС есть кнопки!"
    await message.answer(format_message(text), parse_mode="MarkdownV2")


# ==================== КНОПКИ (только ЛС) ====================
@dp.callback_query()
async def handle_callback(callback: CallbackQuery):
    if callback.message.chat.type != "private":
        await callback.answer("Кнопки работают только в личных сообщениях!", show_alert=True)
        return

    if callback.data == "collect":
        await do_collect(callback.from_user.id, callback.from_user.username or "User", callback.message)
    elif callback.data == "shop":
        # ... (магазин можно добавить позже, сейчас оставим заглушку)
        await callback.message.answer("🏪 Магазин в разработке. Пока используй продажу бананов.")
    elif callback.data == "profile":
        await do_profile(callback.from_user.id, callback.message)
    elif callback.data == "tops":
        await do_top_bananas(callback.message)
    elif callback.data == "roulette_btn":
        await callback.message.answer("Напиши: `Рулетка 50`")

    await callback.answer()


# ==================== ЗАПУСК ====================
async def on_startup(bot: Bot):
    await init_db()
    if WEBHOOK_HOST:
        webhook_url = f"{WEBHOOK_HOST.rstrip('/')}{WEBHOOK_PATH}"
        await bot.set_webhook(webhook_url)
        logging.info(f"Webhook установлен: {webhook_url}")
    logging.info("Бот запущен! 🍌")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if WEBHOOK_HOST:
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        web.run_app(app, host="0.0.0.0", port=PORT)
    else:
        asyncio.run(dp.start_polling(bot))
