import os
import psycopg2  # Changed from sqlite3
import random
import string
from datetime import datetime
from urllib.parse import urlparse  # Added for Postgres parsing
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# --- KEEP ALIVE ---
from keep_alive import keep_alive
keep_alive()

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8633084590:AAFk567rkAVloZhAu2TsrN1glQHQkG71Fls")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8155930122"))
REGISTRATION_BONUS = 2.75
USERS_PAGE_SIZE = 10

# ─── DATABASE CONNECTION (POSTGRESQL) ────────────────────────────────────────
db_url = os.environ.get("DATABASE_URL")
result = urlparse(db_url)

conn = psycopg2.connect(
    database=result.path[1:],
    user=result.username,
    password=result.password,
    host=result.hostname,
    port=result.port
)
conn.autocommit = True  
cur = conn.cursor()

# ─── TABLES (UPDATED FOR POSTGRES) ──────────────────────────────────────────
cur.execute("""CREATE TABLE IF NOT EXISTS users(
    id BIGINT PRIMARY KEY,
    name TEXT,
    phone TEXT,
    email TEXT,
    password TEXT,
    referral_code TEXT UNIQUE,
    referred_by TEXT,
    balance REAL DEFAULT 0,
    level INTEGER DEFAULT 0,
    bonus_claimed INTEGER DEFAULT 0
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS deposits(
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount REAL,
    txn TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS withdraws(
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    bank TEXT,
    account TEXT,
    amount REAL,
    status TEXT DEFAULT 'pending',
    created_at TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS activations(
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    email TEXT,
    phone TEXT,
    old_balance REAL DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS tutorials(
    id SERIAL PRIMARY KEY,
    slot_number INTEGER,
    title TEXT,
    description TEXT,
    file_id TEXT,
    media_type TEXT,
    category TEXT
)""")

# ─── SETTINGS (POSTGRES COMPATIBLE) ──────────────────────────────────────────
def get_setting(key, default=None):
    cur.execute("SELECT value FROM settings WHERE key=%s", (key,)) 
    row = cur.fetchone()
    return row[0] if row else default

def set_setting(key, value):
    cur.execute("""
        INSERT INTO settings (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (key, str(value)))

if not get_setting("trc20_address"):
    set_setting("trc20_address", "TPHgbNeiG2uahVDk1bUESuZendP87hmyoj")
if not get_setting("min_withdrawal"):
    set_setting("min_withdrawal", "20")
if not get_setting("referral_bonus_pct"):
    set_setting("referral_bonus_pct", "25")

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def generate_referral_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        cur.execute("SELECT id FROM users WHERE referral_code=%s", (code,)) 
        if not cur.fetchone():
            return code

def get_trade_level(amount):
    if amount < 20: return 0
    elif amount <= 99: return 1
    elif amount <= 299: return 2
    elif amount <= 999: return 3
    elif amount <= 4999: return 4
    elif amount <= 9999: return 5
    else: return 6

def get_withdraw_rate(level):
    return {0: 300, 1: 300, 2: 325, 3: 350, 4: 375, 5: 400, 6: 450}.get(level, 300)

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def trc20():
    return get_setting("trc20_address")

SUPPORT_BUTTON = InlineKeyboardMarkup([
    [InlineKeyboardButton("🆘 Contact MCT Agent", callback_data="contact_support")]
])

ROBOT_MSG = (
    "🤖 This bot does not accept text messages.\n"
    "If you need help, please contact the MCT Agent."
)

async def wrong_input(update: Update, context, msg: str) -> bool:
    context.user_data["wrong_attempts"] = context.user_data.get("wrong_attempts", 0) + 1
    if context.user_data["wrong_attempts"] >= 3:
        context.user_data.clear()
        await update.message.reply_text(ROBOT_MSG, reply_markup=SUPPORT_BUTTON)
        return True
    await update.message.reply_text(msg)
    return False

# ─── MENU ────────────────────────────────────────────────────────────────────
menu = [
    ["📚 Tutorial", "🆘 Support"],
    ["🔥 Choose Trade Level"],
    ["💰 Balance", "📤 Withdraw"],
    ["♻️ Activate Old Account", "💰 Deposit"],
    ["🔗 Get Referral Link", "📋 Status"],
]
keyboard = ReplyKeyboardMarkup(menu, resize_keyboard=True)


# ─── START ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    # Changed ? to %s
    cur.execute("SELECT * FROM users WHERE id=%s", (update.effective_user.id,))
    if cur.fetchone():
        await dashboard(update)
        return
    if context.args:
        context.user_data["ref_from"] = context.args[0]
    await update.message.reply_text(
        "👋 Welcome to *MCT (MY CASH TARGET)*!\n\n"
        "Please register to continue.\n\n"
        "✏️ Enter your *FULL NAME*:",
        parse_mode="Markdown"
    )
    context.user_data["register"] = "name"


# ─── DASHBOARD ───────────────────────────────────────────────────────────────
async def dashboard(update: Update):
    await update.message.reply_text(
        "📊 *MCT Dashboard*",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# ─── REGISTER ────────────────────────────────────────────────────────────────
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("register")

    if step == "name":
        context.user_data["name"] = update.message.text
        context.user_data["register"] = "phone"
        await update.message.reply_text("📱 Enter your phone number:")

    elif step == "phone":
        context.user_data["phone"] = update.message.text
        context.user_data["register"] = "email"
        await update.message.reply_text("📧 Enter your email address:")

    elif step == "email":
        context.user_data["email"] = update.message.text
        if context.user_data.get("ref_from"):
            context.user_data["register"] = "save"
            await save_user(update, context)
        else:
            context.user_data["register"] = "ref"
            await update.message.reply_text("👥 Do you have a referral code? Enter it, or type *none*:", parse_mode="Markdown")

    elif step == "ref":
        ref_input = update.message.text.strip()
        referred_by = None
        if ref_input.lower() != "none":
            referred_by = ref_input
        if referred_by:
            # Changed ? to %s
            cur.execute("SELECT id FROM users WHERE referral_code=%s", (referred_by,))
            if not cur.fetchone():
                referred_by = None

        context.user_data["referred_by_final"] = referred_by
        context.user_data["register"] = "save"
        await save_user(update, context)

async def save_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = context.user_data.get("referred_by_final") or context.user_data.get("ref_from")

    if referred_by:
        # Changed ? to %s
        cur.execute("SELECT id FROM users WHERE referral_code=%s", (referred_by,))
        if not cur.fetchone():
            referred_by = None

    ref_code = generate_referral_code()
    # Changed all ? to %s
    cur.execute(
        "INSERT INTO users(id,name,phone,email,password,referral_code,referred_by,balance,level,bonus_claimed)"
        " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (user.id, context.user_data["name"], context.user_data["phone"],
         context.user_data["email"], "",
         ref_code, referred_by, REGISTRATION_BONUS, 0, 1)
    )
    # No conn.commit() needed because autocommit=True is set at the top

    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🆕 *NEW USER REGISTERED*\n\n"
            f"Name: `{context.user_data['name']}`\n"
            f"Phone: `{context.user_data['phone']}`\n"
            f"Email: `{context.user_data['email']}`\n"
            f"ID: `{user.id}`\n"
            f"Ref Code: `{ref_code}`\n"
            f"Referred By: `{referred_by or 'none'}`",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    name = context.user_data["name"]
    context.user_data.clear()

    await update.message.reply_text(
        f"🪪 *Your MCT USER ID is:*\n\n`{user.id}`\n\n"
        f"_(Tap to copy — keep it safe!)_",
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        f"*✅ Registration Successful!*\n\n"
        f"*🎉 Congratulations {name}!*\n"
        f"*You have received a registration bonus of 825 Birr ({REGISTRATION_BONUS} USDT)! 🎁*",
        parse_mode="Markdown"
    )
    await dashboard(update)


# ─── BALANCE ─────────────────────────────────────────────────────────────────
async def balance(update: Update):
    # Changed ? to %s
    cur.execute("SELECT balance, level FROM users WHERE id=%s", (update.effective_user.id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("❌ Account not found. Type /start to register.")
        return
    b, l = row
    rate = get_withdraw_rate(l)
    lvl_label = f"Level {l}" if l > 0 else "Level 0 (Deposit ≥ 20 USDT to unlock)"
    await update.message.reply_text(
        f"💰 *Your MCT Balance*\n\n"
        f"💵 Balance: *{b:.4f} USDT*\n"
        f"📊 Trade Level: *{lvl_label}*\n"
        f"💵 ETB Rate: *{rate} ETB/USDT*\n"
        f"💵 ETB Value: *{b * rate:.2f} ETB*",
        parse_mode="Markdown"
    )

# ─── STATUS ──────────────────────────────────────────────────────────────────
async def status(update: Update):
    uid = update.effective_user.id
    # Changed ? to %s
    cur.execute("SELECT id, amount, created_at FROM deposits WHERE user_id=%s AND status='pending'", (uid,))
    deps = cur.fetchall()
    cur.execute("SELECT id, amount, bank, created_at FROM withdraws WHERE user_id=%s AND status='pending'", (uid,))
    wds = cur.fetchall()
    cur.execute("SELECT id, created_at FROM activations WHERE user_id=%s AND status='pending'", (uid,))
    acts = cur.fetchall()

    if not deps and not wds and not acts:
        await update.message.reply_text("📋 You have no pending requests.")
        return

    lines = ["📋 *Your Pending Requests*\n"]
    if deps:
        lines.append("📥 *Deposits:*")
        for did, amt, ct in deps:
            lines.append(f"  • ID: `{did}` | {amt} USDT | ⏳ Pending | {ct or ''}")
    if wds:
        lines.append("\n📤 *Withdrawals:*")
        for wid, amt, bank, ct in wds:
            lines.append(f"  • ID: `{wid}` | {amt} USDT | {bank} | ⏳ Pending")
    if acts:
        lines.append("\n♻️ *Activations:*")
        for aid, ct in acts:
            lines.append(f"  • ID: `{aid}` | ⏳ Pending | {ct or ''}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── TRADE LEVEL / INVEST ────────────────────────────────────────────────────
TRADE_LEVEL_MSG = (
    "💼 *MCT Trading Levels*\n\n"
    "🔹 Trade Level 1: 20 – 99 USDT → 300 ETB Per USDT\n\n"
    "🔹 Trade Level 2: 100 – 299 USDT → 325 ETB Per USDT\n\n"
    "🔹 Trade Level 3: 300 – 999 USDT → 350 ETB Per USDT\n\n"
    "🔹 Trade Level 4: 1,000 – 4,999 USDT → 375 ETB Per USDT\n\n"
    "🔹 Trade Level 5: 5,000 – 9,999 USDT → 400 ETB\n\n"
    "🔹 Trade Level 6: 10,000 – 25,000 USDT → 450 ETB\n\n"
    "📈 Higher levels unlock better trading rewards.\n\n"
    "✏️💱 Enter the amount you want to invest (USDT):"
)

async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Changed ? to %s
    cur.execute("SELECT id FROM deposits WHERE user_id=%s AND status='pending'", (update.effective_user.id,))
    if cur.fetchone():
        await update.message.reply_text("⚠️ You have a pending deposit request. Please wait for Admin approval/rejection before requesting again.")
        return

    await update.message.reply_text(TRADE_LEVEL_MSG, parse_mode="Markdown")
    context.user_data["awaiting_amount"] = True
    context.user_data["invest_min"] = 20
    context.user_data["wrong_attempts"] = 0

async def deposit_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Changed ? to %s
    cur.execute("SELECT id FROM deposits WHERE user_id=%s AND status='pending'", (update.effective_user.id,))
    if cur.fetchone():
        await update.message.reply_text("⚠️ You have a pending deposit request. Please wait for Admin approval/rejection before requesting again.")
        return

    await update.message.reply_text(
        "💰 *MCT Deposit*\n\n"
        "You can deposit from *1 USDT* and above.\n"
        "_(Accounts below 20 USDT are on Trade Level 0)_\n\n"
        "✏️💱 Enter the amount you want to deposit (USDT):",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_amount"] = True
    context.user_data["invest_min"] = 1
    context.user_data["wrong_attempts"] = 0

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    invest_min = context.user_data.get("invest_min", 20)
    try:
        amount = float(update.message.text)
    except ValueError:
        await wrong_input(update, context, "❌ Please enter a valid number (e.g. 50).")
        return

    if amount < invest_min:
        await update.message.reply_text(
            f"❌ Minimum deposit is *{invest_min} USDT*.", parse_mode="Markdown"
        )
        return

    context.user_data["amount"] = amount
    context.user_data["awaiting_amount"] = False
    context.user_data["wrong_attempts"] = 0

    await update.message.reply_text(
        f"📌 Send *{amount} USDT* (TRC20) to:\n\n"
        f"`{trc20()}`\n\n"
        "👆👆👆👆 👆👆👆👆\n\n"
        "Tap the address to copy.\n\n"
        "📸 After sending payment, upload your payment screenshot.",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_screenshot"] = True


# ─── TXN HANDLER ─────────────────────────────────────────────────────────────
async def txn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_txn"):
        return

    txn_id = update.message.text.strip()
    if len(txn_id) < 5:
        await wrong_input(update, context, "❌ Please enter a valid Transaction ID (TXN).")
        return

    user = update.message.from_user
    photo = context.user_data.get("photo")
    amount = context.user_data.get("amount")

    # Fixed for PostgreSQL: Using RETURNING id to get the new row ID
    cur.execute(
        "INSERT INTO deposits(user_id,amount,txn,status,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id",
        (user.id, amount, txn_id, "pending", now())
    )
    did = cur.fetchone()[0]

    caption = (
        f"📥 *New Deposit*\n\n"
        f"ID: `{did}`\n"
        f"User: `{user.id}`\n"
        f"Amount: `{amount} USDT`\n"
        f"TXN: `{txn_id}`"
    )
    btns = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"dep_a_{did}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"dep_r_{did}"),
        InlineKeyboardButton("💬 Message", callback_data=f"dep_m_{user.id}")
    ]])
    if photo:
        await context.bot.send_photo(ADMIN_ID, photo, caption=caption, reply_markup=btns, parse_mode="Markdown")
    else:
        await context.bot.send_message(ADMIN_ID, caption, reply_markup=btns, parse_mode="Markdown")

    await update.message.reply_text(
        "✅ *Deposit request submitted!*\n"
        "⏳ Waiting for MCT Finance Agent approval (15–60 min).",
        parse_mode="Markdown"
    )
    context.user_data.clear()



# ─── DEPOSIT DECISION ────────────────────────────────────────────────────────
async def deposit_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    action = parts[1]
    val = int(parts[2])

    if action == "m":
        context.user_data["admin_action"] = "msg_target"
        context.user_data["admin_msg_uid"] = val
        await q.message.reply_text(f"✉️ Type message to user `{val}`:", parse_mode="Markdown")
        return

    cur.execute("SELECT user_id, amount, txn, status FROM deposits WHERE id=?", (val,))
    data = cur.fetchone()
    if not data:
        await q.answer("Deposit not found", show_alert=True)
        return

    uid, amt, txn_id, status = data
    if status != "pending":
        await q.answer(f"Already {'Approved' if status == 'approved' else 'Rejected'}", show_alert=True)
        return

    if action == "a":
        level = get_trade_level(amt)
        cur.execute("UPDATE users SET balance=balance+?, level=? WHERE id=?", (amt, level, uid))
        cur.execute("UPDATE deposits SET status='approved' WHERE id=?", (val,))
        conn.commit()

        ref_pct = float(get_setting("referral_bonus_pct", "25"))
        cur.execute("SELECT referred_by FROM users WHERE id=?", (uid,))
        ref_row = cur.fetchone()
        if ref_row and ref_row[0]:
            cur.execute("SELECT COUNT(*) FROM deposits WHERE user_id=? AND status='approved'", (uid,))
            if cur.fetchone()[0] == 1:
                bonus = round(amt * ref_pct / 100, 4)
                cur.execute("SELECT id FROM users WHERE referral_code=?", (ref_row[0],))
                ref_user = cur.fetchone()
                if ref_user:
                    cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (bonus, ref_user[0]))
                    conn.commit()
                    try:
                        await context.bot.send_message(
                            ref_user[0],
                            f"🎁 *Referral Bonus Received!*\n\n"
                            f"Your referral deposited and you earned *{bonus} USDT* ({ref_pct}% bonus)! 🚀",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

        cur.execute("SELECT balance, level FROM users WHERE id=?", (uid,))
        u_row = cur.fetchone()
        new_bal, new_lvl = u_row
        rate = get_withdraw_rate(new_lvl)

        try:
            await context.bot.send_message(
                uid,
                f"🎉 *Your Deposit Has Been Approved!* ✅\n\n"
                f"💵 Amount: *{amt} USDT*\n"
                f"💰 Balance: *{new_bal:.4f} USDT*\n"
                f"📊 Trade Level: *{new_lvl}*\n"
                f"💵 ETB Rate: *{rate} ETB/USDT*\n"
                f"💵 ETB Value: *{new_bal * rate:.2f} ETB*\n\n"
                f"Thank you for investing with MCT! 🚀",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        new_status = "Approved ✅"
    else:
        cur.execute("UPDATE deposits SET status='rejected' WHERE id=?", (val,))
        conn.commit()
        try:
            await context.bot.send_message(
                uid, f"❌ Your deposit of *{amt} USDT* was rejected.", parse_mode="Markdown"
            )
        except Exception:
            pass
        new_status = "Rejected ❌"

    new_caption = (
        f"📥 Deposit\n\nID: `{val}`\nUser: `{uid}`\n"
        f"Amount: `{amt} USDT`\nTXN: `{txn_id}`\nStatus: *{new_status}*"
    )
    try:
        await q.edit_message_caption(new_caption, parse_mode="Markdown")
    except Exception:
        try:
            await q.edit_message_text(new_caption, parse_mode="Markdown")
        except Exception:
            pass


# ─── ACTIVATION DECISION ─────────────────────────────────────────────────────
async def activation_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    action = parts[1]
    val = int(parts[2])

    if action == "m":
        context.user_data["admin_action"] = "msg_target"
        context.user_data["admin_msg_uid"] = val
        await q.message.reply_text(f"✉️ Type message to user `{val}`:", parse_mode="Markdown")
        return

    cur.execute("SELECT user_id, email, phone, old_balance, status FROM activations WHERE id=?", (val,))
    data = cur.fetchone()
    if not data:
        await q.answer("Not found", show_alert=True)
        return

    uid, email, phone, old_bal, status = data
    if status != "pending":
        await q.answer("Already processed", show_alert=True)
        return

    if action == "a":
        # Restore old balance and set level
        level = get_trade_level(old_bal)
        cur.execute("UPDATE users SET balance=balance+?, level=? WHERE id=?", (old_bal, level, uid))
        cur.execute("UPDATE activations SET status='approved' WHERE id=?", (val,))
        conn.commit()

        # Updated Activation success message
        try:
            await context.bot.send_message(
                uid,
                "📌 *Your Account is Activated successfully!*\n\n"
                "We are reaching out to inform you that your account has been inactive for several months. "
                "To ensure your account remains fully functional and to verify your ownership, please complete the activation process.\n\n"
                "Good news: We have already migrated your old account balance to this account. "
                "You can view your current funds in the \"Balance\" section once activation is complete.\n\n"
                "You can reactivate your account by making a small verification deposit. Please send a minimum of 1 USDT (up to a maximum of 20 USDT) to the following *TRC20* Address:\n\n"
                f"`{trc20()}`\n\n"
                "👆👆👆👆 👆👆👆👆\n\n"
                "Tap the address to copy.\n\n"
                "📸 After sending payment, upload your payment screenshot. "
                "Once the transaction is confirmed, your account will be successfully activated and ready for use.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        new_status = "Approved ✅"
    else:
        cur.execute("UPDATE activations SET status='rejected' WHERE id=?", (val,))
        conn.commit()
        try:
            await context.bot.send_message(uid, "❌ Your activation request was rejected. Please contact support.")
        except Exception:
            pass
        new_status = "Rejected ❌"

    new_caption = (
        f"♻️ Activation\n\nID: `{val}`\nUser: `{uid}`\n"
        f"Email: `{email}`\nPhone: `{phone}`\n"
        f"Old Balance: `{old_bal} USDT`\nStatus: *{new_status}*"
    )
    try:
        await q.edit_message_caption(new_caption, parse_mode="Markdown")
    except Exception:
        try:
            await q.edit_message_text(new_caption, parse_mode="Markdown")
        except Exception:
            pass


# ─── WITHDRAW ────────────────────────────────────────────────────────────────
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check for pending withdrawal
    cur.execute("SELECT id FROM withdraws WHERE user_id=? AND status='pending'", (update.effective_user.id,))
    if cur.fetchone():
        await update.message.reply_text("⚠️ You have a pending withdrawal request. Please wait for Admin approval/rejection before requesting again.")
        return

    cur.execute("SELECT balance FROM users WHERE id=?", (update.effective_user.id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("❌ Account not found.")
        return

    bal = row[0]
    min_wd = float(get_setting("min_withdrawal", "20"))

    if bal < min_wd:
        await update.message.reply_text(
            f"❌ You do not have enough balance to withdraw.\n\n"
            f"💰 Current Balance: *{bal:.4f} USDT*\n"
            f"📌 Minimum Withdrawal: *{min_wd} USDT*\n\n"
            f"Please deposit or invest to continue.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Deposit", callback_data="start_invest")]
            ])
        )
        return

    await update.message.reply_text(
        "🏦 *Withdrawal Method*\n\n"
        "Please select your bank:\n\n"
        "🔹 CBE\n🔹 Awash Bank\n🔹 Dashen Bank\n"
        "🔹 Abyssinia Bank\n🔹 Telebirr\n🔹 Mpesa\n"
        "🔹 Oromia Bank\n🔹 Hibret Bank\n\n"
        "✏️ Enter your bank name:",
        parse_mode="Markdown"
    )
    context.user_data["withdraw"] = "bank"
    context.user_data["wrong_attempts"] = 0


async def withdraw_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("withdraw")

    if step == "bank":
        context.user_data["bank"] = update.message.text
        context.user_data["withdraw"] = "account"
        await update.message.reply_text("📋 Enter your account number:")

    elif step == "account":
        context.user_data["account"] = update.message.text
        context.user_data["withdraw"] = "amount"
        await update.message.reply_text("💵 Enter amount to withdraw (USDT):")

    elif step == "amount":
        try:
            amt = float(update.message.text)
        except ValueError:
            await wrong_input(update, context, "❌ Please enter a valid number.")
            return

        user = update.message.from_user
        cur.execute("SELECT balance, level FROM users WHERE id=?", (user.id,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("❌ Account not found.")
            context.user_data.clear()
            return

        bal, lvl = row
        min_wd = float(get_setting("min_withdrawal", "20"))

        if amt < min_wd:
            await update.message.reply_text(
                f"❌ Minimum withdrawal is *{min_wd} USDT*.", parse_mode="Markdown"
            )
            return

        if amt > bal:
            await update.message.reply_text(
                f"❌ Insufficient balance.\nYour balance: *{bal:.4f} USDT*", parse_mode="Markdown"
            )
            return

        rate = get_withdraw_rate(lvl)
        etb = amt * rate

        cur.execute(
            "INSERT INTO withdraws(user_id,bank,account,amount,status,created_at) VALUES(?,?,?,?,?,?)",
            (user.id, context.user_data["bank"], context.user_data["account"], amt, "pending", now())
        )
        wid = cur.lastrowid
        conn.commit()

        caption = (
            f"💸 *Withdraw Request*\n\n"
            f"ID: `{wid}`\n"
            f"User: `{user.id}`\n"
            f"Bank: `{context.user_data['bank']}`\n"
            f"Account: `{context.user_data['account']}`\n"
            f"USDT: `{amt}`\n"
            f"ETB: `{etb}`"
        )
        btns = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"wd_a_{wid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"wd_r_{wid}"),
            InlineKeyboardButton("💬 Message", callback_data=f"wd_m_{user.id}")
        ]])
        await context.bot.send_message(ADMIN_ID, caption, reply_markup=btns, parse_mode="Markdown")

        await update.message.reply_text(
            f"✅ *Withdrawal Request Submitted!*\n\n"
            f"You will receive 💸 *{etb:.2f} ETB*\n"
            f"⏳ Waiting for MCT Finance Agent approval (1–24 hours).",
            parse_mode="Markdown"
        )
        context.user_data.clear()


# ─── WITHDRAW DECISION ───────────────────────────────────────────────────────
async def withdraw_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    action = parts[1]
    val = int(parts[2])

    if action == "m":
        context.user_data["admin_action"] = "msg_target"
        context.user_data["admin_msg_uid"] = val
        await q.message.reply_text(f"✉️ Type message to user `{val}`:", parse_mode="Markdown")
        return

    cur.execute("SELECT user_id, amount, bank, account, status FROM withdraws WHERE id=?", (val,))
    row = cur.fetchone()
    if not row:
        await q.answer("Not found", show_alert=True)
        return

    uid, amt, bank, account, status = row
    if status != "pending":
        await q.answer(f"Already {'Approved' if status == 'approved' else 'Rejected'}", show_alert=True)
        return

    cur.execute("SELECT level, balance FROM users WHERE id=?", (uid,))
    u_row = cur.fetchone()
    lvl = u_row[0] if u_row else 1
    rate = get_withdraw_rate(lvl)
    etb = amt * rate

    if action == "a":
        cur.execute("UPDATE users SET balance=balance-? WHERE id=?", (amt, uid))
        cur.execute("UPDATE withdraws SET status='approved' WHERE id=?", (val,))
        conn.commit()

        cur.execute("SELECT balance FROM users WHERE id=?", (uid,))
        new_bal = cur.fetchone()[0]

        try:
            await context.bot.send_message(
                uid,
                f"🎉 *Your Withdrawal Has Been Approved!* ✅\n\n"
                f"💵 ETB Value: *{etb:.2f} ETB*\n"
                f"💵 Amount: *{amt} USDT*\n"
                f"💵 ETB Rate: *{rate} ETB/USDT*\n"
                f"📊 Trade Level: *{lvl}*\n"
                f"🏦 Bank Name: *{bank}*\n"
                f"📋 Account Number: `{account}`\n"
                f"💰 Current Balance: *{new_bal:.4f} USDT*\n\n"
                f"Thank You! 🙏",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        new_status = "Approved ✅"
    else:
        cur.execute("UPDATE withdraws SET status='rejected' WHERE id=?", (val,))
        conn.commit()
        try:
            await context.bot.send_message(
                uid, f"❌ Your withdrawal of *{amt} USDT* was rejected.", parse_mode="Markdown"
            )
        except Exception:
            pass
        new_status = "Rejected ❌"

    new_text = (
        f"💸 Withdraw\n\nID: `{val}`\nUser: `{uid}`\nBank: `{bank}`\n"
        f"Account: `{account}`\nUSDT: `{amt}`\nETB: `{etb}`\nStatus: *{new_status}*"
    )
    try:
        await q.edit_message_text(new_text, parse_mode="Markdown")
    except Exception:
        pass


# ─── REFERRAL ────────────────────────────────────────────────────────────────
async def get_referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur.execute("SELECT referral_code FROM users WHERE id=?", (uid,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("❌ Account not found.")
        return
    ref_code = row[0]
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={ref_code}"
    ref_pct = get_setting("referral_bonus_pct", "25")

    cur.execute("SELECT id, name, balance FROM users WHERE referred_by=?", (ref_code,))
    refs = cur.fetchall()

    msg = (
        f"🔗 *Your Referral Link:*\n\n`{link}`\n\n"
        f"🎁 Earn *{ref_pct}% bonus* when your referral makes their first deposit!\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Your Referrals* ({len(refs)} total)\n"
    )
    if refs:
        for r_uid, r_name, r_bal in refs:
            msg += f"• {r_name} — `{r_uid}` | {r_bal:.4f} USDT\n"
    else:
        msg += "_No referrals yet. Share your link to start earning!_"

    await update.message.reply_text(msg, parse_mode="Markdown")


# ─── ACTIVATE OLD ACCOUNT ────────────────────────────────────────────────────
async def activate_old(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check for pending activation
    cur.execute("SELECT id FROM activations WHERE user_id=? AND status='pending'", (update.effective_user.id,))
    if cur.fetchone():
        await update.message.reply_text("⚠️ You have a pending activation request. Please wait for Admin approval/rejection before requesting again.")
        return

    await update.message.reply_text("📧 Enter the *Email* of your old account:", parse_mode="Markdown")
    context.user_data["activate"] = "email"
    context.user_data["wrong_attempts"] = 0

async def activate_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("activate")

    if step == "email":
        context.user_data["email"] = update.message.text
        context.user_data["activate"] = "phone"
        await update.message.reply_text("📱 Enter the *Phone Number* of your old account:", parse_mode="Markdown")

    elif step == "phone":
        context.user_data["phone"] = update.message.text
        context.user_data["activate"] = "old_balance"
        await update.message.reply_text(
            "💰 Enter the *balance amount* that was in your old account (USDT):",
            parse_mode="Markdown"
        )

    elif step == "old_balance":
        try:
            old_bal = float(update.message.text)
        except ValueError:
            await wrong_input(update, context, "❌ Please enter a valid amount (e.g. 50).")
            return

        context.user_data["old_balance"] = old_bal
        context.user_data["activate"] = None

        user = update.message.from_user
        email = context.user_data.get("email", "")
        phone = context.user_data.get("phone", "")

        cur.execute(
            "INSERT INTO activations(user_id,email,phone,old_balance,status,created_at) VALUES(?,?,?,?,?,?)",
            (user.id, email, phone, old_bal, "pending", now())
        )
        act_id = cur.lastrowid
        conn.commit()

        caption = (
            f"♻️ *OLD ACCOUNT ACTIVATION*\n\n"
            f"ID: `{act_id}`\n"
            f"User: `{user.id}`\n"
            f"Email: `{email}`\n"
            f"Phone: `{phone}`\n"
            f"Old Balance: *{old_bal} USDT*"
        )
        btns = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"act_a_{act_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"act_r_{act_id}"),
            InlineKeyboardButton("💬 Message", callback_data=f"act_m_{user.id}")
        ]])
        await context.bot.send_message(ADMIN_ID, caption, reply_markup=btns, parse_mode="Markdown")

        await update.message.reply_text(
            "✅ *Activation request submitted!*\n"
            "⏳ Waiting for MCT Finance Agent approval (15–60 min).",
            parse_mode="Markdown"
        )
        context.user_data.clear()


# ─── TUTORIAL ────────────────────────────────────────────────────────────────
async def tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, slot_number, title FROM tutorials WHERE category='tutorial' ORDER BY slot_number")
    items = cur.fetchall()
    if not items:
        await update.message.reply_text(
            "📚 *No tutorial videos have been uploaded yet.*\n\nPlease check back later!",
            parse_mode="Markdown"
        )
        return
    btns = [[InlineKeyboardButton(f"📹 {title}", callback_data=f"tut_view_{tid}")] for tid, _, title in items]
    await update.message.reply_text(
        "📚 *MCT Tutorial Videos*\n\nSelect a tutorial to watch:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(btns)
    )


# ─── SUPPORT ─────────────────────────────────────────────────────────────────
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sup_text = get_setting("support_text")
    sup_file = get_setting("support_file_id")
    sup_type = get_setting("support_media_type")

    if not sup_text:
        await update.message.reply_text(
            "🆘 *MCT Support*\n\nFor assistance, contact our support agent.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Contact MCT Agent", callback_data="contact_support")]
            ])
        )
        return

    try:
        if sup_type == "video" and sup_file:
            await update.message.reply_video(sup_file, caption=sup_text)
        elif sup_type == "photo" and sup_file:
            await update.message.reply_photo(sup_file, caption=sup_text)
        else:
            await update.message.reply_text(sup_text)
    except Exception:
        await update.message.reply_text(sup_text)


# ─── ADMIN COMMAND ───────────────────────────────────────────────────────────
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "🔧 *MCT Admin Panel*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Users", callback_data="adm_users_0"),
             InlineKeyboardButton("📥 Deposits", callback_data="adm_deps")],
            [InlineKeyboardButton("📤 Withdrawals", callback_data="adm_wds"),
             InlineKeyboardButton("♻️ Activations", callback_data="adm_acts")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
             InlineKeyboardButton("✉️ Message User", callback_data="adm_msguser")],
            [InlineKeyboardButton("📚 Tutorials", callback_data="adm_tut"),
             InlineKeyboardButton("🆘 Support", callback_data="adm_sup")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")],
        ])
    )

async def show_users_page(q, page: int):
    offset = page * USERS_PAGE_SIZE
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT id, name, balance, level FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
                (USERS_PAGE_SIZE, offset))
    users = cur.fetchall()

    lines = [f"👥 *Users* (Page {page + 1} / {max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)})\n"]
    for uid, name, bal, lvl in users:
        lines.append(f"• ID: `{uid}` | Name: {name} | Bal: {bal:.2f} | Lvl: {lvl}")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm_users_{page - 1}"))
    if offset + USERS_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"adm_users_{page + 1}"))
    nav_row = [nav] if nav else []
    nav_row.append([InlineKeyboardButton("👤 View User Details", callback_data="adm_viewuser")])

    try:
        await q.edit_message_text(
            "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(nav_row)
        )
    except Exception:
        await q.message.reply_text(
            "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(nav_row)
        )

def tut_slots_markup():
    btns = []
    for slot in range(1, 11):
        cur.execute("SELECT id, title FROM tutorials WHERE category='tutorial' AND slot_number=?", (slot,))
        row = cur.fetchone()
        if row:
            btns.append([InlineKeyboardButton(f"✅ Slot {slot}: {row[1]}", callback_data=f"adm_tslot_{slot}")])
        else:
            btns.append([InlineKeyboardButton(f"❌ Slot {slot} — empty", callback_data=f"adm_tslot_{slot}")])
    btns.append([InlineKeyboardButton("🔙 Back", callback_data="adm_back")])
    return InlineKeyboardMarkup(btns)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if update.effective_user.id != ADMIN_ID and data not in ("start_invest", "contact_support", "tut_view_"):
        if not data.startswith("tut_view_"):
            return

    if data == "start_invest":
        # Check for pending deposit in callback
        cur.execute("SELECT id FROM deposits WHERE user_id=? AND status='pending'", (update.effective_user.id,))
        if cur.fetchone():
            await q.message.reply_text("⚠️ You have a pending deposit request. Please wait for Admin approval/rejection before requesting again.")
            return

        context.user_data["awaiting_amount"] = True
        context.user_data["invest_min"] = 1
        context.user_data["wrong_attempts"] = 0
        await q.message.reply_text(
            "💰 *MCT Deposit*\n\n"
            "You can deposit from *1 USDT* and above.\n"
            "_(Accounts below 20 USDT are on Trade Level 0)_\n\n"
            "✏️💱 Enter the amount you want to deposit (USDT):",
            parse_mode="Markdown"
        )
        return

    if data == "contact_support":
        await q.message.reply_text("🆘 Contact MCT Support Agent for help.")
        return

    if data.startswith("tut_view_"):
        tid = int(data.split("_")[-1])
        cur.execute("SELECT title, description, file_id, media_type FROM tutorials WHERE id=?", (tid,))
        row = cur.fetchone()
        if not row:
            await q.message.reply_text("❌ Tutorial not found.")
            return
        title, desc, file_id, media_type = row
        caption = f"📚 *{title}*\n\n{desc}"
        try:
            if media_type == "video" and file_id:
                await q.message.reply_video(file_id, caption=caption, parse_mode="Markdown")
            elif media_type == "photo" and file_id:
                await q.message.reply_photo(file_id, caption=caption, parse_mode="Markdown")
            else:
                await q.message.reply_text(caption, parse_mode="Markdown")
        except Exception:
            await q.message.reply_text(caption, parse_mode="Markdown")
        return

    if data.startswith("adm_users_"):
        page = int(data.split("_")[-1])
        await show_users_page(q, page)

    elif data == "adm_deps":
        cur.execute("SELECT id, user_id, amount, status FROM deposits ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
        if not rows:
            await q.message.reply_text("No deposits found.")
            return
        lines = ["📥 *Recent Deposits*\n"]
        for did, uid, amt, st in rows:
            lines.append(f"• `{did}` | User: `{uid}` | {amt} USDT | {st}")
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif data == "adm_wds":
        cur.execute("SELECT id, user_id, amount, bank, status FROM withdraws ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
        if not rows:
            await q.message.reply_text("No withdrawals found.")
            return
        lines = ["📤 *Recent Withdrawals*\n"]
        for wid, uid, amt, bank, st in rows:
            lines.append(f"• `{wid}` | User: `{uid}` | {amt} USDT | {bank} | {st}")
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif data == "adm_acts":
        cur.execute("SELECT id, user_id, email, old_balance, status FROM activations ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
        if not rows:
            await q.message.reply_text("No activations found.")
            return
        lines = ["♻️ *Recent Activations*\n"]
        for aid, uid, email, old_b, st in rows:
            lines.append(f"• `{aid}` | User: `{uid}` | {email} | Old Bal: {old_b} USDT | {st}")
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif data == "adm_broadcast":
        context.user_data["admin_action"] = "broadcast_text"
        await q.message.reply_text("📢 Enter your broadcast message text:")

    elif data == "adm_msguser":
        context.user_data["admin_action"] = "msg_uid"
        await q.message.reply_text("✉️ Enter the User ID you want to message:")

    elif data == "adm_tut":
        await q.message.reply_text(
            "📚 *Tutorial Videos* (up to 10 slots)\n\nSelect a slot to manage:",
            parse_mode="Markdown",
            reply_markup=tut_slots_markup()
        )

    elif data.startswith("adm_tslot_"):
        slot = int(data.split("_")[-1])
        cur.execute("SELECT id, title, description, file_id, media_type FROM tutorials WHERE category='tutorial' AND slot_number=?", (slot,))
        row = cur.fetchone()
        if row:
            tid, title, desc, file_id, mt = row
            has_media = "✅ Has media" if file_id else "❌ No media"
            await q.message.reply_text(
                f"📹 *Video Slot {slot}*\n\n"
                f"📌 Title: *{title}*\n"
                f"📝 Description: {desc or 'Not set'}\n"
                f"🎬 Status: {has_media}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Set / Edit", callback_data=f"adm_tedit_{slot}")],
                    [InlineKeyboardButton("🗑 Delete Slot", callback_data=f"adm_tdel_{slot}")],
                    [InlineKeyboardButton("🔙 Back", callback_data="adm_tut")],
                ])
            )
        else:
            await q.message.reply_text(
                f"📹 *Video Slot {slot}*\n\n"
                f"📌 Title: Not set\n"
                f"📝 Description: Not set\n"
                f"🎬 Status: ❌ No video",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Set / Edit", callback_data=f"adm_tedit_{slot}")],
                    [InlineKeyboardButton("🔙 Back", callback_data="adm_tut")],
                ])
            )

    elif data.startswith("adm_tedit_"):
        slot = int(data.split("_")[-1])
        context.user_data["admin_action"] = "tut_title"
        context.user_data["tut_slot"] = slot
        context.user_data["admin_tut_cat"] = "tutorial"
        await q.message.reply_text(f"📚 *Slot {slot}* — Enter title:", parse_mode="Markdown")

    elif data.startswith("adm_tdel_"):
        slot = int(data.split("_")[-1])
        cur.execute("DELETE FROM tutorials WHERE category='tutorial' AND slot_number=?", (slot,))
        conn.commit()
        await q.message.reply_text(f"✅ Slot {slot} deleted.", reply_markup=tut_slots_markup())

    elif data == "adm_sup":
        sup_text = get_setting("support_text") or "Not set"
        has_media = "✅ Has media" if get_setting("support_file_id") else "❌ No media"
        preview = sup_text[:200] + ("..." if len(sup_text) > 200 else "")
        await q.message.reply_text(
            f"🆘 Support / Help\n\n📝 Current text:\n{preview}\n\n🖼 Media: {has_media}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Set / Change Text", callback_data="adm_sup_edit")],
                [InlineKeyboardButton("🗑 Delete", callback_data="adm_sup_del")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_back")],
            ])
        )

    elif data == "adm_sup_edit":
        context.user_data["admin_action"] = "sup_text"
        await q.message.reply_text("✏️ Enter new support text:")

    elif data == "adm_sup_del":
        set_setting("support_text", "")
        set_setting("support_file_id", "")
        set_setting("support_media_type", "")
        await q.message.reply_text("✅ Support content deleted.")

    elif data == "adm_settings":
        ref_pct = get_setting("referral_bonus_pct", "25")
        await q.message.reply_text(
            f"⚙️ *Settings*\n\n"
            f"💳 TRC20 Address:\n`{trc20()}`\n\n"
            f"💵 Min Withdrawal: *{get_setting('min_withdrawal')} USDT*\n"
            f"🎁 Referral Bonus: *{ref_pct}%*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Change TRC20 Address", callback_data="adm_set_trc20")],
                [InlineKeyboardButton("💵 Change Min Withdrawal", callback_data="adm_set_minwd")],
                [InlineKeyboardButton("🎁 Change Referral Bonus %", callback_data="adm_set_refpct")],
            ])
        )

    elif data == "adm_set_trc20":
        context.user_data["admin_action"] = "set_trc20"
        await q.message.reply_text("💳 Enter new TRC20 wallet address:")

    elif data == "adm_set_minwd":
        context.user_data["admin_action"] = "set_minwd"
        await q.message.reply_text("💵 Enter new minimum withdrawal amount (USDT):")

    elif data == "adm_set_refpct":
        context.user_data["admin_action"] = "set_refpct"
        await q.message.reply_text(f"🎁 Enter new referral bonus percentage (e.g. 25 for 25%):")

    elif data == "adm_viewuser":
        context.user_data["admin_action"] = "view_user"
        await q.message.reply_text("👤 Enter User ID to view:")

    elif data == "adm_back":
        await q.message.reply_text(
            "🔧 *MCT Admin Panel*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Users", callback_data="adm_users_0"),
                 InlineKeyboardButton("📥 Deposits", callback_data="adm_deps")],
                [InlineKeyboardButton("📤 Withdrawals", callback_data="adm_wds"),
                 InlineKeyboardButton("♻️ Activations", callback_data="adm_acts")],
                [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
                 InlineKeyboardButton("✉️ Message User", callback_data="adm_msguser")],
                [InlineKeyboardButton("📚 Tutorials", callback_data="adm_tut"),
                 InlineKeyboardButton("🆘 Support", callback_data="adm_sup")],
                [InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")],
            ])
        )

    elif data.startswith("usr_addbal_"):
        uid = int(data.split("_")[-1])
        context.user_data["admin_action"] = "addbal_amount"
        context.user_data["admin_target_uid"] = uid
        await q.message.reply_text(f"➕ Amount to add to user `{uid}`:", parse_mode="Markdown")

    elif data.startswith("usr_subbal_"):
        uid = int(data.split("_")[-1])
        context.user_data["admin_action"] = "subbal_amount"
        context.user_data["admin_target_uid"] = uid
        await q.message.reply_text(f"➖ Amount to subtract from user `{uid}`:", parse_mode="Markdown")

    elif data.startswith("usr_msg_"):
        uid = int(data.split("_")[-1])
        context.user_data["admin_action"] = "msg_target"
        context.user_data["admin_msg_uid"] = uid
        await q.message.reply_text(f"✉️ Message to user `{uid}`:", parse_mode="Markdown")

    elif data.startswith("usr_del_"):
        uid = int(data.split("_")[-1])
        cur.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        await q.message.reply_text(f"✅ User `{uid}` deleted.", parse_mode="Markdown")


# ─── ADMIN TEXT HANDLER ──────────────────────────────────────────────────────
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("admin_action")

    if action == "broadcast_text":
        context.user_data["broadcast_text"] = update.message.text
        context.user_data["admin_action"] = "broadcast_media"
        await update.message.reply_text("📸 Send a photo/video to attach, or type *skip*:", parse_mode="Markdown")

    elif action == "broadcast_media":
        if update.message.text.lower() == "skip":
            await do_broadcast(update, context, text=context.user_data["broadcast_text"])
            context.user_data.clear()

    elif action == "msg_uid":
        try:
            uid = int(update.message.text)
            context.user_data["admin_msg_uid"] = uid
            context.user_data["admin_action"] = "msg_target"
            await update.message.reply_text(f"✉️ Message to user `{uid}`:", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            context.user_data.clear()

    elif action == "msg_target":
        uid = context.user_data.get("admin_msg_uid")
        if uid:
            try:
                await context.bot.send_message(uid, f"📣 *MCT Message:*\n\n{update.message.text}", parse_mode="Markdown")
                await update.message.reply_text(f"✅ Message sent to `{uid}`.", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ Failed: {e}")
        context.user_data.clear()

    elif action == "set_trc20":
        addr = update.message.text.strip()
        set_setting("trc20_address", addr)
        await update.message.reply_text(f"✅ TRC20 updated:\n`{addr}`", parse_mode="Markdown")
        context.user_data.clear()

    elif action == "set_minwd":
        try:
            val = float(update.message.text)
            set_setting("min_withdrawal", str(val))
            await update.message.reply_text(f"✅ Min withdrawal set to *{val} USDT*.", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ Invalid number.")
        context.user_data.clear()

    elif action == "set_refpct":
        try:
            val = float(update.message.text)
            set_setting("referral_bonus_pct", str(val))
            await update.message.reply_text(f"✅ Referral bonus set to *{val}%*.", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ Invalid number.")
        context.user_data.clear()

    elif action == "tut_title":
        context.user_data["tut_title"] = update.message.text
        context.user_data["admin_action"] = "tut_desc"
        await update.message.reply_text("📝 Enter description:")

    elif action == "tut_desc":
        context.user_data["tut_desc"] = update.message.text
        context.user_data["admin_action"] = "tut_media"
        await update.message.reply_text("📹 Send a photo/video (or type *skip* for text only):", parse_mode="Markdown")

    elif action == "tut_media":
        if update.message.text.lower() == "skip":
            slot = context.user_data.get("tut_slot")
            cur.execute("DELETE FROM tutorials WHERE category='tutorial' AND slot_number=?", (slot,))
            cur.execute(
                "INSERT INTO tutorials(slot_number,title,description,file_id,media_type,category) VALUES(?,?,?,?,?,?)",
                (slot, context.user_data["tut_title"], context.user_data["tut_desc"], None, "text", "tutorial")
            )
            conn.commit()
            await update.message.reply_text("✅ Tutorial saved!", reply_markup=tut_slots_markup())
            context.user_data.clear()

    elif action == "sup_text":
        context.user_data["sup_text"] = update.message.text
        context.user_data["admin_action"] = "sup_media"
        await update.message.reply_text("📸 Send a photo/video (or type *skip*):", parse_mode="Markdown")

    elif action == "sup_media":
        if update.message.text.lower() == "skip":
            set_setting("support_text", context.user_data["sup_text"])
            set_setting("support_file_id", "")
            set_setting("support_media_type", "text")
            await update.message.reply_text("✅ Support content saved!")
            context.user_data.clear()

    elif action == "view_user":
        try:
            uid = int(update.message.text)
            cur.execute(
                "SELECT id,name,phone,email,balance,level,referral_code,referred_by FROM users WHERE id=?", (uid,)
            )
            row = cur.fetchone()
            if not row:
                await update.message.reply_text("❌ User not found.")
            else:
                uid2, name, phone, email, bal, lvl, ref_code, ref_by = row
                ref_pct = get_setting("referral_bonus_pct", "25")
                await update.message.reply_text(
                    f"👤 *{name}*\n\n"
                    f"   ID: `{uid2}`\n"
                    f"   Email: `{email}`\n"
                    f"   Phone Number: `{phone}`\n"
                    f"   💰 Balance: *{bal:.4f} USDT* |  Level: *{lvl}*\n"
                    f"   🎁 Referral Bonus: *{ref_pct}%*\n"
                    f"   Referred by: `{ref_by or 'none'}`\n"
                    f"   Referral code: `{ref_code}`",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add Balance", callback_data=f"usr_addbal_{uid2}"),
                         InlineKeyboardButton("➖ Reduce Balance", callback_data=f"usr_subbal_{uid2}")],
                        [InlineKeyboardButton("✉️ Message", callback_data=f"usr_msg_{uid2}"),
                         InlineKeyboardButton("🗑 Delete", callback_data=f"usr_del_{uid2}")]
                    ])
                )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
        context.user_data.clear()

    elif action == "addbal_amount":
        try:
            amt = float(update.message.text)
            uid = context.user_data["admin_target_uid"]
            cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (amt, uid))
            conn.commit()
            await update.message.reply_text(f"✅ Added *{amt} USDT* to `{uid}`.", parse_mode="Markdown")
            try:
                await context.bot.send_message(uid, f"💰 *{amt} USDT* has been added to your balance by MCT Admin!", parse_mode="Markdown")
            except Exception:
                pass
        except (ValueError, KeyError):
            await update.message.reply_text("❌ Invalid amount.")
        context.user_data.clear()

    elif action == "subbal_amount":
        try:
            amt = float(update.message.text)
            uid = context.user_data["admin_target_uid"]
            cur.execute("UPDATE users SET balance=MAX(0, balance-?) WHERE id=?", (amt, uid))
            conn.commit()
            await update.message.reply_text(f"✅ Subtracted *{amt} USDT* from `{uid}`.", parse_mode="Markdown")
        except (ValueError, KeyError):
            await update.message.reply_text("❌ Invalid amount.")
        context.user_data.clear()


# ─── BROADCAST ───────────────────────────────────────────────────────────────
async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       text: str, photo=None, video=None):
    cur.execute("SELECT id FROM users")
    users = cur.fetchall()
    success, fail = 0, 0
    for (uid,) in users:
        try:
            if photo:
                await context.bot.send_photo(uid, photo, caption=text, parse_mode="Markdown")
            elif video:
                await context.bot.send_video(uid, video, caption=text, parse_mode="Markdown")
            else:
                await context.bot.send_message(uid, text, parse_mode="Markdown")
            success += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"📢 *Broadcast Complete!*\n✅ Sent: {success}\n❌ Failed: {fail}", parse_mode="Markdown")


# ─── MEDIA HANDLER ───────────────────────────────────────────────────────────
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        action = context.user_data.get("admin_action")

        if action == "broadcast_media":
            txt = context.user_data.get("broadcast_text", "")
            if update.message.photo:
                await do_broadcast(update, context, text=txt, photo=update.message.photo[-1].file_id)
            elif update.message.video:
                await do_broadcast(update, context, text=txt, video=update.message.video.file_id)
            context.user_data.clear()
            return

        if action == "tut_media":
            slot = context.user_data.get("tut_slot")
            file_id = None
            media_type = "text"
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                media_type = "photo"
            elif update.message.video:
                file_id = update.message.video.file_id
                media_type = "video"
            cur.execute("DELETE FROM tutorials WHERE category='tutorial' AND slot_number=?", (slot,))
            cur.execute(
                "INSERT INTO tutorials(slot_number,title,description,file_id,media_type,category) VALUES(?,?,?,?,?,?)",
                (slot, context.user_data.get("tut_title"), context.user_data.get("tut_desc"),
                 file_id, media_type, "tutorial")
            )
            conn.commit()
            await update.message.reply_text("✅ Tutorial saved!", reply_markup=tut_slots_markup())
            context.user_data.clear()
            return

        if action == "sup_media":
            file_id = None
            media_type = "text"
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                media_type = "photo"
            elif update.message.video:
                file_id = update.message.video.file_id
                media_type = "video"
            set_setting("support_text", context.user_data.get("sup_text", ""))
            set_setting("support_file_id", file_id or "")
            set_setting("support_media_type", media_type)
            await update.message.reply_text("✅ Support content saved!")
            context.user_data.clear()
            return

    if context.user_data.get("awaiting_screenshot"):
        if update.message.photo:
            context.user_data["photo"] = update.message.photo[-1].file_id
            context.user_data["awaiting_screenshot"] = False
            context.user_data["wrong_attempts"] = 0
            await update.message.reply_text(
                "📄 *Screenshot received!*\n\nNow send your *Transaction ID (TXN)*:",
                parse_mode="Markdown"
            )
            context.user_data["awaiting_txn"] = True
        else:
            await update.message.reply_text("❌ Please upload a *photo* screenshot of your payment.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❓ No payment expected. Use the menu to start a deposit.")


# ─── ADMIN /approve COMMAND ──────────────────────────────────────────────────
async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        deposit_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /approve <deposit_id>")
        return
    cur.execute("SELECT user_id, amount, status FROM deposits WHERE id=?", (deposit_id,))
    data = cur.fetchone()
    if not data:
        await update.message.reply_text("❌ Deposit not found.")
        return
    if data[2] == "approved":
        await update.message.reply_text("⚠️ Already approved.")
        return
    uid, amount = data[0], data[1]
    level = get_trade_level(amount)
    cur.execute("UPDATE users SET balance=balance+?, level=? WHERE id=?", (amount, level, uid))
    cur.execute("UPDATE deposits SET status='approved' WHERE id=?", (deposit_id,))
    conn.commit()
    await update.message.reply_text(f"✅ Deposit {deposit_id} approved.")
    try:
        await context.bot.send_message(uid, f"✅ Deposit of *{amount} USDT* approved! Level: {level}", parse_mode="Markdown")
    except Exception:
        pass


# ─── ROUTER ──────────────────────────────────────────────────────────────────
async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id == ADMIN_ID and context.user_data.get("admin_action"):
        await admin_text_handler(update, context)
        return

    if context.user_data.get("register"):
        await register(update, context)
        return

    if context.user_data.get("awaiting_amount"):
        await receive_amount(update, context)
        return

    if context.user_data.get("awaiting_txn"):
        await txn(update, context)
        return

    if context.user_data.get("withdraw"):
        await withdraw_process(update, context)
        return

    if context.user_data.get("activate"):
        await activate_process(update, context)
        return

    if context.user_data.get("awaiting_screenshot"):
        await update.message.reply_text(
            "📸 Please *upload a screenshot* of your payment (photo).",
            parse_mode="Markdown"
        )
        return

    if text == "🔥 Choose Trade Level":
        await choose_level(update, context)
    elif text == "💰 Deposit":
        await deposit_flow(update, context)
    elif text == "💰 Balance":
        await balance(update)
    elif text == "📤 Withdraw":
        await withdraw(update, context)
    elif text == "📋 Status":
        await status(update)
    elif text == "♻️ Activate Old Account":
        await activate_old(update, context)
    elif text == "🔗 Get Referral Link":
        await get_referral_link(update, context)
    elif text == "📚 Tutorial":
        await tutorial(update, context)
    elif text == "🆘 Support":
        await support(update, context)
    else:
        await update.message.reply_text(ROBOT_MSG, reply_markup=SUPPORT_BUTTON)


# ─── DB MIGRATION ────────────────────────────────────────────────────────────
def migrate_db():
    migrations = [
        "ALTER TABLE users ADD COLUMN referral_code TEXT",
        "ALTER TABLE users ADD COLUMN referred_by TEXT",
        "ALTER TABLE users ADD COLUMN bonus_claimed INTEGER DEFAULT 0",
        "ALTER TABLE deposits ADD COLUMN created_at TEXT",
        "ALTER TABLE withdraws ADD COLUMN created_at TEXT",
        "ALTER TABLE activations ADD COLUMN old_balance REAL DEFAULT 0",
        "ALTER TABLE tutorials ADD COLUMN slot_number INTEGER",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
        except Exception:
            pass

    try:
        cur.execute("ALTER TABLE activations ADD COLUMN txn TEXT")
    except Exception:
        pass

    cur.execute("SELECT id FROM users WHERE referral_code IS NULL OR referral_code=''")
    for (uid,) in cur.fetchall():
        code = generate_referral_code()
        cur.execute("UPDATE users SET referral_code=? WHERE id=?", (code, uid))

    cur.execute("SELECT id FROM users WHERE bonus_claimed=0 OR bonus_claimed IS NULL")
    for (uid,) in cur.fetchall():
        cur.execute("UPDATE users SET balance=balance+?, bonus_claimed=1 WHERE id=?", (REGISTRATION_BONUS, uid))

    conn.commit()


# ─── RUN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    migrate_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, media_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))
    app.add_handler(CallbackQueryHandler(deposit_decision, pattern="^dep_"))
    app.add_handler(CallbackQueryHandler(activation_decision, pattern="^act_"))
    app.add_handler(CallbackQueryHandler(withdraw_decision, pattern="^wd_"))
    app.add_handler(CallbackQueryHandler(admin_callback,
                    pattern="^(adm_|usr_|start_invest|contact_support|tut_view_)"))

    print("MCT Bot is running...")
    app.run_polling()
