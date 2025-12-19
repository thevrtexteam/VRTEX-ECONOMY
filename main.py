# main.py - Quarter 1
import discord
import random
from discord.ext import commands, tasks
from discord import app_commands, Interaction
import os
import asyncio
import motor.motor_asyncio
from datetime import datetime, timedelta

# -------------------- CONFIG --------------------
TOKEN = os.getenv("DISCORD_TOKEN")  # Discord Bot Token
MONGO_URI = os.getenv("MONGO_URI")  # MongoDB URI
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
TEAM_IDS = [int(x) for x in os.getenv("TEAM_IDS", "").split(",") if x.strip().isdigit()]
TOPGG_LINK = os.getenv("TOPGG_LINK", "")

DEFAULT_PREFIX = "!"  # Default text prefix for servers without custom prefix
DEFAULT_CURRENCY = {"name": "coins", "symbol": "🪙"}

# -------------------- MONGO DB --------------------
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client.vrtex_economy

servers_collection = db.servers
users_collection = db.users

# -------------------- HELPER FUNCTIONS --------------------
async def get_server_prefix(guild_id: int):
    """Return the prefix for a server; default if not set."""
    server = await servers_collection.find_one({"guild_id": guild_id})
    if server and server.get("custom_prefix"):
        return server["custom_prefix"]
    return DEFAULT_PREFIX

async def get_currency_settings(guild_id: int):
    """Return currency name & symbol for a server."""
    server = await servers_collection.find_one({"guild_id": guild_id})
    if server and server.get("currency"):
        return server["currency"]
    return DEFAULT_CURRENCY

async def setup_user(user_id: int):
    """Ensure a user exists in DB."""
    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        await users_collection.insert_one({
            "user_id": user_id,
            "balance": 0,
            "bank": 0,
            "work_streak": 0,
            "job": None,
            "job_level": 1,
            "commands_used": 0,
            "times_worked": 0,
            "times_bought": 0,
            "times_robbed": 0,
            "times_robbed_others": 0,
            "times_fired": 0
        })

# -------------------- BOT SETUP --------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=DEFAULT_PREFIX, intents=intents)

# -------------------- EVENTS --------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.event
async def on_guild_join(guild):
    """Setup default server settings on join."""
    existing = await servers_collection.find_one({"guild_id": guild.id})
    if not existing:
        await servers_collection.insert_one({
            "guild_id": guild.id,
            "custom_prefix": None,
            "currency": DEFAULT_CURRENCY,
            "vrt_ex_server_plus": False
        })

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    prefix = await get_server_prefix(message.guild.id)
    if message.content.startswith(prefix):
        ctx = await bot.get_context(message)
        await bot.invoke(ctx)
    await bot.process_commands(message)

# main.py - Quarter 2 (Economy Core)

# -------------------- JOBS & WORK --------------------
jobs_list = {
    1: "Cashier",
    2: "Guard",
    3: "Farmer",
    4: "Miner",
    5: "Chef"
}

@bot.tree.command(name="work", description="Work your job to earn coins")
async def work(interaction: Interaction):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    
    if not user_data.get("job"):
        await interaction.response.send_message("You don't have a job! Use `/job` to get one.", ephemeral=True)
        return
    
    last_work = user_data.get("last_work")
    now = datetime.utcnow()
    if last_work:
        delta = now - last_work
        if delta < timedelta(hours=1):
            await interaction.response.send_message("You can only work once per hour!", ephemeral=True)
            return
    
    # Give coins
    earned = 500 * user_data["job_level"]
    new_balance = user_data["balance"] + earned
    streak = user_data.get("work_streak", 0) + 1
    times_worked = user_data.get("times_worked", 0) + 1
    
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "work_streak": streak, "last_work": now, "times_worked": times_worked}}
    )
    
    await interaction.response.send_message(f"You worked as a {jobs_list[user_data['job']]} and earned {earned} 🪙!\nYour current streak: {streak}")

    # Firing logic: if streak missed 2 times in a row for 3 days
    if streak < 3:
        await interaction.user.send("You missed work streak requirements. You have been fired due to inactivity!")
        await users_collection.update_one(
            {"user_id": interaction.user.id},
            {"$set": {"job": None, "work_streak": 0}, "$inc": {"times_fired": 1}}
        )

@bot.tree.command(name="job", description="Get or check your job")
async def job(interaction: Interaction):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    
    if user_data.get("job"):
        job_name = jobs_list[user_data["job"]]
        await interaction.response.send_message(f"You currently work as a {job_name} (Level {user_data['job_level']})")
        return
    
    # Assign first job randomly
    import random
    new_job = random.choice(list(jobs_list.keys()))
    await users_collection.update_one({"user_id": interaction.user.id}, {"$set": {"job": new_job}})
    await interaction.response.send_message(f"You have been assigned the job: {jobs_list[new_job]}")

# -------------------- MONTHLY --------------------
@bot.tree.command(name="monthly", description="Get your monthly payout (30000 coins)")
async def monthly(interaction: Interaction):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    
    last_monthly = user_data.get("last_monthly")
    now = datetime.utcnow()
    if last_monthly:
        delta = now - last_monthly
        if delta < timedelta(days=30):
            await interaction.response.send_message("You can only claim monthly once every 30 days!", ephemeral=True)
            return
    
    new_balance = user_data["balance"] + 30000
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "last_monthly": now}}
    )
    await interaction.response.send_message("You received your monthly payout of 30000 🪙!")

# -------------------- SHOP & BUY --------------------
shop_items = {
    1: {"name": "Bed", "price": 5000},
    2: {"name": "TV", "price": 10000},
    3: {"name": "House", "price": 50000},
    4: {"name": "Food Pack", "price": 1000},
    5: {"name": "Weapon", "price": 20000}
}

@bot.tree.command(name="shop", description="View shop items")
async def shop(interaction: Interaction):
    msg = "**Available Shop Items:**\n"
    for item_id, item in shop_items.items():
        msg += f"{item_id}. {item['name']} - {item['price']} 🪙\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="buy", description="Buy an item from the shop")
@app_commands.describe(item_id="Enter the item number from /shop")
async def buy(interaction: Interaction, item_id: int):
    await setup_user(interaction.user.id)
    if item_id not in shop_items:
        await interaction.response.send_message("Invalid item ID!", ephemeral=True)
        return
    
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    item = shop_items[item_id]
    
    if user_data["balance"] < item["price"]:
        await interaction.response.send_message("You don't have enough coins!", ephemeral=True)
        return
    
    # Deduct coins and add to inventory
    new_balance = user_data["balance"] - item["price"]
    inventory = user_data.get("inventory", [])
    inventory.append(item["name"])
    times_bought = user_data.get("times_bought", 0) + 1
    
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "inventory": inventory, "times_bought": times_bought}}
    )
    
    await interaction.response.send_message(f"You bought **{item['name']}** for {item['price']} 🪙!")

# -------------------- USE ITEMS --------------------
@bot.tree.command(name="use", description="Use an item from your inventory")
@app_commands.describe(item_name="Name of the item to use")
async def use(interaction: Interaction, item_name: str):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    inventory = user_data.get("inventory", [])
    
    if item_name not in inventory:
        await interaction.response.send_message("You don't own this item!", ephemeral=True)
        return
    
    inventory.remove(item_name)
    await users_collection.update_one({"user_id": interaction.user.id}, {"$set": {"inventory": inventory}})
    await interaction.response.send_message(f"You used **{item_name}**!")

# main.py - Quarter 3 (Leaderboards, Settings, Weekly)

# -------------------- WEEKLY PAYOUT (VRTEX+ ONLY) --------------------
@bot.tree.command(name="weekly", description="Get your weekly payout (only for VRTEX+ users)")
async def weekly(interaction: Interaction):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    
    # Check if user has VRTEX+
    if not user_data.get("vRTEX_plus", False):
        await interaction.response.send_message("This command is only available for VRTEX+ users!", ephemeral=True)
        return
    
    last_weekly = user_data.get("last_weekly")
    now = datetime.utcnow()
    if last_weekly:
        delta = now - last_weekly
        if delta < timedelta(days=7):
            await interaction.response.send_message("You can only claim weekly once every 7 days!", ephemeral=True)
            return
    
    payout = 7000
    new_balance = user_data["balance"] + payout
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "last_weekly": now}}
    )
    await interaction.response.send_message(f"You received your weekly payout of {payout} 🪙!")

# -------------------- SETTINGS COMMAND --------------------
@bot.tree.command(name="settings", description="Change server prefix, currency name, or currency symbol (Admins only)")
@app_commands.describe(
    prefix="Set a custom prefix (VRTEX SERVER+ only)",
    currency_name="Change your currency name",
    currency_symbol="Change your currency symbol"
)
async def settings(interaction: Interaction, prefix: str = None, currency_name: str = None, currency_symbol: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only admins can change settings!", ephemeral=True)
        return
    
    server_id = interaction.guild.id
    server_data = await servers_collection.find_one({"server_id": server_id}) or {}

    update_dict = {}
    
    # Custom prefix only for VRTEX SERVER+
    if prefix:
        if server_data.get("vRTEX_server_plus", False):
            update_dict["prefix"] = prefix
        else:
            await interaction.response.send_message("Only VRTEX SERVER+ servers can set a custom prefix.", ephemeral=True)
            return
    
    if currency_name:
        update_dict["currency_name"] = currency_name
    if currency_symbol:
        update_dict["currency_symbol"] = currency_symbol
    
    if update_dict:
        await servers_collection.update_one({"server_id": server_id}, {"$set": update_dict}, upsert=True)
        await interaction.response.send_message("Server settings updated successfully!")
    else:
        await interaction.response.send_message("No valid changes provided.", ephemeral=True)

# -------------------- SERVER LEADERBOARD --------------------
@bot.tree.command(name="server_leaderboard", description="View server leaderboard")
async def server_leaderboard(interaction: Interaction):
    server_id = interaction.guild.id
    server_users = await users_collection.find({"server_id": server_id}).to_list(length=100)
leaderboard = sorted(server_users, key=lambda u: u.get("balance", 0), reverse=True)[:10]
    
    msg = "**Server Leaderboard:**\n"
    for i, user in enumerate(leaderboard, 1):
        member = interaction.guild.get_member(user["user_id"])
        name = member.mention if member else f"UserID {user['user_id']}"
        msg += f"{i}. {name} - {user['balance']} 🪙\n"
    
    await interaction.response.send_message(msg)

# -------------------- GLOBAL LEADERBOARD --------------------
@bot.tree.command(name="global_leaderboard", description="View global leaderboard")
async def global_leaderboard(interaction: Interaction):
    global_users = await users_collection.find().to_list(length=1000)
    leaderboard = sorted(global_users, key=lambda u: u.get("balance", 0), reverse=True)[:10]

    
    msg = "**Global Leaderboard:**\n"
    for i, user in enumerate(leaderboard, 1):
        msg += f"{i}. <@{user['user_id']}> - {user['balance']} 🪙\n"
    
    await interaction.response.send_message(msg)

# main.py - Quarter 4 (Economy Actions, Recap, Daily/Crime/Robbery/etc.)

# -------------------- DAILY PAYOUT --------------------
@bot.tree.command(name="daily", description="Claim your daily coins")
async def daily(interaction: Interaction):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    now = datetime.utcnow()
    
    last_daily = user_data.get("last_daily")
    if last_daily and (now - last_daily).total_seconds() < 86400:  # 24h
        await interaction.response.send_message("You can only claim daily once every 24 hours!", ephemeral=True)
        return

    payout = 1000
    new_balance = user_data["balance"] + payout
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "last_daily": now},
         "$inc": {"daily_claims": 1, "total_earned": payout}}
    )
    await interaction.response.send_message(f"You claimed your daily {payout} 🪙!")

# -------------------- WORK / JOB --------------------
@bot.tree.command(name="work", description="Do your work shift")
async def work(interaction: Interaction):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    
    now = datetime.utcnow()
    last_work = user_data.get("last_work")
    
    if last_work and (now - last_work).total_seconds() < 43200:  # 12h cooldown
        await interaction.response.send_message("You already worked recently. Wait before working again.", ephemeral=True)
        return
    
    # Job streaks
    streak = user_data.get("job_streak", 0)
    if last_work and (now - last_work).total_seconds() > 172800:  # >2 days, reset streak
        streak = 0
        # Send DM about firing if missed work twice in a row
        try:
            await interaction.user.send("You missed work for 2 days. You are fired from your job!")
        except:
            pass

    earnings = 2000 + (streak * 200)
    new_balance = user_data["balance"] + earnings
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "last_work": now, "job_streak": streak + 1},
         "$inc": {"total_worked": 1, "total_earned": earnings}}
    )
    await interaction.response.send_message(f"You worked your shift and earned {earnings} 🪙! Streak: {streak+1}")

# -------------------- DEPOSIT & WITHDRAW --------------------
@bot.tree.command(name="deposit", description="Deposit coins into your bank")
@app_commands.describe(amount="Amount to deposit")
async def deposit(interaction: Interaction, amount: int):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    
    if amount > user_data["balance"]:
        await interaction.response.send_message("You don't have enough coins!", ephemeral=True)
        return
    
    new_balance = user_data["balance"] - amount
    new_bank = user_data.get("bank", 0) + amount
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "bank": new_bank}}
    )
    await interaction.response.send_message(f"Deposited {amount} 🪙 to your bank!")

@bot.tree.command(name="withdraw", description="Withdraw coins from your bank")
@app_commands.describe(amount="Amount to withdraw")
async def withdraw(interaction: Interaction, amount: int):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})

    
    bank_amount = user_data.get("bank", 0)
    if amount > bank_amount:
        await interaction.response.send_message("Not enough coins in your bank!", ephemeral=True)
        return
    
    new_balance = user_data["balance"] + amount
    new_bank = bank_amount - amount
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$set": {"balance": new_balance, "bank": new_bank}}
    )
    await interaction.response.send_message(f"Withdrew {amount} 🪙 from your bank!")

# -------------------- ROB / CRIME / BEG --------------------
@bot.tree.command(name="rob", description="Try to steal coins from another user")
@app_commands.describe(user="User to rob")
async def rob(interaction: Interaction, user: discord.Member):
    if user.bot or user.id == interaction.user.id:
        await interaction.response.send_message("Invalid target!", ephemeral=True)
        return
    
    await setup_user(interaction.user.id)
    await setup_user(user.id)
    
    success = random.choice([True, False])
    amount = random.randint(100, 2000)
    
    if success:
        await users_collection.update_one({"user_id": interaction.user.id}, {"$inc": {"balance": amount, "total_robbed": 1}})
        await users_collection.update_one({"user_id": user.id}, {"$inc": {"balance": -amount, "total_got_robbed": 1}})
        await interaction.response.send_message(f"You successfully robbed {amount} 🪙 from {user.mention}!")
    else:
        await interaction.response.send_message("Your robbery attempt failed!")

@bot.tree.command(name="beg", description="Beg for coins")
async def beg(interaction: Interaction):
    await setup_user(interaction.user.id)
    amount = random.randint(50, 500)
    await users_collection.update_one(
        {"user_id": interaction.user.id},
        {"$inc": {"balance": amount, "total_earned": amount}}
    )
    await interaction.response.send_message(f"You begged and received {amount} 🪙!")

# -------------------- RECAP COMMAND --------------------
@bot.tree.command(name="recap", description="Show your stats in VRTEX Economy")
async def recap(interaction: Interaction):
    await setup_user(interaction.user.id)
    user_data = await users_collection.find_one({"user_id": interaction.user.id})
    
    total_earned = user_data.get("total_earned", 0)
    total_worked = user_data.get("total_worked", 0)
    total_bought = user_data.get("total_bought", 0)
    total_robbed = user_data.get("total_robbed", 0)
    total_got_robbed = user_data.get("total_got_robbed", 0)
    total_fired = user_data.get("total_fired", 0)
    total_commands_used = user_data.get("commands_used", 0)
    
    msg = f"**VRTEX Economy Recap for {interaction.user.mention}**\n"
    msg += f"🪙 Coins earned: {total_earned}\n"
    msg += f"💼 Times worked: {total_worked}\n"
    msg += f"🛒 Items bought: {total_bought}\n"
    msg += f"🕵️ Times robbed: {total_robbed}\n"
    msg += f"⚠️ Times got robbed: {total_got_robbed}\n"
    msg += f"❌ Times fired: {total_fired}\n"
    msg += f"📊 Total commands used: {total_commands_used}\n"
    
    await interaction.response.send_message(msg)

# -------------------- BOT RUN --------------------
# Make sure your TOKEN is set in environment variables or directly

TOKEN = os.getenv("DISCORD_TOKEN")  # Or replace with "YOUR_BOT_TOKEN" directly
bot.run(TOKEN)
