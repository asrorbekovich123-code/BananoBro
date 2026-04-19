import asyncio
import logging
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ====================== НАСТРОЙКИ ======================
BOT_TOKEN = "8692984616:AAgm5gUUmJUnhx-304Eq1zBiTDX8ZG89psM"   # ←←← ТВОЙ ТОКЕН ЗДЕСЬ
AD_TEXT = "🍌 BananoX — выращивай бананы!"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "bot.db"

# ====================== БАЗА ДАННЫХ ======================
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
    set_clause = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
        await db.commit()

def calculate_earned(farm_m2: int, last_collect_time: int) -> int:
    if last_collect_time == 0:
        return 0
    hours_passed = (int(time.time()) - last_collect_time) / 3600.0
    return int(hours_passed * (100 + farm_m2 * 5))

def format_msg(text: str) -> str:
    return f"{text}\n\n{AD_TEXT}"

# ====================== КОМАНДЫ ======================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await init_db()
    user = message.from_user
    await get_or_create_user(user.id, user.username or f"User{user.id}")

    text = "🌿 **Добро пожаловать в BananoX!**\n\nВыращивай бананы и прокачивай ферму!"

    if message.chat.type == "private":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍌 Собрать", callback_data="collect")],
            [InlineKeyboardButton(text="💰 Продать", callback_data="sell")],
            [InlineKeyboardButton(text="🏪 Магазин", callback_data="shop")],
            [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="🏆 Топ", callback_data="top_bananas")],
        ])
        await message.answer(format_msg(text), parse_mode="MarkdownV2", reply_markup=kb)
    else:
        await message.answer(format_msg(text), parse_mode="MarkdownV2")


@dp.message(Command("collect"))
async def cmd_collect(message: types.Message):
    row = await get_or_create_user(message.from_user.id, message.from_user.username or "User")
    earned = calculate_earned(row[4], row[5])
    new_bananas = row[2] + earned

    await update_user(message.from_user.id, bananas=new_bananas, last_collect_time=int(time.time()))

    await message.answer(format_msg(f"**🍌 Сбор урожая**\n\nТы собрал **{earned}** бананов!\nТеперь у тебя **{new_bananas}** 🍌"), parse_mode="MarkdownV2")


@dp.message(Command("sell"))
async def cmd_sell(message: types.Message):
    row = await get_or_create_user(message.from_user.id, "dummy")
    if row[2] < 10:
        await message.answer("❌ У тебя меньше 10 бананов!")
        return

    amount = row[2]
    coins = amount // 10
    await update_user(message.from_user.id, bananas=0, banana_coins=row[3] + coins)

    await message.answer(format_msg(f"**💰 Продажа**\n\nПродал **{amount}** бананов\nПолучил **{coins}** Banano Coins"), parse_mode="MarkdownV2")


@dp.message(Command("shop"))
async def cmd_shop(message: types.Message):
    text = """**🏪 Магазин ферм**

1 м² = 1 Banano Coin
Каждый м² даёт +5 бананов в час

/buy 10 — купить 10 м²
/buy 50 — купить 50 м²"""
    await message.answer(format_msg(text), parse_mode="MarkdownV2")


@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    try:
        amount = int(message.text.split()[1])
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Пример: `/buy 10`", parse_mode="MarkdownV2")
        return

    row = await get_or_create_user(message.from_user.id, "dummy")
    cost = amount

    if row[3] < cost:
        await message.answer(f"❌ Недостаточно Banano Coins!\nНужно: {cost}\nУ тебя: {row[3]}", parse_mode="MarkdownV2")
        return

    new_m2 = row[4] + amount
    new_coins = row[3] - cost
    await update_user(message.from_user.id, farm_m2=new_m2, banana_coins=new_coins)

    await message.answer(format_msg(f"**✅ Куплено {amount} м²**\nТеперь ферма: {new_m2} м²\nКоинов осталось: {new_coins}"), parse_mode="MarkdownV2")


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    row = await get_or_create_user(message.from_user.id, "dummy")
    income = 100 + row[4] * 5
    text = f"""**👤 Профиль**

🍌 Бананы: {row[2]}
🪙 Banano Coins: {row[3]}
🌱 Ферма: {row[4]} м²
📈 Доход в час: {income} бананов"""
    await message.answer(format_msg(text), parse_mode="MarkdownV2")


@dp.message(Command("top_bananas"))
async def cmd_top_bananas(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT username, bananas FROM users ORDER BY bananas DESC LIMIT 10") as cur:
            rows = await cur.fetchall()

    lines = ["**🏆 ТОП по бананам**\n"]
    for i, (name, cnt) in enumerate(rows, 1):
        lines.append(f"{i}. {name or 'Аноним'} — {cnt} 🍌")
    await message.answer(format_msg("\n".join(lines)), parse_mode="MarkdownV2")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = """🌿 **Команды BananoX:**

/collect — собрать бананы
/sell — продать все бананы
/shop — магазин
/buy 10 — купить м² фермы
/profile — профиль
/top_bananas — топ по бананам
/help — помощь"""
    await message.answer(format_msg(text), parse_mode="MarkdownV2")


# ====================== ЗАПУСК (Polling) ======================
async def main():
    await init_db()
    logging.info("BananoX запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
