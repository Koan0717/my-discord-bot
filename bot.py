import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import datetime
import asyncio
from dotenv import load_dotenv
import database
from keep_alive import keep_alive
from helpers import (
    JST, MSG_COOLDOWN, TC_XP_COOLDOWN, VC_XP_PER_MIN, ROOM_SETTINGS,
    get_setting, is_rank_eligible, is_vc_coins_eligible, check_and_assign_level_roles, send_log
)

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

class EconomyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.message_cooldowns = {} # {user_id: timestamp} (通貨用)
        self.tc_xp_cooldowns = {}   # {user_id: timestamp} (経験値用)
        self.vc_sessions = {}       # {user_id: join_timestamp}
        self.empty_custom_vcs = {}  # {channel_id: empty_since_timestamp}
        self.auto_vc_triggers = set()
        self.auto_vc_configs = {}  # {channel_id: config_dict}
        self.evaluation_settings = {}  # {guild_id: {"forum_channel_ids": set, "self_intro_channel_ids": set}}
        self.rank_settings_cache = {}  # {guild_id: {"whitelist": set, "blacklist": set, "categories": set, "blacklist_categories": set}}
        self.vc_coins_settings_cache = {}  # {guild_id: {"whitelist": set, "blacklist": set, "categories": set, "blacklist_categories": set}}
        self.role_room_prices = {}     # {(role_key, room_type, duration): price}
        self.spam_tracker = {}         # {user_id: {"last_content": str, "content_count": int, "everyone_count": int, "last_time": datetime}}
        self.invite_cache = {}         # {guild_id: {invite_code: uses}}
        self.antigrief_settings_cache = {} # {guild_id: {"categories": set, "channels": set, "exempt_roles": set}}


    def get_evaluation_config(self, guild_id: int) -> dict:
        if guild_id not in self.evaluation_settings:
            forum_vals = get_setting(self, "EVALUATION_FORUM_CHANNEL_IDS") or []
            forum_ids = forum_vals if isinstance(forum_vals, list) else ([forum_vals] if forum_vals else [])
            self.evaluation_settings[guild_id] = {
                "forum_channel_ids": set(forum_ids),
                "self_intro_channel_ids": set(get_setting(self, "SELF_INTRO_CHANNEL_IDS") or [])
            }
        return self.evaluation_settings[guild_id]

    def get_rank_config(self, guild_id: int) -> dict:
        if guild_id not in self.rank_settings_cache:
            return {"whitelist": set(), "blacklist": set(), "categories": set(), "blacklist_categories": set()}
        return self.rank_settings_cache[guild_id]

    async def fetch_and_cache_rank_config(self, guild_id: int) -> dict:
        data = await database.get_rank_settings(guild_id)
        self.rank_settings_cache[guild_id] = {
            "whitelist": set(data.get("whitelist", [])),
            "blacklist": set(data.get("blacklist", [])),
            "categories": set(data.get("categories", [])),
            "blacklist_categories": set(data.get("blacklist_categories", []))
        }
        return self.rank_settings_cache[guild_id]

    def get_vc_coins_config(self, guild_id: int) -> dict:
        if guild_id not in self.vc_coins_settings_cache:
            return {"whitelist": set(), "blacklist": set(), "categories": set(), "blacklist_categories": set()}
        return self.vc_coins_settings_cache[guild_id]

    async def fetch_and_cache_vc_coins_config(self, guild_id: int) -> dict:
        data = await database.get_vc_coins_settings(guild_id)
        self.vc_coins_settings_cache[guild_id] = {
            "whitelist": set(data.get("whitelist", [])),
            "blacklist": set(data.get("blacklist", [])),
            "categories": set(data.get("categories", [])),
            "blacklist_categories": set(data.get("blacklist_categories", []))
        }
        return self.vc_coins_settings_cache[guild_id]

    def get_antigrief_config(self, guild_id: int) -> dict:
        if guild_id not in self.antigrief_settings_cache:
            self.antigrief_settings_cache[guild_id] = {
                "categories": set(),
                "channels": set(),
                "exempt_roles": set()
            }
        return self.antigrief_settings_cache[guild_id]

    async def fetch_and_cache_antigrief_config(self, guild_id: int) -> dict:
        data = await database.get_antigrief_settings(guild_id)
        self.antigrief_settings_cache[guild_id] = {
            "categories": set(data.get("categories", [])),
            "channels": set(data.get("channels", [])),
            "exempt_roles": set(data.get("exempt_roles", []))
        }
        return self.antigrief_settings_cache[guild_id]


    async def setup_hook(self):
        await database.setup_db()
        try:
            from cogs.shop import ShopPanelView
            self.add_view(ShopPanelView(self))
        except Exception as e:
            print(f'Failed to load ShopPanelView: {e}')
        self.bot_settings = await database.load_settings()

        # 荒らし対策設定のロード
        try:
            db_antigrief = await database.get_all_antigrief_settings()
            for s in db_antigrief:
                self.antigrief_settings_cache[s["guild_id"]] = {
                    "categories": set(s.get("categories", [])),
                    "channels": set(s.get("channels", [])),
                    "exempt_roles": set(s.get("exempt_roles", []))
                }
        except Exception as e:
            print(f"[ERROR] Failed to load antigrief settings from DB: {e}")

        # ランク設定のロード
        try:
            db_rank = await database.get_all_rank_settings()
            for r in db_rank:
                self.rank_settings_cache[r["guild_id"]] = {
                    "whitelist": set(r.get("whitelist", [])),
                    "blacklist": set(r.get("blacklist", [])),
                    "categories": set(r.get("categories", [])),
                    "blacklist_categories": set(r.get("blacklist_categories", []))
                }
        except Exception as e:
            print(f"[ERROR] Failed to load rank settings from DB: {e}")

        # VCコイン獲得制限設定のロード
        try:
            db_vc_coins = await database.get_all_vc_coins_settings()
            for r in db_vc_coins:
                self.vc_coins_settings_cache[r["guild_id"]] = {
                    "whitelist": set(r.get("whitelist", [])),
                    "blacklist": set(r.get("blacklist", [])),
                    "categories": set(r.get("categories", [])),
                    "blacklist_categories": set(r.get("blacklist_categories", []))
                }
        except Exception as e:
            print(f"[ERROR] Failed to load VC coins settings from DB: {e}")

        # 自己紹介・評価設定のロード
        try:
            db_eval_settings = await database.get_all_evaluation_settings()
            for s in db_eval_settings:
                self.evaluation_settings[s["guild_id"]] = {
                    "forum_channel_ids": set(s["forum_channel_ids"]),
                    "self_intro_channel_ids": set(s["self_intro_channel_ids"])
                }
        except Exception as e:
            print(f"[ERROR] Failed to load evaluation settings from DB: {e}")

        # VC作成トリガーの読み込み
        self.auto_vc_triggers = set(await database.get_auto_vc_triggers())
        try:
            db_configs = await database.get_all_auto_vc_configs()
            for cfg in db_configs:
                self.auto_vc_configs[cfg["channel_id"]] = cfg
        except Exception as e:
            print(f"[ERROR] Failed to load auto VC configs: {e}")

        create_vc_id = get_setting(self, "CREATE_VC_CHANNEL_ID")
        if not self.auto_vc_triggers and create_vc_id != 123456789012345678:
            await database.add_auto_vc_trigger(create_vc_id)
            self.auto_vc_triggers.add(create_vc_id)
            await database.save_auto_vc_config(create_vc_id, "", True, True, False, True, True)
            self.auto_vc_configs[create_vc_id] = {
                "channel_id": create_vc_id,
                "base_name": "",
                "allow_rename": True,
                "include_owner_name": True,
                "use_numbering": False,
                "allow_limit_change": True,
                "show_panel": True
            }

        # 部屋の価格設定のキャッシュロード
        try:
            db_prices = await database.get_all_room_prices()
            for p_info in db_prices:
                rtype = p_info["room_type"]
                dur = p_info["duration"]
                price = p_info["price"]
                if rtype in ROOM_SETTINGS and dur in ROOM_SETTINGS[rtype]:
                    ROOM_SETTINGS[rtype][dur]["price"] = price
        except Exception as e:
            print(f"[ERROR] Failed to load room prices from DB: {e}")

        # ロール別部屋価格のキャッシュロード
        try:
            db_role_prices = await database.get_all_role_room_prices()
            for rp in db_role_prices:
                self.role_room_prices[(rp["role_key"], rp["room_type"], rp["duration"])] = rp["price"]
        except Exception as e:
            print(f"[ERROR] Failed to load role room prices from DB: {e}")

        # Cogsのロード
        cogs_to_load = [
            "cogs.admin",
            "cogs.economy",
            "cogs.leveling",
            "cogs.rooms",
            "cogs.gambling",
            "cogs.interview",
            "cogs.evaluation",
            "cogs.utility"
        ]
        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                print(f"[OK] Loaded Cog: {cog}")
            except Exception as e:
                print(f"[ERROR] Failed to load Cog {cog}: {e}")

        await self.tree.sync()
        print(f"[OK] Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        print("[OK] Slash commands and persistent views are synced.")

bot = EconomyBot()

# --- 中央集権イベント (メインハンドラ) ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        if member.bot: return
        
        # VCログの送信
        guild = member.guild
        if guild:
            embed = None
            if before.channel is None and after.channel is not None:
                embed = discord.Embed(
                    title="🎙️ VC参加",
                    description=f"{member.mention} が {after.channel.mention} に参加しました。",
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.now(JST)
                )
                embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
            elif before.channel is not None and after.channel is None:
                embed = discord.Embed(
                    title="🎙️ VC退出",
                    description=f"{member.mention} が {before.channel.mention} から退出しました。",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(JST)
                )
                embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
            elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
                embed = discord.Embed(
                    title="🎙️ VC移動",
                    description=f"{member.mention} が {before.channel.mention} から {after.channel.mention} に移動しました。",
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now(JST)
                )
                embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
                
            if embed:
                await send_log(bot, guild, "vc_join_leave", embed)
    except Exception as log_e:
        print(f"[ERROR] Failed to send VC log: {log_e}")

    try:
        if member.bot: return
        user_id = member.id
        now_aware = datetime.datetime.now(JST)

        # 参加・移動時
        if after.channel is not None:
            is_join = before.channel is None or before.channel.id != after.channel.id
            if is_join:
                in_correct_category = is_rank_eligible(bot, after.channel)
                eval_category_id = get_setting(bot, "EVALUATION_CATEGORY_ID")
                is_eval_category = (after.channel.category and after.channel.category.id == eval_category_id)
                in_coins_eligible = is_vc_coins_eligible(bot, after.channel)
                
                if in_correct_category or is_eval_category or in_coins_eligible:
                    print(f"[VC XP/Coins] Started session for {member.display_name} (rank={in_correct_category}, eval={is_eval_category}, coins={in_coins_eligible})")
                    bot.vc_sessions[user_id] = now_aware
        
        # 退出・移動時
        if before.channel is not None and (after.channel is None or before.channel != after.channel):
            join_time = bot.vc_sessions.pop(user_id, None)
            if join_time:
                duration_seconds = int((now_aware - join_time).total_seconds())
                if before.channel.category:
                    await database.add_vc_duration(user_id, before.channel.category.id, duration_seconds)
                
                duration_minutes = duration_seconds // 60
                if duration_minutes > 0:
                    if is_rank_eligible(bot, before.channel):
                        xp_reward = duration_minutes * VC_XP_PER_MIN
                        new_lv = await database.add_xp(user_id, xp_reward, "vc")
                        if new_lv:
                            lv_channel = bot.get_channel(get_setting(bot, "LEVEL_UP_CHANNEL_ID"))
                            if lv_channel:
                                await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
                            await check_and_assign_level_roles(bot, member, "vc", new_lv)
    except Exception as global_e:
        print(f"CRITICAL ERROR in on_voice_state_update: {global_e}")

if __name__ == "__main__":
    if TOKEN:
        discord.utils.setup_logging()
        keep_alive()
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN is not set in .env")