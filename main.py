# main.py
from web_server import keep_alive

# start keep-alive server
keep_alive()

import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
import os
import json
import datetime
import random
import asyncio
from typing import Optional

# -----------------------------
# Configuration / Environment
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
TEAM_IDS = [int(x) for x in os.getenv("TEAM_IDS", "").split(",") if x.strip().isdigit()]
TOPGG_LINK = os.getenv("TOPGG_LINK", "")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=commands.when_mentioned_or("ve"), intents=intents, case_insensitive=True)

# -----------------------------
# Files and storage helpers
# -----------------------------
FILES = {
    "users": "users.json",
    "servers": "servers.json",
    "businesses": "businesses.json",
    "items": "items.json",
    "jobs": "jobs.json",
    "market": "market.json",
    "quests": "quests.json",
    "economy": "economy.json"
}

# ensure files exist
for fname in FILES.values():
    if not os.path.exists(fname):
        with open(fname, "w") as f:
            json.dump({}, f)

def load_json(file_key: str) -> dict:
    path = FILES[file_key]
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # if corrupt or missing, recreate
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}

def save_json(file_key: str, data: dict):
    path = FILES[file_key]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# User helpers
# -----------------------------
async def get_user(user_id: int) -> dict:
    users = load_json("users")
    sid = str(user_id)
    if sid not in users:
        users[sid] = {
            "wallet": 0,
            "bank": 0,
            "daily_claimed": None,
            "work_claims": {},   # per-guild last work timestamp ISO
            "membership": False,
            "xp": 0,
            "level": 1,
            "job": None,
            "job_streak": 0,
            "items": {},
            "businesses": {}
        }
        save_json("users", users)
    return users[sid]

async def update_user(user_id: int, data: dict):
    users = load_json("users")
    sid = str(user_id)
    if sid not in users:
        users[sid] = {}
    users[sid].update(data)
    save_json("users", users)

async def is_plus(user_id: int) -> bool:
    u = await get_user(user_id)
    return u.get("membership", False)

# -----------------------------
# Economy helpers
# -----------------------------
def get_guild_economy(guild_id: int) -> dict:
    econ = load_json("economy")
    gid = str(guild_id)
    if gid not in econ:
        # defaults
        econ[gid] = {
            "currency_name": "Coins",
            "currency_symbol": "$",
            "starting_balance": 0,
            "tax_rate": 0
        }
        save_json("economy", econ)
    return econ[gid]

def set_guild_economy(guild_id: int, data: dict):
    econ = load_json("economy")
    econ[str(guild_id)] = econ.get(str(guild_id), {})
    econ[str(guild_id)].update(data)
    save_json("economy", econ)

# -----------------------------
# Utility
# -----------------------------
def utc_now():
    return datetime.datetime.utcnow()

def readable_time_delta(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

# -----------------------------
# Leveling helper
# -----------------------------
async def add_xp(user_id: int, amount: int):
    user = await get_user(user_id)
    user['xp'] = user.get('xp', 0) + amount
    leveled = False
    if user['xp'] >= user.get('level', 1) * 100:
        user['xp'] -= user.get('level', 1) * 100
        user['level'] = user.get('level', 1) + 1
        leveled = True
    await update_user(user_id, user)
    return leveled

# -----------------------------
# On ready
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    print("💾 JSON storage ready")
    # ensure economy file entries exist for guilds bot is in
    econ = load_json("economy")
    for g in bot.guilds:
        if str(g.id) not in econ:
            econ[str(g.id)] = {
                "currency_name": "Coins",
                "currency_symbol": "$",
                "starting_balance": 0,
                "tax_rate": 0
            }
    save_json("economy", econ)

# -----------------------------
# On guild join -> send setup message
# -----------------------------
@bot.event
async def on_guild_join(guild: discord.Guild):
    # find the first channel where @everyone can view and send messages
    target_channel = None
    for ch in guild.text_channels:
        perms = ch.permissions_for(guild.default_role)
        if perms.view_channel and perms.send_messages:
            target_channel = ch
            break
    if not target_channel:
        # nothing to do
        return
    embed = discord.Embed(
        title="💠 Thanks for inviting VRTEX Economy!",
        description="Type `veletsgo` or press **Start Setup** to configure the economy for this server.",
        color=discord.Color.blurple()
    )
    view = View()
    btn = Button(label="Start Setup (veletsgo)", style=discord.ButtonStyle.green)
    async def start_setup(interaction: discord.Interaction):
        if interaction.user.guild_permissions.manage_guild or interaction.user.id == OWNER_ID or interaction.user.id in TEAM_IDS:
            await interaction.response.defer()
            await launch_setup(interaction, guild, starter=interaction.user)
        else:
            await interaction.response.send_message("You need Manage Server (or be owner / team) to run setup.", ephemeral=True)
    btn.callback = start_setup
    view.add_item(btn)
    await target_channel.send(embed=embed, view=view)

# -----------------------------
# Setup flow helpers (modals + paged buttons)
# -----------------------------
class CurrencyModal(Modal, title="Currency setup"):
    currency_name = TextInput(label="Currency name", placeholder="Coins, Gold, VRTEX", required=True, max_length=40)
    currency_symbol = TextInput(label="Currency symbol (optional)", placeholder="$ or V", required=False, max_length=6)

    def __init__(self, guild: discord.Guild, starter: discord.Member):
        super().__init__()
        self.guild = guild
        self.starter = starter

    async def on_submit(self, interaction: discord.Interaction):
        # save to economy
        set_guild_economy(self.guild.id, {
            "currency_name": self.currency_name.value.strip(),
            "currency_symbol": self.currency_symbol.value.strip() or ""
        })
        await interaction.response.send_message(f"✅ Currency set to **{self.currency_name.value.strip()}** `{self.currency_symbol.value.strip()}`. You can change this later with `vesettings`.", ephemeral=True)

async def launch_setup(interaction_or_ctx, guild: discord.Guild, starter: discord.Member):
    # send a paged setup view starting with an intro message
    # create a persistent message for navigation (ephemeral if interaction)
    channel = None
    if isinstance(interaction_or_ctx, discord.Interaction):
        channel = interaction_or_ctx.channel
    else:
        channel = interaction_or_ctx

    page = 1
    # create a view with Next / Back / Finish
    class SetupView(View):
        def __init__(self, *, timeout=900):
            super().__init__(timeout=timeout)
            self.page = 1

        async def send_page(self, interaction_or_ctx, who_initiated):
            if isinstance(interaction_or_ctx, discord.Interaction):
                respond = interaction_or_ctx.response
            # build page content
            econ = get_guild_economy(guild.id)
            if self.page == 1:
                embed = discord.Embed(title="SETUP VRTEX ECONOMY FOR YOUR SERVER", color=discord.Color.blurple())
                embed.add_field(name="Step 1 — Currency", value=f"Currency name: **{econ.get('currency_name', 'Coins')}**\nSymbol: **{econ.get('currency_symbol', '$')}**\n\nClick **Edit** to set currency name & symbol (modal).", inline=False)
                embed.set_footer(text="These settings can be changed later with the command `vesettings`.")
                if isinstance(interaction_or_ctx, discord.Interaction):
                    await interaction_or_ctx.response.edit_message(embed=embed, view=self)
                else:
                    await interaction_or_ctx.send(embed=embed, view=self)
            elif self.page == 2:
                embed = discord.Embed(title="Step 2 — Economy Options", color=discord.Color.blurple())
                embed.add_field(name="Starting Balance", value=f"{econ.get('starting_balance', 0)} {econ.get('currency_symbol','')}", inline=False)
                embed.add_field(name="Work Reward", value="Users will get 1000 per hour (can be changed later).", inline=False)
                if isinstance(interaction_or_ctx, discord.Interaction):
                    await interaction_or_ctx.response.edit_message(embed=embed, view=self)
                else:
                    await interaction_or_ctx.send(embed=embed, view=self)
            elif self.page == 3:
                embed = discord.Embed(title="Step 3 — Confirm", color=discord.Color.green())
                embed.add_field(name="Summary", value=f"Currency: **{econ.get('currency_name')} {econ.get('currency_symbol','')}**\nStarting balance: **{econ.get('starting_balance',0)}**\nWork: **1000 per hour**", inline=False)
                if isinstance(interaction_or_ctx, discord.Interaction):
                    await interaction_or_ctx.response.edit_message(embed=embed, view=self)
                else:
                    await interaction_or_ctx.send(embed=embed, view=self)

        @discord.ui.button(label="<< Back", style=discord.ButtonStyle.secondary, row=0)
        async def back(self, button: Button, interaction: discord.Interaction):
            if interaction.user != starter and not (interaction.user.guild_permissions.manage_guild or interaction.user.id in TEAM_IDS or interaction.user.id == OWNER_ID):
                return await interaction.response.send_message("You are not allowed to navigate this setup.", ephemeral=True)
            if self.page > 1:
                self.page -= 1
            await self.send_page(interaction, starter)

        @discord.ui.button(label="Edit Currency", style=discord.ButtonStyle.gray, row=0)
        async def edit_currency(self, button: Button, interaction: discord.Interaction):
            if interaction.user != starter and not (interaction.user.guild_permissions.manage_guild or interaction.user.id in TEAM_IDS or interaction.user.id == OWNER_ID):
                return await interaction.response.send_message("You are not allowed to edit.", ephemeral=True)
            modal = CurrencyModal(guild, starter)
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Next >>", style=discord.ButtonStyle.primary, row=0)
        async def nxt(self, button: Button, interaction: discord.Interaction):
            if interaction.user != starter and not (interaction.user.guild_permissions.manage_guild or interaction.user.id in TEAM_IDS or interaction.user.id == OWNER_ID):
                return await interaction.response.send_message("You are not allowed to navigate this setup.", ephemeral=True)
            if self.page < 3:
                self.page += 1
                await self.send_page(interaction, starter)
            else:
                # finish
                await interaction.response.send_message("✅ Setup complete! You can edit settings later with `vesettings`. Type `vehelp` to see all commands.", ephemeral=True)
                self.stop()

    # send initial message
    view = SetupView()
    embed = discord.Embed(title="SETUP VRTEX ECONOMY FOR YOUR SERVER", description="Press Next to begin or Edit Currency to set currency now.", color=discord.Color.blurple())
    # If called from an interaction, reply; else send
    if isinstance(interaction_or_ctx, discord.Interaction):
        await interaction_or_ctx.followup.send(embed=embed, view=view)
    else:
        await interaction_or_ctx.send(embed=embed, view=view)

# wrapper command to start setup manually
@bot.command()
async def veletsgo(ctx):
    if not (ctx.author.guild_permissions.manage_guild or ctx.author.id in TEAM_IDS or ctx.author.id == OWNER_ID):
        await ctx.send("You need Manage Server permission (or be owner/team) to run setup.")
        return
    await launch_setup(ctx, ctx.guild, starter=ctx.author)

# -----------------------------
# Economy / Core commands
# -----------------------------
# multiple names requested: implement vebal (main) and extra commands that just forward to same handler
async def send_balance_embed(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    user = await get_user(member.id)
    guild_econ = get_guild_economy(ctx.guild.id) if ctx.guild else {"currency_name":"Coins","currency_symbol":"$"}
    name = guild_econ.get("currency_name", "Coins")
    sym = guild_econ.get("currency_symbol", "")
    wallet = user.get("wallet", 0)
    bank = user.get("bank", 0)
    embed = discord.Embed(title=f"{member.display_name}'s Balance", color=discord.Color.green())
    embed.add_field(name=f"{name} (Wallet)", value=f"{wallet} {sym}", inline=True)
    embed.add_field(name=f"{name} (Bank)", value=f"{bank} {sym}", inline=True)
    embed.add_field(name="Membership", value="VRTEX+" if user.get("membership") else "Normal", inline=False)
    embed.set_footer(text="Use veprofile for more info.")
    await ctx.send(embed=embed)

@bot.command()
async def vebal(ctx, member: discord.Member=None):
    await send_balance_embed(ctx, member)

# extra variants requested (no aliases, separate commands that call same logic)
@bot.command()
async def vewallet(ctx, member: discord.Member=None):
    await send_balance_embed(ctx, member)

@bot.command()
async def vepocket(ctx, member: discord.Member=None):
    await send_balance_embed(ctx, member)

@bot.command()
async def vebank(ctx, member: discord.Member=None):
    await send_balance_embed(ctx, member)

@bot.command()
async def vecash(ctx, member: discord.Member=None):
    await send_balance_embed(ctx, member)

@bot.command()
async def vedeposit(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user.get("wallet", 0):
        return await ctx.send("❌ Invalid deposit amount or insufficient wallet funds.")
    user['wallet'] -= amount
    user['bank'] = user.get('bank', 0) + amount
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ Deposited {amount}{get_guild_economy(ctx.guild.id).get('currency_symbol','')} into your bank.")

@bot.command()
async def vewithdraw(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user.get("bank", 0):
        return await ctx.send("❌ Invalid withdraw amount or insufficient bank funds.")
    user['bank'] -= amount
    user['wallet'] = user.get('wallet', 0) + amount
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ Withdrawn {amount}{get_guild_economy(ctx.guild.id).get('currency_symbol','')} to your wallet.")

@bot.command()
async def vetransfer(ctx, member: discord.Member, amount: int):
    if member.id == ctx.author.id:
        return await ctx.send("❌ You cannot transfer to yourself.")
    sender = await get_user(ctx.author.id)
    receiver = await get_user(member.id)
    if amount <= 0 or amount > sender.get("wallet", 0):
        return await ctx.send("❌ Invalid transfer amount or insufficient balance.")
    sender['wallet'] -= amount
    receiver['wallet'] = receiver.get('wallet', 0) + amount
    await update_user(ctx.author.id, sender)
    await update_user(member.id, receiver)
    await ctx.send(f"✅ Transferred {amount}{get_guild_economy(ctx.guild.id).get('currency_symbol','')} to {member.mention}!")

@bot.command()
async def veleaderboard(ctx):
    users = load_json("users")
    # compute total per user
    ranking = []
    for uid, data in users.items():
        total = data.get('wallet', 0) + data.get('bank', 0)
        ranking.append((uid, total))
    ranking.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="💰 Top Richest Users", color=discord.Color.gold())
    guild = ctx.guild
    count = 0
    for uid, total in ranking:
        if count >= 10:
            break
        # only show users that exist in this guild (optional): we will show all — but try to resolve member
        try:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
        except Exception:
            name = f"User {uid}"
        embed.add_field(name=name, value=f"Total: {total}{get_guild_economy(guild.id).get('currency_symbol','')}", inline=False)
        count += 1
    await ctx.send(embed=embed)

@bot.command()
async def veprofile(ctx, member: discord.Member=None):
    member = member or ctx.author
    user = await get_user(member.id)
    econ = get_guild_economy(ctx.guild.id)
    embed = discord.Embed(title=f"{member.display_name}'s Profile", color=discord.Color.blue())
    embed.add_field(name="Balance", value=f"{user.get('wallet',0)+user.get('bank',0)}{econ.get('currency_symbol','')}", inline=False)
    embed.add_field(name="Level & XP", value=f"Level {user.get('level',1)} (XP: {user.get('xp',0)})", inline=False)
    embed.add_field(name="Job", value=user.get('job') or "Unemployed", inline=False)
    embed.add_field(name="Businesses", value=", ".join(user.get('businesses',{}).keys()) or "None", inline=False)
    await ctx.send(embed=embed)

# -----------------------------
# Work: user can use once per hour, gives 1000
# -----------------------------
@bot.command()
async def vework(ctx):
    user = await get_user(ctx.author.id)
    guild_id = str(ctx.guild.id)
    last_claims = user.get("work_claims", {})
    now = utc_now()
    last_iso = last_claims.get(guild_id)
    cooldown = 3600  # 1 hour
    if last_iso:
        try:
            last_dt = datetime.datetime.fromisoformat(last_iso)
            delta = (now - last_dt).total_seconds()
            if delta < cooldown:
                await ctx.send(f"❌ You can work again in **{readable_time_delta(cooldown - delta)}**")
                return
        except Exception:
            # if parsing fails, allow
            pass
    reward = 1000
    # plus members get bonus
    if await is_plus(ctx.author.id):
        reward = int(reward * 1.25)
    user['wallet'] = user.get('wallet', 0) + reward
    last_claims[guild_id] = now.isoformat()
    user['work_claims'] = last_claims
    await update_user(ctx.author.id, user)
    leveled = await add_xp(ctx.author.id, 20)
    msg = f"✅ You worked and earned **{reward}{get_guild_economy(ctx.guild.id).get('currency_symbol','')}**!"
    if leveled:
        msg += "\n🎉 You leveled up!"
    await ctx.send(msg)

# -----------------------------
# Coinflip: vecf (amount)
# -----------------------------
@bot.command()
async def vecf(ctx, amount: str):
    user = await get_user(ctx.author.id)
    if amount.lower() == 'all':
        amt = user.get('wallet', 0)
    else:
        try:
            amt = int(amount)
        except ValueError:
            return await ctx.send("❌ Invalid amount. Provide a number or 'all'.")
    if amt <= 0 or amt > user.get('wallet', 0):
        return await ctx.send("❌ Insufficient funds.")
    user['wallet'] -= amt
    await update_user(ctx.author.id, user)
    await ctx.send("🪙 Flipping the coin... You're **Heads**")
    await asyncio.sleep(1.5)
    res = random.choice(["Heads", "Tails"])
    if res == "Heads":
        winnings = amt * 2
        user['wallet'] = user.get('wallet', 0) + winnings
        await update_user(ctx.author.id, user)
        await ctx.send(f"🎉 It landed on **Heads** — you won **{winnings}{get_guild_economy(ctx.guild.id).get('currency_symbol','')}**!")
    else:
        await ctx.send(f"💀 It landed on **Tails** — you lost **{amt}{get_guild_economy(ctx.guild.id).get('currency_symbol','')}**.")

# -----------------------------
# Simple mini-games (kept but minimal)
# -----------------------------
@bot.command()
async def veslots(ctx, amount: int):
    user = await get_user(ctx.author.id)
    if amount <= 0 or amount > user.get('wallet', 0):
        return await ctx.send("❌ Invalid amount.")
    user['wallet'] -= amount
    await update_user(ctx.author.id, user)
    emojis = ["🍒", "🍋", "🍉", "⭐", "💎"]
    res = [random.choice(emojis) for _ in range(3)]
    embed = discord.Embed(title="🎰 Slots", description=" | ".join(res), color=discord.Color.gold())
    if res[0] == res[1] == res[2]:
        winnings = amount * 2
        user['wallet'] += winnings
        await update_user(ctx.author.id, user)
        embed.add_field(name="🎉 You won!", value=f"You earned {winnings}{get_guild_economy(ctx.guild.id).get('currency_symbol','')}")
    else:
        embed.add_field(name="💀 You lost", value=f"Lost {amount}{get_guild_economy(ctx.guild.id).get('currency_symbol','')}")
    await ctx.send(embed=embed)

# -----------------------------
# vebusiness simplified group (command names intentionally explicit)
# -----------------------------
DEFAULT_BUSINESSES = {
    "Bakery": {"cost": 5000, "profit": 500, "upkeep": 50, "tier": 1},
    "Mine": {"cost": 10000, "profit": 1200, "upkeep": 150, "tier": 2},
    "Shop": {"cost": 20000, "profit": 2500, "upkeep": 300, "tier": 3},
}

@bot.group()
async def vebusiness(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send("Usage: vebusiness list | buy <name> | claim | info <name>")

@vebusiness.command()
async def list(ctx):
    embed = discord.Embed(title="🏠 Available Businesses", color=discord.Color.orange())
    for name, info in DEFAULT_BUSINESSES.items():
        embed.add_field(name=name, value=f"Cost: {info['cost']}{get_guild_economy(ctx.guild.id).get('currency_symbol','')} | Profit: {info['profit']}", inline=False)
    await ctx.send(embed=embed)

@vebusiness.command()
async def buy(ctx, *, name: str):
    if name not in DEFAULT_BUSINESSES:
        return await ctx.send("❌ Business not found.")
    user = await get_user(ctx.author.id)
    if name in user.get('businesses', {}):
        return await ctx.send("❌ You already own this business.")
    cost = DEFAULT_BUSINESSES[name]['cost']
    if user.get('wallet', 0) < cost:
        return await ctx.send("❌ Not enough money.")
    user['wallet'] -= cost
    user.setdefault('businesses', {})[name] = DEFAULT_BUSINESSES[name]
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ You bought **{name}**!")

@vebusiness.command()
async def claim(ctx):
    user = await get_user(ctx.author.id)
    total = 0
    for b, info in user.get('businesses', {}).items():
        total += info.get('profit', 0)
    user['wallet'] = user.get('wallet', 0) + total
    await update_user(ctx.author.id, user)
    await ctx.send(f"✅ Claimed {total}{get_guild_economy(ctx.guild.id).get('currency_symbol','')} from your businesses.")

@vebusiness.command()
async def info(ctx, *, name: str):
    if name not in DEFAULT_BUSINESSES:
        return await ctx.send("❌ Business not found.")
    info = DEFAULT_BUSINESSES[name]
    embed = discord.Embed(title=f"{name} Info", color=discord.Color.orange())
    embed.add_field(name="Cost", value=str(info['cost']), inline=True)
    embed.add_field(name="Profit", value=str(info['profit']), inline=True)
    embed.add_field(name="Tier", value=str(info['tier']), inline=True)
    await ctx.send(embed=embed)

# -----------------------------
# vesettings interactive (buttons -> categories -> dropdown -> modals)
# -----------------------------
@bot.command()
async def vesettings(ctx):
    if not (ctx.author.guild_permissions.manage_guild or ctx.author.id in TEAM_IDS or ctx.author.id == OWNER_ID):
        return await ctx.send("You need Manage Server permission (or be owner/team) to use vesettings.")
    econ = get_guild_economy(ctx.guild.id)
    embed = discord.Embed(title="⚙️ VRTEX Settings", description="Choose a category below to configure.", color=discord.Color.blurple())
    embed.add_field(name="Current", value=f"Currency: **{econ.get('currency_name')} {econ.get('currency_symbol','')}**\nStarting balance: **{econ.get('starting_balance',0)}**\nTax: **{econ.get('tax_rate',0)}%**", inline=False)

    class SettingsView(View):
        def __init__(self):
            super().__init__(timeout=300)

        @discord.ui.button(label="Economy", style=discord.ButtonStyle.primary)
        async def economy_btn(self, button: Button, interaction: discord.Interaction):
            await interaction.response.defer()
            await show_economy_options(interaction, ctx.guild)

        @discord.ui.button(label="Commands toggle", style=discord.ButtonStyle.secondary)
        async def toggle_btn(self, button: Button, interaction: discord.Interaction):
            await interaction.response.defer()
            await show_toggle_options(interaction, ctx.guild)

        @discord.ui.button(label="Prefix", style=discord.ButtonStyle.gray)
        async def prefix_btn(self, button: Button, interaction: discord.Interaction):
            await interaction.response.send_message("To change prefix use `veprefix <newprefix>` (only VRTEX+ members can do this).", ephemeral=True)

    view = SettingsView()
    await ctx.send(embed=embed, view=view)

async def show_economy_options(interaction: discord.Interaction, guild: discord.Guild):
    econ = get_guild_economy(guild.id)
    options = [
        discord.SelectOption(label="Set Currency Name & Symbol", value="currency"),
        discord.SelectOption(label="Set Starting Balance", value="startbal"),
        discord.SelectOption(label="Set Tax Rate", value="tax"),
    ]
    select = Select(placeholder="Choose economy setting...", options=options, min_values=1, max_values=1)

    async def sel_callback(inter: discord.Interaction):
        choice = select.values[0]
        if choice == "currency":
            modal = CurrencyModal(guild, inter.user)
            await inter.response.send_modal(modal)
        elif choice == "startbal":
            # ask via modal
            class StartBalModal(Modal, title="Set Starting Balance"):
                amount = TextInput(label="Starting balance (integer)", placeholder="e.g. 100", required=True, max_length=12)
                def __init__(self, guild, user):
                    super().__init__()
                    self.guild = guild
                    self.user = user
                async def on_submit(self, inner_inter: discord.Interaction):
                    try:
                        val = int(self.amount.value.strip())
                        set_guild_economy(self.guild.id, {"starting_balance": val})
                        await inner_inter.response.send_message(f"✅ Starting balance set to {val}.", ephemeral=True)
                    except Exception:
                        await inner_inter.response.send_message("❌ Invalid number.", ephemeral=True)
            await inter.response.send_modal(StartBalModal(guild, inter.user))
        elif choice == "tax":
            class TaxModal(Modal, title="Set Tax Rate"):
                rate = TextInput(label="Tax rate (percentage)", placeholder="e.g. 5", required=True, max_length=6)
                def __init__(self, guild, user):
                    super().__init__()
                    self.guild = guild
                    self.user = user
                async def on_submit(self, inner_inter: discord.Interaction):
                    try:
                        r = int(self.rate.value.strip())
                        set_guild_economy(self.guild.id, {"tax_rate": r})
                        await inner_inter.response.send_message(f"✅ Tax rate set to {r}%.", ephemeral=True)
                    except Exception:
                        await inner_inter.response.send_message("❌ Invalid rate.", ephemeral=True)
            await inter.response.send_modal(TaxModal(guild, inter.user))

    select.callback = sel_callback
    view = View()
    view.add_item(select)
    await interaction.followup.send("Choose an economy setting to edit:", view=view, ephemeral=True)

async def show_toggle_options(interaction: discord.Interaction, guild: discord.Guild):
    # show a list of commands which can be toggled (simple demo)
    servers = load_json("servers")
    servers[str(guild.id)] = servers.get(str(guild.id), {})
    disabled = servers[str(guild.id)].get("disabled_commands", [])
    COMMANDS = ["vework","vecf","veslots","vebusiness","vehelp","vebalance"]
    options = []
    for c in COMMANDS:
        label = f"{c} {'(disabled)' if c in disabled else '(enabled)'}"
        options.append(discord.SelectOption(label=label, value=c))
    select = Select(placeholder="Toggle command (select to toggle)", options=options, min_values=1, max_values=1)
    async def sel_callback(inter: discord.Interaction):
        cmd = select.values[0]
        if cmd in disabled:
            disabled.remove(cmd)
            await inter.response.send_message(f"✅ Enabled `{cmd}`", ephemeral=True)
        else:
            disabled.append(cmd)
            await inter.response.send_message(f"✅ Disabled `{cmd}`", ephemeral=True)
        servers[str(guild.id)]["disabled_commands"] = disabled
        save_json("servers", servers)
    select.callback = sel_callback
    view = View()
    view.add_item(select)
    await interaction.followup.send("Choose a command to toggle:", view=view, ephemeral=True)

# -----------------------------
# vehelp interactive
# -----------------------------
@bot.command()
async def vehelp(ctx):
    embed = discord.Embed(title="💠 VRTEX ECONOMY — Help", description="Choose a category to view commands.", color=discord.Color.blurple())
    embed.add_field(name="Categories", value="Economy • Games • Businesses • Server • Info", inline=False)
    view = View()

    async def send_economy(interaction: discord.Interaction):
        econ = get_guild_economy(ctx.guild.id)
        sym = econ.get('currency_symbol','')
        e = discord.Embed(title="Economy Commands", color=discord.Color.green())
        e.add_field(name="Balance", value="`vebal` `vewallet` `vepocket` `vebank` `vecash` — show balances", inline=False)
        e.add_field(name="Deposit / Withdraw", value="`vedeposit <amount>` | `vewithdraw <amount>`", inline=False)
        e.add_field(name="Transfer", value="`vetransfer @user <amount>`", inline=False)
        e.add_field(name="Work", value=f"`vework` — earn **1000{sym}** (once per hour)", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    async def send_games(interaction: discord.Interaction):
        e = discord.Embed(title="Games / Mini-Games", color=discord.Color.gold())
        e.add_field(name="Coinflip", value="`vecf <amount|'all'>` — coinflip", inline=False)
        e.add_field(name="Slots", value="`veslots <amount>`", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    async def send_business(interaction: discord.Interaction):
        e = discord.Embed(title="Business Commands", color=discord.Color.orange())
        e.add_field(name="Business group", value="`vebusiness list` | `vebusiness buy <name>` | `vebusiness claim` | `vebusiness info <name>`", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    async def send_server(interaction: discord.Interaction):
        e = discord.Embed(title="Server & Settings", color=discord.Color.blurple())
        e.add_field(name="Setup & Settings", value="`veletsgo` — start setup | `vesettings` — interactive settings (Manage Server only)", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    async def send_info(interaction: discord.Interaction):
        e = discord.Embed(title="Info & Misc", color=discord.Color.blue())
        e.add_field(name="Profile & Leaderboard", value="`veprofile` | `veleaderboard`", inline=False)
        e.add_field(name="Help", value="You're here! `vehelp`", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    b_econ = Button(label="Economy", style=discord.ButtonStyle.primary)
    b_games = Button(label="Games", style=discord.ButtonStyle.secondary)
    b_biz = Button(label="Businesses", style=discord.ButtonStyle.success)
    b_server = Button(label="Server", style=discord.ButtonStyle.gray)
    b_info = Button(label="Info", style=discord.ButtonStyle.blurple)

    b_econ.callback = lambda inter: asyncio.create_task(send_economy(inter))
    b_games.callback = lambda inter: asyncio.create_task(send_games(inter))
    b_biz.callback = lambda inter: asyncio.create_task(send_business(inter))
    b_server.callback = lambda inter: asyncio.create_task(send_server(inter))
    b_info.callback = lambda inter: asyncio.create_task(send_info(inter))

    view.add_item(b_econ)
    view.add_item(b_games)
    view.add_item(b_biz)
    view.add_item(b_server)
    view.add_item(b_info)

    await ctx.send(embed=embed, view=view)

# -----------------------------
# small safety: prevent disabled commands (simple check)
# -----------------------------
@bot.check
async def global_command_block(ctx):
    servers = load_json("servers")
    disabled = servers.get(str(ctx.guild.id), {}).get("disabled_commands", []) if ctx.guild else []
    if ctx.command and ctx.command.name in disabled:
        await ctx.send("That command is currently disabled on this server.")
        return False
    return True

# -----------------------------
# run bot
# -----------------------------
if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not set.")
    else:
        bot.run(TOKEN)
