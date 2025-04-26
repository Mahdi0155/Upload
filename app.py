import os
import json
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

FILES_PATH = "files.json"

if not os.path.exists(FILES_PATH):
    with open(FILES_PATH, "w") as f:
        json.dump([], f)

class UploadStates(StatesGroup):
    waiting_for_file = State()

def load_files():
    with open(FILES_PATH, "r") as f:
        return json.load(f)

def save_files(data):
    with open(FILES_PATH, "w") as f:
        json.dump(data, f, indent=2)

async def check_membership(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "creator", "administrator"]
    except:
        return False

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    text = message.text
    parts = text.split()
    args = parts[1] if len(parts) > 1 else None

    if message.from_user.id == ADMIN_ID and not args:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="ارسال فایل جدید", callback_data="send_file")],
                [InlineKeyboardButton(text="نمایش فایل‌های آپلود شده", callback_data="show_files")]
            ]
        )
        await message.answer("سلام ادمین عزیز! چیکار میخوای بکنی؟", reply_markup=keyboard)
        return

    if args:
        await state.update_data(file_id=args)
        await handle_file_request(message, state)
    else:
        await message.answer("سلام! فایل خاصی درخواست نشده.")

async def handle_file_request(message, state, from_callback=False):
    user_id = message.from_user.id
    data = await state.get_data()
    file_id = data.get("file_id")

    if not file_id:
        await message.answer("خطا! فایل پیدا نشد.")
        return

    is_member = await check_membership(user_id)
    if not is_member:
        join_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="عضویت در کانال", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],
                [InlineKeyboardButton(text="بررسی عضویت", callback_data="check_membership")]
            ]
        )
        text = "باید عضو کانال بشی تا بتونی فایل رو دریافت کنی."
        if from_callback:
            await message.edit_text(text, reply_markup=join_keyboard)
        else:
            await message.answer(text, reply_markup=join_keyboard)
        return

    await message.answer("فایل درخواستی شما:")
    await bot.send_document(chat_id=message.chat.id, document=file_id)
    await state.clear()

@dp.callback_query(lambda c: c.data == 'check_membership')
async def check_membership_button(callback_query: types.CallbackQuery, state: FSMContext):
    await handle_file_request(callback_query.message, state, from_callback=True)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "send_file")
async def send_file_button(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("لطفاً عکس یا ویدیوی خودت رو بفرست.")
    await state.set_state(UploadStates.waiting_for_file)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "show_files")
async def show_files_button(callback_query: types.CallbackQuery):
    files = load_files()
    if not files:
        await callback_query.message.answer("هیچ فایلی آپلود نشده.")
        return

    for idx, file in enumerate(files, 1):
        file_type = file.get("type")
        file_id = file.get("file_id")
        link_button = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="کپی لینک فایل", callback_data=f"get_link_{file_id}")]
            ]
        )
        if file_type == "photo":
            await bot.send_photo(chat_id=callback_query.message.chat.id, photo=file_id, caption=f"فایل {idx}", reply_markup=link_button)
        elif file_type == "video":
            await bot.send_video(chat_id=callback_query.message.chat.id, video=file_id, caption=f"فایل {idx}", reply_markup=link_button)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("get_link_"))
async def get_link(callback_query: types.CallbackQuery):
    file_id = callback_query.data.split("_", 2)[2]
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={file_id}"
    await callback_query.message.answer(f"لینک فایل:\n\n{link}")
    await callback_query.answer()

@dp.message(UploadStates.waiting_for_file)
async def handle_uploaded_file(message: types.Message, state: FSMContext):
    if not (message.photo or message.video):
        await message.answer("فقط عکس یا ویدیو بفرست.")
        return

    file_id = None
    file_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"

    files = load_files()
    files.append({"file_id": file_id, "type": file_type})
    save_files(files)

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={file_id}"

    await message.answer(f"فایل آپلود شد!\n\nلینک فایل:\n{link}")
    await state.clear()

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)

@app.post("/")
async def webhook(req: Request):
    if req.method != "POST":
        return {"ok": False}

    data = await req.json()
    try:
        update = types.Update(**data)
        await dp.feed_update(bot, update)
    except Exception as e:
        print(f"خطا در پردازش آپدیت: {e}")
        print(data)
        return {"ok": False}
    return {"ok": True}
