import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
Bot tokenini shu yerga kiriting
BOT_TOKEN = "9116459506:AAEmgu1GDMiJ-gyaSCIvgPftEK1j1PhukCg"
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
O'yin ma'lumotlarini vaqtinchalik xotirada saqlash (chat_id bo'yicha)
games = {}
Rollarni taqsimlash funksiyasi
def assign_roles(players_list):
count = len(players_list)
roles = []
# O'yinchilar soniga qarab rollar
mafia_count = max(1, count // 3)
roles.extend(["Mafia"] * mafia_count)
if count >= 4:
roles.append("Komissar")
if count >= 5:
roles.append("Doktor")
# Qolganlari Tinch aholi
while len(roles) < count:
    roles.append("Tinch aholi")
    
random.shuffle(roles)
return dict(zip(players_list, roles))
1. O'yinni e'lon qilish (/game)
@dp.message(Command("game"))
async def start_registration(message: types.Message):
if message.chat.type == "private":
await message.answer("Bu buyruq faqat guruhlarda ishlaydi!")
return
chat_id = message.chat.id
if chat_id in games and games[chat_id]["status"] != "ended":
    await message.answer("Bu guruhda allaqachon o'yin ketmoqda!")
    return

games[chat_id] = {
    "status": "registration",
    "players": {},      # {user_id: full_name}
    "roles": {},        # {user_id: role}
    "alive": [],        # [user_id, ...]
    "night_actions": {}, # {"mafia": target_id, "doctor": target_id, "sheriff": target_id}
    "votes": {}         # {voter_id: target_id}
}

kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ O'yinga qo'shilish", callback_data="join_game")]
])
await message.answer(
    "🎲 **Mafia o'yini uchun ro'yxatdan o'tish boshlandi!**\n\n"
    "O'yinga qo'shilish uchun tugmani bosing (kamida 4 kishi kerak).\n"
    "Boshlash uchun /start_mafia buyrug'ini yozing.",
    reply_markup=kb,
    parse_mode="Markdown"
)
O'yinga qo'shilish tugmasi bosilganda
@dp.callback_query(F.data == "join_game")
async def join_game_callback(callback: CallbackQuery):
chat_id = callback.message.chat.id
user = callback.from_user
if chat_id not in games or games[chat_id]["status"] != "registration":
    await callback.answer("Ro'yxatdan o'tish yopilgan!", show_alert=True)
    return

if user.id in games[chat_id]["players"]:
    await callback.answer("Siz allaqachon ro'yxatdasiz!", show_alert=True)
    return

# Bot lichkasiga yozish imkoniyatini tekshirish
try:
    await bot.send_message(user.id, "✅ Siz guruhdagi Mafia o'yiniga qo'shildingiz! O'yin boshlanishini kuting.")
except Exception:
    await callback.answer("Avval botga kirib /start bosing (lichkaga yozish uchun)!", show_alert=True)
    return

games[chat_id]["players"][user.id] = user.full_name
players_names = "\n".join([f"• {name}" for name in games[chat_id]["players"].values()])

kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ O'yinga qo'shilish", callback_data="join_game")]
])
await callback.message.edit_text(
    f"🎲 **Mafia o'yini uchun ro'yxatdan o'tish boshlandi!**\n\n"
    f"**Ro'yxatdagilar ({len(games[chat_id]['players'])}):**\n{players_names}\n\n"
    f"O'yinni boshlash uchun: /start_mafia",
    reply_markup=kb,
    parse_mode="Markdown"
)
await callback.answer("Qo'shildingiz!")
2. O'yinni boshlash (/start_mafia)
@dp.message(Command("start_mafia"))
async def begin_game(message: types.Message):
chat_id = message.chat.id
if chat_id not in games or games[chat_id]["status"] != "registration":
return
players = list(games[chat_id]["players"].keys())
if len(players) < 4:
    await message.answer("❌ O'yinni boshlash uchun kamida 4 nafar o'yinchi kerak!")
    return

games[chat_id]["alive"] = players.copy()
roles = assign_roles(players)
games[chat_id]["roles"] = roles

# Har bir o'yinchiga rolini shaxsiy xabarda yuborish
for uid, role in roles.items():
    await bot.send_message(uid, f"🎭 O'yin boshlandi! Sizning rolingiz: **{role}**", parse_mode="Markdown")

await message.answer("🌃 **O'yin boshlandi! Shaharga tun cho'kdi...**\n"
                     "Tinch aholi uxlamoqda. Aktiv rollar bot lichkasida o'z tanlovini qilmoqda.", parse_mode="Markdown")
await night_phase(chat_id)
3. Tun fazasi
async def night_phase(chat_id):
game = games[chat_id]
game["status"] = "night"
game["night_actions"] = {}
alive_players = game["alive"]

# Aktiv rollarga tanlov tugmalarini yuborish
for uid in alive_players:
    role = game["roles"][uid]
    if role in ["Mafia", "Komissar", "Doktor"]:
        buttons = []
        for target_id in alive_players:
            if role != "Doktor" and target_id == uid:
                continue # Mafia va Komissar o'zini tanlay olmaydi
            target_name = game["players"][target_id]
            buttons.append([InlineKeyboardButton(
                text=target_name, 
                callback_data=f"night_{chat_id}_{role}_{target_id}"
            )])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await bot.send_message(uid, f"🌙 Tun. **{role}**, kimni tanlaysiz?", reply_markup=kb, parse_mode="Markdown")

# Tungi harakatlar uchun 25 soniya kutish
await asyncio.sleep(25)
await resolve_night(chat_id)
Tungi tanlovlarni qabul qilish
@dp.callback_query(F.data.startswith("night_"))
async def handle_night_action(callback: CallbackQuery):
, chat_id_str, role, target_id_str = callback.data.split("")
chat_id = int(chat_id_str)
target_id = int(target_id_str)
if chat_id not in games or games[chat_id]["status"] != "night":
    await callback.answer("Tun tugagan!", show_alert=True)
    return

games[chat_id]["night_actions"][role] = target_id
target_name = games[chat_id]["players"][target_id]

if role == "Komissar":
    target_role = games[chat_id]["roles"][target_id]
    is_mafia = "HA, u Mafia! 🔫" if target_role == "Mafia" else "Yo'q, u tinch aholi."
    await callback.message.edit_text(f"🔍 Tekshiruv natijasi ({target_name}): **{is_mafia}**", parse_mode="Markdown")
else:
    await callback.message.edit_text(f"✅ Siz **{target_name}** ni tanladingiz.", parse_mode="Markdown")
await callback.answer()
4. Tun natijalarini hisoblash va Kun fazasiga o'tish
async def resolve_night(chat_id):
game = games[chat_id]
actions = game["night_actions"]
mafia_target = actions.get("Mafia")
doctor_target = actions.get("Doktor")

report = "☀️ **Tong otdi!**\n\n"
if mafia_target:
    if mafia_target == doctor_target:
        report += "💉 Mafia hujum qildi, lekin **Doktor** o'z vaqtida yetib kelib qurbonni qutqarib qoldi! Hech kim o'lmadi."
    else:
        victim_name = game["players"][mafia_target]
        victim_role = game["roles"][mafia_target]
        game["alive"].remove(mafia_target)
        report += f"💀 Tunda **{victim_name}** ({victim_role}) shafqatsizlarcha o'ldirildi."
else:
    report += "😴 Tun tinch o'tdi, hech kim o'lmadi."

await bot.send_message(chat_id, report, parse_mode="Markdown")

if await check_winner(chat_id):
    return

await day_phase(chat_id)
5. Kun fazasi (Muhokama va Ovoz berish)
async def day_phase(chat_id):
game = games[chat_id]
game["status"] = "day"
game["votes"] = {}
await bot.send_message(chat_id, "🗣 **Muhokama vaqti!** Mafia kim ekanligini aniqlang (20 soniya muhokama).")
await asyncio.sleep(20)

# Ovoz berish tugmalarini chiqarish
buttons = []
for uid in game["alive"]:
    buttons.append([InlineKeyboardButton(
        text=f"Osish: {game['players'][uid]}", 
        callback_data=f"vote_{chat_id}_{uid}"
    )])
kb = InlineKeyboardMarkup(inline_keyboard=buttons)
await bot.send_message(chat_id, "⚖️ **Ovoz berish boshlandi!** Kimni o'yindan chetlatamiz? (15 soniya)", reply_markup=kb, parse_mode="Markdown")

await asyncio.sleep(15)
await resolve_day(chat_id)
@dp.callback_query(F.data.startswith("vote_"))
async def handle_vote(callback: CallbackQuery):
, chat_id_str, target_id_str = callback.data.split("")
chat_id = int(chat_id_str)
target_id = int(target_id_str)
voter_id = callback.from_user.id
