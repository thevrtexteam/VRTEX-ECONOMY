from web_server import keep_alive

# Your other imports (e.g., discord.py) go here

# Start the keep-alive server before the bot logs in
keep_alive()

# Your bot's code goes here
import discord
from discord.ext import commands, tasks
import os
import json
import datetime
import random
import asyncio

# Load environment variables
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
TEAM_IDS = list(map(int, os.getenv("TEAM_IDS", "").split(",")))
TOPGG_LINK = os.getenv("TOPGG_LINK", "")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=commands.when_mentioned_or("ve"), intents=intents, case_insensitive=True)

# JSON storage files
FILES = {
    "users": "users.json",
    "servers": "servers.json",
    "businesses": "businesses.json",
    "items": "items.json",
    "jobs": "jobs.json",
    "market": "market.json",
    "quests": "quests.json"
}

# Ensure JSON files exist
for file in FILES.values():
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump({}, f)

# JSON helpers
def load_json(file_key):
    with open(FILES[file_key], "r") as f:
        return json.load(f)

def save_json(file_key, data):
    with open(FILES[file_key], "w") as f:
        json.dump(data, f, indent=4)

# User helpers
async def get_user(user_id):
    users = load_json("users")
    if str(user_id) not in users:
        users[str(user_id)] = {
            "wallet": 0,
            "bank": 0,
            "daily_claimed": None,
            "drop_claimed": None,
            "membership": False,
            "xp": 0,
            "level": 1,
            "job": None,
            "job_streak": 0,
            "items": {},
            "businesses": {}
        }
        save_json("users", users)
    return users[str(user_id)]

async def update_user(user_id, data):
    users = load_json("users")
    users[str(user_id)].update(data)
    save_json("users", users)

async def is_plus(user_id):
    user = await get_user(user_id)
    return user.get("membership", False)

def daily_reset():
    return datetime.datetime.utcnow().date()

def get_bonus(user_id, amount):
    return int(amount * 1.5) if asyncio.run(is_plus(user_id)) else amount

# Leveling helpers
async def add_xp(user_id, amount):
    user = await get_user(user_id)
    user["xp"] += amount
    # Level up every 100 XP
    if user["xp"] >= user["level"] * 100:
        user["xp"] -= user["level"] * 100
        user["level"] += 1
        await update_user(user_id, user)
        return True
    await update_user(user_id, user)
    return False

# Bot events
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("💾 JSON storage ready")

# ------------------------- ECONOMY COMMANDS -------------------------
@bot.command(aliases=["vebalance"])
async def balance(ctx, member: discord.Member=None):
    member = member or ctx.author
    user = await get_user(member.id)
    embed = discord.Embed(title=f"{member.name}'s Balance", color=discord.Color.green())
    embed.add_field(name="Wallet", value=f"{user['wallet']}$", inline=True)
    embed.add_field(name="Bank", value=f"{user['bank']}$", inline=True)
    embed.add_field(name="Membership", value="VRTEX+" if user.get("membership") else "Normal", inline=False)
    await ctx.send(embed=embed)

@bot.command(aliases=["vedeposit"])
async def deposit(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user["wallet"]:
        await ctx.send("❌ Invalid deposit amount!")
        return
    user["wallet"] -= amount
    user["bank"] += amount
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ Deposited {amount}$ into your bank!")

@bot.command(aliases=["vewithdraw"])
async def withdraw(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user["bank"]:
        await ctx.send("❌ Invalid withdraw amount!")
        return
    user["wallet"] += amount
    user["bank"] -= amount
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ Withdrawn {amount}$ to your wallet!")

@bot.command(aliases=["vetransfer"])
async def transfer(ctx, member: discord.Member, amount: int):
    if member.id == ctx.author.id:
        await ctx.send("❌ You cannot transfer to yourself!")
        return
    sender = await get_user(ctx.author.id)
    receiver = await get_user(member.id)
    if amount <= 0 or amount > sender["wallet"]:
        await ctx.send("❌ Invalid transfer amount!")
        return
    sender["wallet"] -= amount
    receiver["wallet"] += amount
    await update_user(ctx.author.id, sender)
    await update_user(member.id, receiver)
    await ctx.send(f"✅ Transferred {amount}$ to {member.mention}!")

@bot.command(aliases=["veleaderboard"])
async def leaderboard(ctx):
    users = load_json("users")
    top = sorted(users.items(), key=lambda x: x[1]["wallet"] + x[1]["bank"], reverse=True)[:10]
    embed = discord.Embed(title="💰 Top 10 Richest Users", color=discord.Color.gold())
    for i, (uid, data) in enumerate(top, 1):
        member = ctx.guild.get_member(int(uid))
        name = member.name if member else f"User ID {uid}"
        embed.add_field(name=f"{i}. {name}", value=f"Total: {data['wallet']+data['bank']}$", inline=False)
    await ctx.send(embed=embed)

@bot.command(aliases=["veprofile", "profile"])
async def profile(ctx, member: discord.Member=None):
    member = member or ctx.author
    user = await get_user(member.id)
    embed = discord.Embed(title=f"{member.name}'s Profile", color=discord.Color.blue())
    embed.add_field(name="Balance", value=f"{user['wallet'] + user['bank']}$", inline=False)
    embed.add_field(name="Level", value=f"{user['level']} (XP: {user['xp']})", inline=False)
    embed.add_field(name="Membership", value="VRTEX+" if user.get("membership") else "Normal", inline=False)
    embed.add_field(name="Job", value=user["job"] if user["job"] else "Unemployed", inline=False)
    embed.add_field(name="Businesses Owned", value=", ".join(user["businesses"].keys()) if user["businesses"] else "None", inline=False)
    embed.add_field(name="Items", value=", ".join(user["items"].keys()) if user["items"] else "None", inline=False)
    await ctx.send(embed=embed)

# ------------------------- DAILY, DROP, VOTE -------------------------
@bot.command(aliases=["vedaily", "daily"])
async def daily(ctx):
    user = await get_user(ctx.author.id)
    today = daily_reset()
    last_claim = user.get("daily_claimed")
    if last_claim == str(today):
        await ctx.send("❌ You already claimed your daily today! Come back tomorrow.")
        return
    amount = 3000
    if await is_plus(ctx.author.id):
        amount = 4000
    user["wallet"] += amount
    user["daily_claimed"] = str(today)
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You claimed your daily and received **{amount}$**!")

@bot.command(aliases=["vedrop", "drop"])
async def drop(ctx):
    user = await get_user(ctx.author.id)
    now = datetime.datetime.utcnow()
    last_claim = user.get("drop_claimed")
    if last_claim:
        last = datetime.datetime.fromisoformat(last_claim)
        delta = (now - last).total_seconds()
        cooldown = 3600
        if await is_plus(ctx.author.id):
            cooldown = 3600 * 0.8
        if delta < cooldown:
            await ctx.send(f"❌ You can claim drop again in **{int((cooldown-delta)//60)}m {int((cooldown-delta)%60)}s**")
            return
    amount = 1000
    if await is_plus(ctx.author.id):
        amount = 2000
    user["wallet"] += amount
    user["drop_claimed"] = now.isoformat()
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You claimed a drop and received **{amount}$**!")

@bot.command(aliases=["vevote", "vote"])
async def vote(ctx):
    user = await get_user(ctx.author.id)
    amount = 2000
    if await is_plus(ctx.author.id):
        amount = 3000
    user["wallet"] += amount
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ Thanks for voting! You received **{amount}$**!\nVote here: {TOPGG_LINK}")

# ------------------------- VRTEX+ MEMBERSHIP MANAGEMENT -------------------------
@bot.command(aliases=["addplus"])
async def addplus(ctx, member: discord.Member):
    if ctx.author.id not in TEAM_IDS and ctx.author.id != OWNER_ID:
        await ctx.send("❌ Only team members or owner can give VRTEX+ membership.")
        return
    user = await get_user(member.id)
    user["membership"] = True
    await update_user(member.id, user)
    await ctx.send(f"✅ {member.mention} has been granted **VRTEX+** membership!")

@bot.command(aliases=["removeplus"])
async def removeplus(ctx, member: discord.Member):
    if ctx.author.id not in TEAM_IDS and ctx.author.id != OWNER_ID:
        await ctx.send("❌ Only team members or owner can remove VRTEX+ membership.")
        return
    user = await get_user(member.id)
    user["membership"] = False
    await update_user(member.id, user)
    await ctx.send(f"✅ {member.mention} has been removed from **VRTEX+** membership!")

# ------------------------- PREFIX CHANGE (VRTEX+ ONLY) -------------------------
@bot.command(aliases=["veprefix", "prefix"])
async def prefix(ctx, new_prefix):
    if not await is_plus(ctx.author.id):
        await ctx.send("❌ Only VRTEX+ members can change server prefix!")
        return
    servers = load_json("servers")
    servers[str(ctx.guild.id)] = {"prefix": new_prefix}
    save_json("servers", servers)
    await ctx.send(f"✅ Server prefix changed to **{new_prefix}**")

# ------------------------- PROMOTE -------------------------
@bot.command(aliases=["vepromote", "promote"])
async def promote(ctx):
    user = await get_user(ctx.author.id)
    # Promote automatically for now based on balance >= 10000
    if user["wallet"] + user["bank"] >= 10000:
        await ctx.send(f"🎉 Congratulations {ctx.author.mention}, you are promoted!")
    else:
        await ctx.send("❌ You need at least 10000$ to get promoted.")
# ------------------------- JOBS & WORK SYSTEM -------------------------
DEFAULT_JOBS = {
    "Farmer": {"pay": 500, "xp": 20},
    "Miner": {"pay": 700, "xp": 25},
    "Blacksmith": {"pay": 1000, "xp": 40},
    "Merchant": {"pay": 1500, "xp": 60}
}

@bot.command(aliases=["vejobs"])
async def vejobs(ctx):
    embed = discord.Embed(title="💼 Available Jobs", color=discord.Color.purple())
    for job, info in DEFAULT_JOBS.items():
        embed.add_field(name=job, value=f"Pay: {info['pay']}$ | XP: {info['xp']}", inline=False)
    await ctx.send(embed=embed)

@bot.command(aliases=["veapplyjob"])
async def veapplyjob(ctx, *, job_name):
    if job_name not in DEFAULT_JOBS:
        await ctx.send("❌ Job not found!")
        return
    user = await get_user(ctx.author.id)
    user["job"] = job_name
    user["job_streak"] = 0
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You have successfully applied for the **{job_name}** job!")

@bot.command(aliases=["vequitjob"])
async def vequitjob(ctx):
    user = await get_user(ctx.author.id)
    if not user["job"]:
        await ctx.send("❌ You do not have a job currently!")
        return
    job_name = user["job"]
    user["job"] = None
    user["job_streak"] = 0
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You quit your **{job_name}** job.")

@bot.command(aliases=["vework"])
async def vework(ctx):
    user = await get_user(ctx.author.id)
    if not user["job"]:
        await ctx.send("❌ You need a job first! Use `veapplyjob [job name]`")
        return
    job_info = DEFAULT_JOBS[user["job"]]
    pay = job_info["pay"]
    xp = job_info["xp"]
    if await is_plus(ctx.author.id):
        pay = int(pay * 1.25)
        xp = int(xp * 1.25)
    user["wallet"] += pay
    user["job_streak"] += 1
    leveled_up = await add_xp(ctx.author.id, xp)
    await update_user(ctx.author.id, user)
    msg = f"✅ You worked as **{user['job']}** and earned {pay}$ + {xp} XP!"
    if leveled_up:
        msg += f"\n🎉 You leveled up!"
    await ctx.send(msg)

# ------------------------- BUSINESSES -------------------------
DEFAULT_BUSINESSES = {
    "Bakery": {"cost": 5000, "profit": 500, "upkeep": 50, "tier": 1},
    "Mine": {"cost": 10000, "profit": 1200, "upkeep": 150, "tier": 2},
    "Shop": {"cost": 20000, "profit": 2500, "upkeep": 300, "tier": 3},
    "Factory": {"cost": 50000, "profit": 6000, "upkeep": 800, "tier": 4},
    "Tech Lab": {"cost": 100000, "profit": 15000, "upkeep": 2000, "tier": 5}
}

@bot.group(aliases=["vebusiness"], invoke_without_command=True)
async def vebusiness(ctx):
    await ctx.send("❌ Use a subcommand: buy/upgrade/list/info/claim")

@vebusiness.command()
async def list(ctx):
    embed = discord.Embed(title="🏠 Available Businesses", color=discord.Color.orange())
    for biz, info in DEFAULT_BUSINESSES.items():
        embed.add_field(name=biz, value=f"Cost: {info['cost']}$ | Profit: {info['profit']}$ | Tier: {info['tier']}", inline=False)
    await ctx.send(embed=embed)

@vebusiness.command()
async def buy(ctx, *, name):
    if name not in DEFAULT_BUSINESSES:
        await ctx.send("❌ Business not found!")
        return
    user = await get_user(ctx.author.id)
    if name in user["businesses"]:
        await ctx.send("❌ You already own this business!")
        return
    cost = DEFAULT_BUSINESSES[name]["cost"]
    if user["wallet"] < cost:
        await ctx.send("❌ Not enough money!")
        return
    user["wallet"] -= cost
    user["businesses"][name] = {"profit": DEFAULT_BUSINESSES[name]["profit"], "upkeep": DEFAULT_BUSINESSES[name]["upkeep"], "tier": DEFAULT_BUSINESSES[name]["tier"]}
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You bought **{name}**!")

@vebusiness.command()
async def claim(ctx):
    user = await get_user(ctx.author.id)
    total_profit = 0
    for biz, info in user["businesses"].items():
        profit = info["profit"]
        if await is_plus(ctx.author.id) and info["tier"] >= 3:
            profit = int(profit * 1.25)
        total_profit += profit
    user["wallet"] += total_profit
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You claimed **{total_profit}$** from all your businesses!")

@vebusiness.command()
async def info(ctx, *, name):
    if name not in DEFAULT_BUSINESSES:
        await ctx.send("❌ Business not found!")
        return
    info = DEFAULT_BUSINESSES[name]
    embed = discord.Embed(title=f"{name} Info", color=discord.Color.orange())
    embed.add_field(name="Cost", value=f"{info['cost']}$", inline=True)
    embed.add_field(name="Profit", value=f"{info['profit']}$", inline=True)
    embed.add_field(name="Upkeep", value=f"{info['upkeep']}$", inline=True)
    embed.add_field(name="Tier", value=info['tier'], inline=True)
    await ctx.send(embed=embed)

# ------------------------- ITEMS & MARKETPLACE -------------------------
DEFAULT_ITEMS = {
    "Potion": {"price": 500, "effect": "heal"},
    "Elixir": {"price": 1000, "effect": "boost"},
    "Gem": {"price": 5000, "effect": "rare"}
}

@bot.command(aliases=["veinventory"])
async def inventory(ctx):
    user = await get_user(ctx.author.id)
    if not user["items"]:
        await ctx.send("📦 Your inventory is empty!")
        return
    embed = discord.Embed(title=f"{ctx.author.name}'s Inventory", color=discord.Color.teal())
    for item, qty in user["items"].items():
        embed.add_field(name=item, value=f"Quantity: {qty}", inline=False)
    await ctx.send(embed=embed)

@bot.command(aliases=["vebuy"])
async def vebuy(ctx, *, item_name):
    if item_name not in DEFAULT_ITEMS:
        await ctx.send("❌ Item not found!")
        return
    user = await get_user(ctx.author.id)
    price = DEFAULT_ITEMS[item_name]["price"]
    if user["wallet"] < price:
        await ctx.send("❌ Not enough money!")
        return
    user["wallet"] -= price
    user["items"][item_name] = user["items"].get(item_name, 0) + 1
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You bought 1 {item_name} for {price}$!")

@bot.command(aliases=["vesell"])
async def vesell(ctx, *, item_name):
    user = await get_user(ctx.author.id)
    if item_name not in user["items"] or user["items"][item_name] <= 0:
        await ctx.send("❌ You don't own this item!")
        return
    sell_price = DEFAULT_ITEMS.get(item_name, {}).get("price", 0) // 2
    user["wallet"] += sell_price
    user["items"][item_name] -= 1
    if user["items"][item_name] == 0:
        del user["items"][item_name]
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You sold 1 {item_name} for {sell_price}$!")

# ------------------------- ADVENTURE & QUESTS -------------------------
ZONES = ["Forest", "Cave", "River", "Mountain"]

@bot.command(aliases=["veadventure"])
async def adventure(ctx):
    user = await get_user(ctx.author.id)
    zone = random.choice(ZONES)
    coins = random.randint(200, 1000)
    xp = random.randint(10, 50)
    if await is_plus(ctx.author.id):
        coins = int(coins * 1.25)
        xp = int(xp * 1.25)
    user["wallet"] += coins
    leveled_up = await add_xp(ctx.author.id, xp)
    await update_user(ctx.author.id, user)
    msg = f"🏞️ You explored the **{zone}** and found **{coins}$** + {xp} XP!"
    if leveled_up:
        msg += "\n🎉 You leveled up!"
    await ctx.send(msg)
# ------------------------- MINI-GAMES -------------------------
# ------------------------- BETTING MINI-GAMES -------------------------
from discord.ui import View, Button

# ---------- 1. COINFLIP (vebet) ----------
@bot.command()
async def vebet(ctx, amount: str):
    user = await get_user(ctx.author.id)
    if amount.lower() == "all":
        amount = user["wallet"]
    else:
        try:
            amount = int(amount)
        except ValueError:
            return await ctx.send("❌ Invalid bet amount!")
    if amount <= 0 or amount > user["wallet"]:
        return await ctx.send("❌ Not enough cash to bet!")

    user["wallet"] -= amount
    await update_user(ctx.author.id, user)

    await ctx.send("🪙 Flipping the coin... (You are **Heads**)")

    await asyncio.sleep(2)
    result = random.choice(["Heads", "Tails"])
    if result == "Heads":
        winnings = amount * 2
        user["wallet"] += winnings
        await update_user(ctx.author.id, user)
        await ctx.send(f"🎉 It landed on **Heads!** You won **{winnings}$**!")
    else:
        await ctx.send("💀 It landed on **Tails!** You lost your bet.")

# ---------- 2. SLOTS (veslots) ----------
@bot.command()
async def veslots(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user["wallet"]:
        return await ctx.send("❌ Not enough cash to bet!")

    user["wallet"] -= amount
    await update_user(ctx.author.id, user)

    emojis = ["🍒", "🍋", "🍉", "⭐", "💎"]
    slot_result = [random.choice(emojis) for _ in range(3)]
    win = random.random() < 0.45  # 45% win rate

    embed = discord.Embed(title="🎰 Slot Machine", color=discord.Color.gold())
    embed.add_field(name="Result", value=" | ".join(slot_result), inline=False)

    if win and slot_result[0] == slot_result[1] == slot_result[2]:
        winnings = amount * 2
        embed.add_field(name="🎉 You won!", value=f"You earned {winnings}$", inline=False)

        view = View()

        async def claim(interaction):
            if interaction.user != ctx.author:
                return await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            user["wallet"] += winnings
            await update_user(ctx.author.id, user)
            await interaction.response.edit_message(content=f"✅ Claimed **{winnings}$**!", view=None)

        async def double(interaction):
            if interaction.user != ctx.author:
                return await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            win2 = random.random() < 0.45
            if win2:
                winnings2 = amount * 3
                embed2 = discord.Embed(title="🎰 Double Round!", description=f"You doubled successfully! Win: {winnings2}$", color=discord.Color.green())
                view2 = View()

                async def claim2(inter):
                    user["wallet"] += winnings2
                    await update_user(ctx.author.id, user)
                    await inter.response.edit_message(content=f"✅ Claimed **{winnings2}$**!", view=None)

                async def triple(inter):
                    win3 = random.random() < 0.45
                    if win3:
                        winnings3 = amount * 4
                        user["wallet"] += winnings3
                        await update_user(ctx.author.id, user)
                        await inter.response.edit_message(content=f"🏆 Triple win! You earned **{winnings3}$**!", view=None)
                    else:
                        await inter.response.edit_message(content=f"💀 Lost the triple! You lost **{amount * 3}$** total.", view=None)

                view2.add_item(Button(label="Claim", style=discord.ButtonStyle.green))
                view2.add_item(Button(label="Triple", style=discord.ButtonStyle.red))
                view2.children[0].callback = claim2
                view2.children[1].callback = triple

                await interaction.response.edit_message(embed=embed2, view=view2)
            else:
                await interaction.response.edit_message(content=f"💀 You lost the double! Lost **{amount * 2}$** total.", view=None)

        view.add_item(Button(label="Claim", style=discord.ButtonStyle.green))
        view.add_item(Button(label="Double", style=discord.ButtonStyle.red))
        view.children[0].callback = claim
        view.children[1].callback = double

        await ctx.send(embed=embed, view=view)
    else:
        await ctx.send(embed=embed.add_field(name="💀 You lost!", value=f"Lost {amount}$", inline=False))

# ---------- 3. ROCK PAPER SCISSORS (verps) ----------
@bot.command()
async def verps(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user["wallet"]:
        return await ctx.send("❌ Not enough cash to bet!")

    user["wallet"] -= amount
    await update_user(ctx.author.id, user)

    choices = ["🪨 Rock", "📄 Paper", "✂️ Scissors"]

    embed = discord.Embed(title="🪨📄✂️ Rock Paper Scissors", description="Choose your move:", color=discord.Color.blue())
    view = View()

    async def rps_callback(interaction, user_choice):
        if interaction.user != ctx.author:
            return await interaction.response.send_message("❌ Not your game!", ephemeral=True)

        bot_choice = random.choice(choices)
        win_chance = random.random() < 0.33  # 33% chance user wins
        result = "draw"
        if win_chance:
            result = "win"
        else:
            result = "lose"

        if result == "win":
            winnings = amount * 2
            user["wallet"] += winnings
            await update_user(ctx.author.id, user)
            msg = f"🎉 You chose {user_choice}, Bot chose {bot_choice}. You **won {winnings}$!**"
        elif result == "lose":
            msg = f"💀 You chose {user_choice}, Bot chose {bot_choice}. You lost your bet."
        else:
            user["wallet"] += amount  # refund if draw
            await update_user(ctx.author.id, user)
            msg = f"😐 Draw! You get your {amount}$ back."

        await interaction.response.edit_message(content=msg, embed=None, view=None)

    for choice in choices:
        btn = Button(label=choice, style=discord.ButtonStyle.primary)
        btn.callback = lambda inter, c=choice: asyncio.create_task(rps_callback(inter, c))
        view.add_item(btn)

    await ctx.send(embed=embed, view=view)

# ---------- 4. EMOJI RACE (verace) ----------
@bot.command()
async def verace(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user["wallet"]:
        return await ctx.send("❌ Not enough cash to bet!")

    user["wallet"] -= amount
    await update_user(ctx.author.id, user)

    emojis = ["🐎", "🐢", "🐇"]
    player_pick = random.choice(emojis)
    bot_pick = random.choice([e for e in emojis if e != player_pick])

    await ctx.send(f"🏁 You picked {player_pick}, racing against {bot_pick}...")

    await asyncio.sleep(3)
    win = random.random() < 0.33  # 33% chance to win

    if win:
        winnings = amount * 3
        user["wallet"] += winnings
        await update_user(ctx.author.id, user)
        await ctx.send(f"🎉 {player_pick} won the race! You earned **{winnings}$**!")
    else:
        await ctx.send(f"💀 {bot_pick} won! You lost your bet.")

# ---------- 5. BLACKJACK (veblackjack) ----------
@bot.command()
async def veblackjack(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user["wallet"]:
        return await ctx.send("❌ Not enough cash to bet!")

    user["wallet"] -= amount
    await update_user(ctx.author.id, user)

    win = random.random() < 0.44  # 44% win rate
    view = View()

    async def end_game(interaction, action):
        if interaction.user != ctx.author:
            return await interaction.response.send_message("❌ Not your game!", ephemeral=True)

        if win:
            winnings = amount * 2
            user["wallet"] += winnings
            await update_user(ctx.author.id, user)
            await interaction.response.edit_message(content=f"🃏 You chose **{action}** and **won {winnings}$!** 🎉", view=None)
        else:
            await interaction.response.edit_message(content=f"💀 You chose **{action}** and lost your bet!", view=None)

    for label in ["Hit", "Stand", "Double Down", "Split"]:
        btn = Button(label=label, style=discord.ButtonStyle.primary)
        btn.callback = lambda inter, l=label: asyncio.create_task(end_game(inter, l))
        view.add_item(btn)

    await ctx.send("🃏 Blackjack! Choose your move:", view=view)

# ------------------------- SERVER SETTINGS -------------------------
@bot.group(aliases=["vesettings"], invoke_without_command=True)
async def vsettings(ctx):
    await ctx.send("❌ Use a subcommand: currency/tax/toggle/prefix")

@vsettings.command()
async def currency(ctx, name):
    servers = load_json("servers")
    servers[str(ctx.guild.id)] = servers.get(str(ctx.guild.id), {})
    servers[str(ctx.guild.id)]["currency"] = name
    save_json("servers", servers)
    await ctx.send(f"✅ Server currency set to **{name}**")

@vsettings.command()
async def tax(ctx, rate: int):
    servers = load_json("servers")
    servers[str(ctx.guild.id)] = servers.get(str(ctx.guild.id), {})
    servers[str(ctx.guild.id)]["tax"] = rate
    save_json("servers", servers)
    await ctx.send(f"✅ Server tax rate set to **{rate}%**")

@vsettings.command()
async def toggle(ctx, command_name):
    servers = load_json("servers")
    servers[str(ctx.guild.id)] = servers.get(str(ctx.guild.id), {})
    commands_disabled = servers[str(ctx.guild.id)].get("disabled_commands", [])
    if command_name in commands_disabled:
        commands_disabled.remove(command_name)
        await ctx.send(f"✅ Command **{command_name}** enabled")
    else:
        commands_disabled.append(command_name)
        await ctx.send(f"✅ Command **{command_name}** disabled")
    servers[str(ctx.guild.id)]["disabled_commands"] = commands_disabled
    save_json("servers", servers)

# ------------------------- LEVEL & RANK -------------------------
@bot.command(aliases=["velevel"])
async def velevel(ctx):
    user = await get_user(ctx.author.id)
    await ctx.send(f"🎚️ Level: {user['level']} | XP: {user['xp']}")

@bot.command(aliases=["verank"])
async def verank(ctx):
    users = load_json("users")
    ranking = sorted(users.items(), key=lambda x: x[1]["xp"] + x[1]["level"]*100, reverse=True)
    for i, (uid, data) in enumerate(ranking, 1):
        if int(uid) == ctx.author.id:
            await ctx.send(f"🏆 You are rank #{i}")
            return
    await ctx.send("❌ You are not ranked yet.")

# ------------------------- GENERAL INFO -------------------------
@bot.command(aliases=["vehelp"])
async def vehelp(ctx):
    commands_list = """
💠 **VRTEX ECONOMY COMMANDS**
- vebalance, vedeposit, vewithdraw, vetransfer, veleaderboard, veprofile
- vedaily, vedrop, vevote
- vework, veapplyjob, vequitjob, vejobs, vepromote
- vebusiness buy/list/info/claim
- veinventory, vebuy, vesell
- veadventure, vequests, veachievements
- vecardclash, vetrivia, vememorymatch
- vesettings currency/tax/toggle/prefix
- velevel, verank, vehelp, veabout
"""
    await ctx.send(commands_list)

@bot.command(aliases=["veabout"])
async def veabout(ctx):
    await ctx.send("💠 **VRTEX ECONOMY** | Created by VRTEX Team\nAll features: Economy, Jobs, Business, Adventure, Mini-Games, VRTEX+ Premium!")

# ------------------------- RUN BOT -------------------------
keep_alive()

bot.run(TOKEN)
