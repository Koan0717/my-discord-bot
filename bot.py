import discord
from discord.ext import commands
import os
import datetime
from dotenv import load_dotenv
import database
import config

# 各種 Persistent Views のインポート
from cogs.rooms import MainInnPanelView, TempInnPanelView, LuxuryInnPanelView, CustomRoomView, InnControlView, RoomControlView, CustomRoomControlView, VCRenamePanelView
from cogs.gambling import ChinchiroView, CoinflipView, SlotView, BlackjackView, RouletteView
from cogs.interview import InterviewPanelView
from cogs.tickets import EmblemRequestPanelView, ConfessionRequestPanelView, TicketControlView, InquiryRequestPanelView, CustomTicketPanelView
from cogs.admin import PanelSetupView, VCTriggerPanelView
from cogs.logging_cog import AnonymousChatPanelView

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

class EconomyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.message_cooldowns = {}      # {user_id: timestamp} (通貨用)
        self.tc_xp_cooldowns = {}        # {user_id: timestamp} (経験値用)
        self.vc_sessions = {}            # {user_id: join_timestamp}
        self.eval_vc_sessions = {}       # {user_id: join_timestamp} (評価浮上時間用)
        self.empty_custom_vcs = {}       # {channel_id: empty_since_timestamp}
        self.auto_vc_triggers = set()
        self.evaluation_settings = {}    # {guild_id: {"forum_channel_ids": set, "self_intro_channel_ids": set}}
        self.rank_settings = {}          # {guild_id: {"whitelist": set, "blacklist": set, "categories": set}}
        self.spam_tracker = {}           # {user_id: {"last_content": str, "content_count": int, "everyone_count": int, "last_time": datetime}}
        self.bot_settings = {}
        self.invite_cache = {}           # {guild_id: {invite_code: uses}}
        self.antigrief_settings_cache = {} # {guild_id: {"categories": set, "channels": set, "exempt_roles": set}}


    def get_evaluation_config(self, guild_id: int) -> dict:
        if guild_id not in self.evaluation_settings:
            forum_vals = config.get_setting(self, "EVALUATION_FORUM_CHANNEL_IDS") or []
            forum_ids = forum_vals if isinstance(forum_vals, list) else ([forum_vals] if forum_vals else [])
            self.evaluation_settings[guild_id] = {
                "forum_channel_ids": set(forum_ids),
                "self_intro_channel_ids": set(config.get_setting(self, "SELF_INTRO_CHANNEL_IDS") or [])
            }
        return self.evaluation_settings[guild_id]

    def get_rank_config(self, guild_id: int) -> dict:
        if guild_id not in self.rank_settings:
            self.rank_settings[guild_id] = {
                "whitelist": set(),
                "blacklist": set(),
                "categories": set(),
                "whitelist_categories": set(),
                "blacklist_categories": set()
            }
        return self.rank_settings[guild_id]

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

        # ランク設定の読み込み
        try:
            db_rank_settings = await database.get_all_rank_settings()
            for s in db_rank_settings:
                self.rank_settings[s["guild_id"]] = {
                    "whitelist": set(s.get("whitelist", [])),
                    "blacklist": set(s.get("blacklist", [])),
                    "whitelist_categories": set(s.get("whitelist_categories", [])),
                    "blacklist_categories": set(s.get("blacklist_categories", []))
                }
        except Exception as e:
            print(f"[ERROR] Failed to load rank settings from DB: {e}")

        # VC作成トリガーの読み込みとマイグレーション
        self.auto_vc_triggers = set(await database.get_auto_vc_triggers())
        create_vc_id = config.get_setting(self, "CREATE_VC_CHANNEL_ID")
        if not self.auto_vc_triggers and create_vc_id != 123456789012345678:
            await database.add_auto_vc_trigger(create_vc_id)
            self.auto_vc_triggers.add(create_vc_id)

        # 部屋の価格設定キャッシュの同期
        try:
            db_prices = await database.get_all_room_prices()
            for p_info in db_prices:
                rtype = p_info["room_type"]
                dur = p_info["duration"]
                price = p_info["price"]
                if rtype in config.ROOM_SETTINGS and dur in config.ROOM_SETTINGS[rtype]:
                    config.ROOM_SETTINGS[rtype][dur]["price"] = price
        except Exception as e:
            print(f"[ERROR] Failed to load room prices from DB: {e}")

        # Persistent Views の追加
        self.add_view(MainInnPanelView())
        self.add_view(TempInnPanelView())
        self.add_view(LuxuryInnPanelView())
        self.add_view(CustomRoomView())
        self.add_view(InnControlView())
        self.add_view(RoomControlView())
        self.add_view(CustomRoomControlView())
        self.add_view(ChinchiroView())
        self.add_view(CoinflipView())
        self.add_view(SlotView())
        self.add_view(BlackjackView())
        self.add_view(RouletteView())
        self.add_view(InterviewPanelView())
        self.add_view(EmblemRequestPanelView())
        self.add_view(ConfessionRequestPanelView())
        self.add_view(TicketControlView())
        self.add_view(VCRenamePanelView())
        self.add_view(PanelSetupView())
        self.add_view(InquiryRequestPanelView())
        self.add_view(AnonymousChatPanelView())
        self.add_view(CustomTicketPanelView())
        self.add_view(VCTriggerPanelView())

        # Cogsのロード
        cogs = [
            "cogs.economy",
            "cogs.gambling",
            "cogs.rooms",
            "cogs.tickets",
            "cogs.ranking",
            "cogs.evaluation",
            "cogs.interview",
            "cogs.events",
            "cogs.reaction_roles",
            "cogs.admin",
            "cogs.logging_cog",
            "cogs.shop"
        ]
        for extension in cogs:
            try:
                await self.load_extension(extension)
                print(f"[OK] Loaded extension: {extension}")
            except Exception as cog_e:
                print(f"[ERROR] Failed to load extension {extension}: {cog_e}")

        await self.tree.sync()

        # Render Health Check用 Webサーバー (aiohttp版)
        try:
            from aiohttp import web
            async def handle_ping(request):
                return web.Response(text="Bot is alive!")
            app = web.Application()
            app.add_routes([web.get('/', handle_ping)])
            runner = web.AppRunner(app)
            await runner.setup()
            port = int(os.environ.get("PORT", 8080))
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            print(f"[OK] Web server started on port {port} (Render Health Check)", flush=True)
        except Exception as web_e:
            print(f"[ERROR] Failed to start web server: {web_e}", flush=True)

        print(f"[SUCCESS] Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        print("[SUCCESS] Slash commands and persistent views are synced.")

bot = EconomyBot()

@bot.event
async def on_ready():
    now_aware = datetime.datetime.now(config.JST)
    eval_cat_id = config.get_setting(bot, "EVAL_TIME_CATEGORY_ID")
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            xp_enabled = config.is_xp_enabled(bot, vc)
            is_eval = vc.category and vc.category.id == eval_cat_id
            for member in vc.members:
                if member.bot:
                    continue
                if xp_enabled and member.id not in bot.vc_sessions:
                    bot.vc_sessions[member.id] = now_aware
                    print(f"[Startup] Started VC XP session for {member.display_name}")
                if is_eval and member.id not in bot.eval_vc_sessions:
                    bot.eval_vc_sessions[member.id] = now_aware
                    print(f"[Startup] Started VC Eval session for {member.display_name}")

if __name__ == "__main__":
    if TOKEN:
        discord.utils.setup_logging()
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN is not set in .env")
