# main.py — VRTEX Economy (slash commands + optional classic prefix for VRTEX+)
"""
Features implemented:
- All core actions exposed as slash commands (default for every server).
- Optional classic text-prefix commands available only for VRTEX+ (premium) servers.
- Premium purchase flow (owner/admin will need to wire real payment):
    * An owner-only helper command `/premium grant <user_id> <months>` simulates marking payment complete and generates a one-time key (OTP) sent via DM to purchaser.
    * Purchaser uses `/premium activate <key>` inside the server to activate premium for that guild (requires Manage Guild permission).
- When premium is active for a guild, `/settings` adds a "Subscription" button showing days left and end date.
- Server-level custom prefix support when premium is active (stored in servers.json under `custom_prefix`).
- Data persisted in simple JSON files in working directory (users.json, servers.json, economy.json, etc.).

Notes for real deployment:
- Replace `/premium grant` flow with your payment provider webhook that calls the bot (e.g., an owner-only endpoint or a secured bot command) to mark payment done and generate+DM the key.
- Keep your DISCORD_TOKEN and OWNER_ID safe.

This file is written to be clear and commented; adjust thresholds / rewards / values as needed.
"""

from web_server import keep_alive
keep_alive()  # lightweight keepalive if you host on Replit / similar

import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
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
# We keep a text-prefix bot for backward compatibility, but text commands should be gated to premium servers.
# If you prefer not to allow text commands at all, set command_prefix to None and remove the prefix command blocks.

def get_prefix(bot, message):
    """Return a prefix for text commands. If the guild is premium & has custom_prefix, return it.
    Otherwise return a benign default 've' (but text cmds will be blocked for non-premium by checks).
    """
    if not message.guild:
        # Allow DM prefix usage with 've' as fallback
        return "ve"
    servers = load_json("servers")
    entry = servers.get(str(message.guild.id), {})
    if entry.get("premium_until"):
        try:
            # check expiration
            until = datetime.datetime.fromisoformat(entry.get("premium_until"))
            if until > datetime.datetime.utcnow():
                return entry.get("custom_prefix", "ve")
        except Exception:
            pass
    return "ve"  # fallback but commands will be blocked by check

bot = commands.Bot(command_prefix=get_prefix, intents=intents, case_insensitive=True)
# remove default help to use our custom help (slash + text)
bot.remove_command("help")

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

# ensure files exist and are valid json
for fname in FILES.values():
    if not os.path.exists(fname):
        with open(fname, "w", encoding="utf-8") as f:
            json.dump({}, f)


def load_json(file_key: str) -> dict:
    path = FILES[file_key]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    # reset file
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
            "work_claims": {},
            "membership": False,  # VRTEX+ flag for the user (if you sell personal membership)
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
    users[sid] = users.get(sid, {})
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
# Premium flow helpers
# -----------------------------

def generate_otp(length=8) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(random.choice(chars) for _ in range(length))


def add_pending_key(user_id: int, months: int) -> str:
    servers = load_json("servers")
    pending = servers.get("_pending_keys", {})
    otp = generate_otp()
    # ensure uniqueness
    while otp in pending:
        otp = generate_otp()
    pending[otp] = {
        "user_id": user_id,
        "months": months,
        "created_at": utc_now().isoformat(),
        "used": False
    }
    servers["_pending_keys"] = pending
    save_json("servers", servers)
    return otp


def use_pending_key(otp: str) -> Optional[dict]:
    servers = load_json("servers")
    pending = servers.get("_pending_keys", {})
    entry = pending.get(otp)
    if not entry:
        return None
    if entry.get("used"):
        return None
    # mark used
    entry["used"] = True
    pending[otp] = entry
    servers["_pending_keys"] = pending
    save_json("servers", servers)
    return entry

# -----------------------------
# Premium activation / grant (owner-side helper)
# -----------------------------

@bot.tree.command(name="premium_grant", description="OWNER: mark payment done and generate OTP for user (owner-only).")
@app_commands.describe(user_id="Discord user id who paid", months="Number of months to grant the OTP for")
async def premium_grant(interaction: discord.Interaction, user_id: str, months: int = 1):
    # This command is intended for bot owner or your backend to call when a payment clears.
    if interaction.user.id != OWNER_ID and interaction.user.id not in TEAM_IDS:
        await interaction.response.send_message("Only the bot owner or team can run this.", ephemeral=True)
        return
    try:
        uid = int(user_id)
    except Exception:
        await interaction.response.send_message("Invalid user id.", ephemeral=True)
        return
    otp = add_pending_key(uid, months)
    # DM the purchaser with the key
    try:
        user = await bot.fetch_user(uid)
        await user.send(f"Thanks for your payment! Your VRTEX Economy premium activation key is:\n`{otp}`\nUse `/premium activate <key>` in the server where you'd like to enable VRTEX+.")
        await interaction.response.send_message(f"OTP generated and DM'd to <@{uid}>.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to DM user (they may have DMs off). OTP: `{otp}`\nError: {e}", ephemeral=True)

# Activation command: user uses OTP in a server to activate premium for that guild
@bot.tree.command(name="premium_activate", description="Activate VRTEX+ for this server with a one-time key.")
@app_commands.describe(key="One-time activation key you received by DM")
async def premium_activate(interaction: discord.Interaction, key: str):
    # must be used in guild and by a manager (server admin)
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild and interaction.user.id != OWNER_ID and interaction.user.id not in TEAM_IDS:
        await interaction.response.send_message("You need Manage Server permission to activate premium.", ephemeral=True)
        return
    pending = load_json("servers").get("_pending_keys", {})
    entry = pending.get(key)
    if not entry:
        await interaction.response.send_message("Invalid or expired key.", ephemeral=True)
        return
    if entry.get("used"):
        await interaction.response.send_message("This key has already been used.", ephemeral=True)
        return
    # Use and apply
    # mark used
    use_pending_key(key)
    months = int(entry.get("months", 1))
    now = utc_now()
    delta = datetime.timedelta(days=30 * months)
    servers = load_json("servers")
    guild_entry = servers.get(str(interaction.guild.id), {})
    existing_until = None
    if guild_entry.get("premium_until"):
        try:
            existing_until = datetime.datetime.fromisoformat(guild_entry.get("premium_until"))
        except Exception:
            existing_until = None
    if existing_until and existing_until > now:
        new_until = existing_until + delta
    else:
        new_until = now + delta
    guild_entry["premium_until"] = new_until.isoformat()
    # default custom prefix keeps previous or stays as 've' until set
    guild_entry.setdefault("custom_prefix", guild_entry.get("custom_prefix", "ve"))
    guild_entry.setdefault("disabled_commands", guild_entry.get("disabled_commands", []))
    servers[str(interaction.guild.id)] = guild_entry
    save_json("servers", servers)
    await interaction.response.send_message(f"✅ VRTEX+ activated for this server until **{new_until.date()}** ({(new_until - now).days} days).", ephemeral=True)
    # notify server owner in system channel if possible
    try:
        ch = interaction.guild.system_channel or interaction.channel
        await ch.send(f"🎉 Server premium activated by {interaction.user.mention}. VRTEX+ active until **{new_until.date()}**.")
    except Exception:
        pass

# -----------------------------
# Slash commands (primary interface) — examples: /help, /balance, /work, /settings
# -----------------------------

@bot.tree.command(name="help", description="Show VRTEX Economy help & commands")
async def slash_help(interaction: discord.Interaction):
    # custom help embed for slash users
    embed = discord.Embed(title="💠 VRTEX Economy — Help", description="Slash commands are available below. If you have VRTEX+ you may also use a custom text prefix.", color=discord.Color.from_rgb(88,101,242))
    embed.add_field(name="Quick", value="`/balance` `/work` `/profile` `/settings` `/premium activate`", inline=False)
    embed.set_footer(text="Tip: server admins can activate premium to unlock custom prefix and settings.")
    await interaction.response.send_message(embed=embed, ephemeral=False)


@bot.tree.command(name="balance", description="Show your balance")
@app_commands.describe(member="Member to view (optional)")
async def slash_balance(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    user = await get_user(target.id)
    guild_econ = get_guild_economy(interaction.guild.id) if interaction.guild else {"currency_symbol":"$"}
    sym = guild_econ.get("currency_symbol", "")
    embed = discord.Embed(title=f"{target.display_name}'s Balance", color=discord.Color.dark_gray())
    embed.add_field(name="Wallet", value=f"{user.get('wallet',0)} {sym}", inline=True)
    embed.add_field(name="Bank", value=f"{user.get('bank',0)} {sym}", inline=True)
    embed.add_field(name="Membership", value="VRTEX+" if user.get('membership') else "Normal", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="work", description="Work and earn (once per hour)")
async def slash_work(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)
    guild_id = str(interaction.guild.id) if interaction.guild else None
    if not guild_id:
        await interaction.response.send_message("Work can only be used inside a server.", ephemeral=True)
        return
    last_claims = user.get("work_claims", {})
    now = utc_now()
    last_iso = last_claims.get(guild_id)
    cooldown = 3600
    if last_iso:
        try:
            last_dt = datetime.datetime.fromisoformat(last_iso)
            delta = (now - last_dt).total_seconds()
            if delta < cooldown:
                await interaction.response.send_message(f"❌ You can work again in **{readable_time_delta(cooldown - delta)}**", ephemeral=True)
                return
        except Exception:
            pass
    reward = 1000
    if await is_plus(interaction.user.id):
        reward = int(reward * 1.25)
    user['wallet'] = user.get('wallet',0) + reward
    last_claims[guild_id] = now.isoformat()
    user['work_claims'] = last_claims
    await update_user(interaction.user.id, user)
    leveled = await add_xp(interaction.user.id, 20)
    msg = f"✅ You worked and earned **{reward}{get_guild_economy(interaction.guild.id).get('currency_symbol','')}**!"
    if leveled:
        msg += "\n🎉 You leveled up!"
    await interaction.response.send_message(msg)

# -----------------------------
# Settings slash command: shows view with Subscription button
# -----------------------------

class SettingsView(View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    @discord.ui.button(label="Subscription", style=discord.ButtonStyle.secondary, custom_id="sv_subscription")
    async def subscription_btn(self, interaction: discord.Interaction, button: Button):
        # show subscription info
        servers = load_json("servers")
        g = servers.get(str(self.guild.id), {})
        until_iso = g.get("premium_until")
        if not until_iso:
            await interaction.response.send_message("This server does not have VRTEX+ active.", ephemeral=True)
            return
        try:
            until = datetime.datetime.fromisoformat(until_iso)
        except Exception:
            await interaction.response.send_message("Subscription info corrupted.", ephemeral=True)
            return
        now = utc_now()
        if until < now:
            await interaction.response.send_message("VRTEX+ subscription has expired.", ephemeral=True)
            return
        delta = until - now
        await interaction.response.send_message(f"📅 VRTEX+ active until **{until.date()}** — **{delta.days} days** remaining.", ephemeral=True)


@bot.tree.command(name="settings", description="Server settings (Manage Server only). Shows Subscription status and economy options.)")
async def slash_settings(interaction: discord.Interaction):
    # permission check
    if not interaction.guild:
        await interaction.response.send_message("Settings must be used in a server.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_guild or interaction.user.id in TEAM_IDS or interaction.user.id == OWNER_ID):
        await interaction.response.send_message("You need Manage Server permission (or be owner/team) to use settings.", ephemeral=True)
        return
    econ = get_guild_economy(interaction.guild.id)
    embed = discord.Embed(title="⚙️ VRTEX Settings", color=discord.Color.blurple())
    embed.add_field(name="Economy", value=f"Currency: **{econ.get('currency_name')} {econ.get('currency_symbol','')}**\nStarting balance: **{econ.get('starting_balance',0)}**", inline=False)
    view = SettingsView(interaction.guild)
    # add an extra button for changing custom prefix if server is premium
    servers = load_json("servers")
    g = servers.get(str(interaction.guild.id), {})
    if g.get("premium_until"):
        # add a small 'Change Prefix' button
        async def change_prefix_cb(inter: discord.Interaction):
            # present a modal to change prefix
            class PrefixModal(Modal, title="Set Custom Prefix"):
                new_prefix = TextInput(label="New prefix (single token)", placeholder="e.g. ve or !", max_length=10, required=True)
                def __init__(self, guild):
                    super().__init__()
                    self.guild = guild
                async def on_submit(self, modal_inter: discord.Interaction):
                    val = self.new_prefix.value.strip()
                    # basic validation
                    if len(val) == 0:
                        await modal_inter.response.send_message("Invalid prefix.", ephemeral=True)
                        return
                    servers_local = load_json("servers")
                    servers_local.setdefault(str(self.guild.id), {})
                    servers_local[str(self.guild.id)]["custom_prefix"] = val
                    save_json("servers", servers_local)
                    await modal_inter.response.send_message(f"✅ Custom prefix set to `{val}`. You can now use `{val}help` (if available) as a text command in this server.", ephemeral=True)
            await inter.response.send_modal(PrefixModal(inter.guild))

        # attach as a ephemeral followup via a one-off button
        btn = Button(label="Change Prefix (Premium)", style=discord.ButtonStyle.primary)
        btn.callback = lambda inter: asyncio.create_task(change_prefix_cb(inter))
        view.add_item(btn)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

# -----------------------------
# Text (prefix) commands — gated to premium servers
# -----------------------------

def premium_required_text_command(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    servers = load_json("servers")
    entry = servers.get(str(ctx.guild.id), {})
    until = entry.get("premium_until")
    if not until:
        return False
    try:
        dt = datetime.datetime.fromisoformat(until)
        if dt > utc_now():
            return True
    except Exception:
        return False
    return False


def ensure_premium_text():
    async def predicate(ctx: commands.Context):
        if premium_required_text_command(ctx):
            return True
        await ctx.send("This server does not have VRTEX+ active. Use slash commands (default) or activate premium.")
        return False
    return commands.check(predicate)


@bot.command(name="help_text")
@ensure_premium_text()
async def help_text(ctx: commands.Context):
    # show same help but text-based. Only available in premium servers
    embed = discord.Embed(title="💠 VRTEX Economy — Help (text)")
    embed.add_field(name="Quick", value="`help` `balance` `work` `settings` `premium activate`", inline=False)
    await ctx.send(embed=embed)

# duplicate basic commands as text wrappers — they all check premium via decorator
@bot.command(name="balance_text")
@ensure_premium_text()
async def balance_text(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    await send_balance_text(ctx, member)

async def send_balance_text(ctx, member: discord.Member):
    user = await get_user(member.id)
    guild_econ = get_guild_economy(ctx.guild.id) if ctx.guild else {"currency_symbol":"$"}
    sym = guild_econ.get("currency_symbol", "")
    embed = discord.Embed(title=f"{member.display_name}'s Balance", color=discord.Color.dark_gray())
    embed.add_field(name="Wallet", value=f"{user.get('wallet',0)} {sym}", inline=True)
    embed.add_field(name="Bank", value=f"{user.get('bank',0)} {sym}", inline=True)
    await ctx.send(embed=embed)

# You can add other text-wrapped commands similarly. For brevity we keep a few examples.

# -----------------------------
# Small safety check for disabling commands per-server
# -----------------------------
@bot.check
async def global_command_block(ctx):
    # Allow DMs / missing guild gracefully
    if ctx.guild is None:
        return True
    # Always allow help_text (but it's gated above)
    if ctx.command and ctx.command.name in ("help_text", "balance_text"):
        return True
    servers = load_json("servers")
    server_entry = servers.get(str(ctx.guild.id), {})
    disabled = server_entry.get("disabled_commands", [])
    cmd_name = ctx.command.name if ctx.command else None
    if not cmd_name:
        return True
    if cmd_name in disabled:
        try:
            await ctx.send(f"⚠️ The command `{cmd_name}` is currently disabled on this server.")
        except Exception:
            pass
        return False
    return True

# -----------------------------
# On ready
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    # sync slash commands
    try:
        await bot.tree.sync()
        print("🔁 Slash commands synced.")
    except Exception as e:
        print("Warning: failed to sync commands:", e)

# -----------------------------
# Run bot
# -----------------------------
if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not set.")
    else:
        bot.run(TOKEN)
