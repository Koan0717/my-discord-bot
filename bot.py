import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import random
import datetime
import asyncio
from dotenv import load_dotenv
import database
import json
import re

# --- 設定 ---
CURRENCY_NAME = "Rune"
JST = datetime.timezone(datetime.timedelta(hours=9))

# 獲得量の設定
MSG_COOLDOWN = 60     # メッセージ獲得のクールダウン（秒）


# 経験値の設定
TC_XP_REWARD = 10      # メッセージ1通あたりのXP
TC_XP_COOLDOWN = 10    # TC XP獲得のクールダウン（秒）
VC_XP_PER_MIN = 15     # VC滞在1分あたりのXP
LEVEL_UP_CHANNEL_ID = 123456789012345678
RANKING_CATEGORY_NAME = "【仮】ランク対象カテゴリ名"  # ランク機能が有効なカテゴリー

# 部屋作成の設定
ROOM_SETTINGS = {
    "宿": {
        12: {"price": 10000, "duration_hours": 12},
        24: {"price": 15000, "duration_hours": 24}
    },
    "高級宿": {
        12: {"price": 150000, "duration_hours": 12},
        24: {"price": 250000, "duration_hours": 24}
    },
    "カスタムVC": {
        24: {"price": 30000, "duration_hours": 24}
    }
}
CREATE_VC_CHANNEL_ID = 123456789012345678

# 面接・入界設定
NEW_MEMBER_ROLE_NAME = "【仮】新規メンバーロール名"
PENDING_MEMBER_ROLE_NAME = "【仮】入界待機者ロール名"
INTERVIEWER_ROLE_NAMES = ["【仮】面接官ロール名A", "【仮】面接官ロール名B"]
MAIN_SUB_MEMBER_ROLE_NAMES = ["【仮】本・準メンバーロール名A", "【仮】本・準メンバーロール名B"]
EMBLEM_MANAGER_ROLE_NAME = "【仮】スタンプ統括ロール名"
EMBLEM_MASTER_ROLE_NAME = "【仮】スタンプ制作ロール名"
CONFESSION_PRIEST_ROLE_NAME = "【仮】告解司祭ロール名"
PRIEST_ROLE_NAME = "【仮】司祭ロール名"
INITIAL_COINS = 30000

# 自己紹介・評価設定
SELF_INTRO_CHANNEL_IDS = [123456789012345678, 123456789012345678]
EVALUATION_FORUM_CHANNEL_IDS = []

# --- 運営権限チェック用の仮ロール名 ---
ADMIN_ROLE_NAMES = ["【仮】管理者ロール名A", "【仮】管理者ロール名B"]
EVALUATOR_ROLE_NAMES = ["【仮】評価員ロール名A", "【仮】評価員ロール名B"]

# --- ランク対象設定 (TC/VC XP対象) は別途DB管理されているため、
# 初期設定の RANKING_CATEGORY_ID は「評価時間対象カテゴリー」として扱います。
# 移行のため、キー名は EVAL_TIME_CATEGORY_ID とし、RANKING_CATEGORY_ID からのフォールバックを設けます。

# --- 動的設定管理 (DB保存) ---
DEFAULT_SETTINGS = {
    "LEVEL_UP_CHANNEL_ID": 123456789012345678,
    "CREATE_VC_CHANNEL_ID": 123456789012345678,
    "EVAL_TIME_CATEGORY_ID": 123456789012345678,
    "NEW_MEMBER_ROLE_ID": 123456789012345678,
    "PENDING_MEMBER_ROLE_ID": 123456789012345678,
    "INTERVIEWER_ROLE_IDS": [],
    "MAIN_SUB_MEMBER_ROLE_IDS": [],
    "EMBLEM_MANAGER_ROLE_ID": 123456789012345678,
    "EMBLEM_MASTER_ROLE_ID": 123456789012345678,
    "CONFESSION_PRIEST_ROLE_ID": 123456789012345678,
    "PRIEST_ROLE_ID": 123456789012345678,
    "ADMIN_ROLE_IDS": [],
    "EVALUATOR_ROLE_IDS": [],
    "EVENT_MANAGER_ROLE_IDS": [],
    "SELF_INTRO_CHANNEL_IDS": [],
    "EVALUATION_FORUM_CHANNEL_IDS": []
}

def get_setting(key: str):
    if hasattr(bot, 'bot_settings') and key in bot.bot_settings:
        return bot.bot_settings[key]
    if key == "EVAL_TIME_CATEGORY_ID" and hasattr(bot, 'bot_settings') and "RANKING_CATEGORY_ID" in bot.bot_settings:
        return bot.bot_settings["RANKING_CATEGORY_ID"]
    return DEFAULT_SETTINGS.get(key)


def get_role_by_setting(guild, key, default_name):
    role_id = get_setting(key)
    role = guild.get_role(role_id) if role_id else None
    if not role:
        role = discord.utils.get(guild.roles, name=default_name)
    return role

def get_role_by_id_or_name(guild, role_id, default_name):
    role = guild.get_role(role_id) if role_id else None
    if not role:
        role = discord.utils.get(guild.roles, name=default_name)
    return role

def has_event_manager_role(user: discord.Member):
    event_manager_role_ids = get_setting("EVENT_MANAGER_ROLE_IDS")
    if not event_manager_role_ids:
        event_manager_role_ids = []
    user_role_ids = [role.id for role in user.roles]
    if any(rid in event_manager_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    return False

def has_admin_role(user: discord.Member):
    admin_role_ids = get_setting("ADMIN_ROLE_IDS")
    user_role_ids = [role.id for role in user.roles]
    if any(rid in admin_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    user_role_names = [role.name for role in user.roles]
    if any(name in ADMIN_ROLE_NAMES for name in user_role_names):
        return True
    return False

def get_evaluator_tier(user: discord.Member) -> int:
    if user.guild_permissions.administrator: return 3
    user_role_ids = [r.id for r in user.roles]
    
    admin_ids = get_setting("ADMIN_ROLE_IDS") or []
    if any(rid in admin_ids for rid in user_role_ids): return 3
    
    tier3_ids = get_setting("EVALUATOR_TIER3_ROLE_IDS") or []
    if any(rid in tier3_ids for rid in user_role_ids): return 3
    
    tier2_ids = get_setting("EVALUATOR_TIER2_ROLE_IDS") or []
    if any(rid in tier2_ids for rid in user_role_ids): return 2
    
    tier1_ids = get_setting("EVALUATOR_TIER1_ROLE_IDS") or []
    if any(rid in tier1_ids for rid in user_role_ids): return 1
    
    old_eval_ids = get_setting("EVALUATOR_ROLE_IDS") or []
    if any(rid in old_eval_ids for rid in user_role_ids): return 1
    
    user_role_names = [role.name for role in user.roles]
    if any(name in EVALUATOR_ROLE_NAMES or name in ADMIN_ROLE_NAMES for name in user_role_names):
        return 1
    
    return 0

def has_evaluator_role(user: discord.Member) -> bool:
    return get_evaluator_tier(user) > 0

def has_interviewer_role(user: discord.Member):
    interviewer_role_ids = get_setting("INTERVIEWER_ROLE_IDS")
    user_role_ids = [r.id for r in user.roles]
    if any(rid in interviewer_role_ids for rid in user_role_ids):
        return True
    user_role_names = [r.name for r in user.roles]
    if any(name in INTERVIEWER_ROLE_NAMES for name in user_role_names):
        return True
    return False

def is_main_or_sub_member(user: discord.Member):
    main_sub_role_ids = get_setting("MAIN_SUB_MEMBER_ROLE_IDS")
    user_role_ids = [r.id for r in user.roles]
    if any(rid in main_sub_role_ids for rid in user_role_ids):
        return True
    user_role_names = [r.name for r in user.roles]
    if any(name in MAIN_SUB_MEMBER_ROLE_NAMES for name in user_role_names):
        return True
    return False

def is_in_eval_time_category(channel):
    if not channel or not channel.category:
        return False
    eval_cat_id = get_setting("EVAL_TIME_CATEGORY_ID")
    if channel.category.id == eval_cat_id:
        return True
    ranking_cat_name = get_setting("RANKING_CATEGORY_NAME")
    if ranking_cat_name and ranking_cat_name.lower() in channel.category.name.lower():
        return True
    return False


def is_xp_enabled(channel):
    try:
        if not channel or not channel.guild:
            return False
        cfg = bot.get_rank_config(channel.guild.id)
        whitelist = cfg.get("whitelist", set())
        blacklist = cfg.get("blacklist", set())
        wl_categories = cfg.get("whitelist_categories", set())
        bl_categories = cfg.get("blacklist_categories", set())
        
        # どちらも未指定の場合はすべてのチャンネルを対象にする
        if not whitelist and not blacklist and not wl_categories and not bl_categories:
            return True
            
        # 無効チャンネル・カテゴリーは最優先で除外
        if channel.id in blacklist:
            return False
        if channel.category and channel.category.id in bl_categories:
            return False
            
        # 有効（ホワイトリスト）が指定されている場合はその中のみ対象
        # 有効が指定されていない場合は無効以外すべてが対象
        if whitelist or wl_categories:
            in_whitelist = (channel.id in whitelist) or (channel.category and channel.category.id in wl_categories)
            if not in_whitelist:
                return False
            
        return True
    except Exception as e:
        print(f"[ERROR] Error in is_xp_enabled: {e}")
        return False

def is_in_evaluation_category(channel):
    if not channel or not channel.category:
        return False
    cfg = bot.get_rank_config(channel.guild.id)
    categories = cfg.get("categories", set())
    if categories:
        return channel.category.id in categories
    eval_cat_id = get_setting("EVAL_TIME_CATEGORY_ID")
    if channel.category.id == eval_cat_id:
        return True
    ranking_cat_name = get_setting("RANKING_CATEGORY_NAME")
    if ranking_cat_name and ranking_cat_name.lower() in channel.category.name.lower():
        return True
    return False


def format_evaluation_datetime(dt: datetime.datetime) -> str:
    if not dt:
        return "データなし"
    if dt.tzinfo is not None:
        dt = dt.astimezone(JST)
    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
    return dt.strftime(f"%Y年%m月%d日({weekday_ja}) %H:%M")

async def check_and_assign_level_roles(member: discord.Member, level_type: str, new_level: int):
    rewards = await database.get_level_role_rewards(level_type)
    if not rewards:
        return

    target_level = -1
    for r in rewards:
        if r["level"] <= new_level:
            target_level = max(target_level, r["level"])

    roles_to_add = []
    roles_to_remove = []

    for r in rewards:
        role = member.guild.get_role(r["role_id"])
        if not role: continue

        if r["level"] == target_level:
            if role not in member.roles:
                roles_to_add.append(role)
        else:
            if role in member.roles:
                roles_to_remove.append(role)

    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=f"{level_type.upper()}レベル更新 (古いロールの解除)")
        if roles_to_add:
            await member.add_roles(*roles_to_add, reason=f"{level_type.upper()}レベル到達報酬 (Lv.{new_level})")
            
            role_mentions = ", ".join([role.mention for role in roles_to_add])
            lv_channel_id = get_setting("LEVEL_UP_CHANNEL_ID")
            lv_channel = member.guild.get_channel(lv_channel_id)
            if lv_channel:
                await lv_channel.send(f"🎁 {member.mention} が {level_type.upper()} レベル {new_level} に達したため、以下のロールが付与されました！\n{role_mentions}")
    except Exception as e:
        print(f"[ERROR] check_and_assign_level_roles for {member.display_name}: {e}")

# ------------

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
        self.eval_vc_sessions = {}  # {user_id: join_timestamp} (評価浮上時間用)
        self.empty_custom_vcs = {}  # {channel_id: empty_since_timestamp}
        self.auto_vc_triggers = set()
        self.evaluation_settings = {}  # {guild_id: {"forum_channel_ids": set, "self_intro_channel_ids": set}}
        self.rank_settings = {}  # {guild_id: {"whitelist": set, "blacklist": set, "categories": set}}
        self.spam_tracker = {}  # {user_id: {"last_content": str, "content_count": int, "everyone_count": int, "last_time": datetime}}


    def get_evaluation_config(self, guild_id: int) -> dict:
        if guild_id not in self.evaluation_settings:
            # データベース未設定の場合のグローバルデフォルトフォールバック
            forum_vals = get_setting("EVALUATION_FORUM_CHANNEL_IDS") or []
            forum_ids = forum_vals if isinstance(forum_vals, list) else ([forum_vals] if forum_vals else [])
            self.evaluation_settings[guild_id] = {
                "forum_channel_ids": set(forum_ids),
                "self_intro_channel_ids": set(get_setting("SELF_INTRO_CHANNEL_IDS") or [])
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

    async def setup_hook(self):
        await database.setup_db()
        # Bot設定値のロード
        self.bot_settings = await database.load_settings()

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

        # ランク設定の読み込み（カテゴリ別ホワイトリスト/ブラックリスト）
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
        create_vc_id = get_setting("CREATE_VC_CHANNEL_ID")
        if not self.auto_vc_triggers and create_vc_id != 123456789012345678:
            await database.add_auto_vc_trigger(create_vc_id)
            self.auto_vc_triggers.add(create_vc_id)

        # 部屋の価格設定をデータベースから読み込んでキャッシュを更新
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
        
        # グループの登録
        self.tree.add_command(AdminGroup())
        self.tree.add_command(InterviewerGroup())
        self.tree.add_command(EvaluationGroup())
        self.tree.add_command(EvaluatorSheetGroup())
        self.tree.add_command(EventGroup())
        
        await self.tree.sync()
        self.check_expired_rooms.start()
        self.vc_reward_loop.start()

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
            print(f"✅ Web server started on port {port} (Render Health Check)", flush=True)
        except Exception as web_e:
            print(f"[ERROR] Failed to start web server: {web_e}", flush=True)

        print(f"✅ Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        print("✅ Slash commands and persistent views are synced.")

    @tasks.loop(minutes=1)
    async def check_expired_rooms(self):
        # 1. 有効期限切れの部屋を削除
        expired_channel_ids = await database.get_expired_rooms()
        for channel_id in expired_channel_ids:
            channel = self.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete()
                except discord.NotFound:
                    pass
            await database.remove_room(channel_id)
            self.empty_custom_vcs.pop(channel_id, None)
        
        # 2. 無人のカスタムVCをチェックして削除 (10分経過)
        now = datetime.datetime.now(JST)
        to_delete = []
        for channel_id, empty_since in list(self.empty_custom_vcs.items()):
            if (now - empty_since).total_seconds() >= 600: # 10分 = 600秒
                to_delete.append(channel_id)
        
        for channel_id in to_delete:
            channel = self.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete()
                except discord.NotFound:
                    pass
            await database.remove_room(channel_id)
            self.empty_custom_vcs.pop(channel_id, None)

    @check_expired_rooms.before_loop
    async def before_check_expired_rooms(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=1)
    async def vc_reward_loop(self):
        now = datetime.datetime.now(JST)
        for user_id, last_reward_time in list(self.vc_sessions.items()):
            member = None
            # 全てのサーバーからユーザーを探す
            for guild in self.guilds:
                m = guild.get_member(user_id)
                if m and m.voice and m.voice.channel:
                    member = m
                    break
            
            if member:
                # カテゴリーのチェック (部分一致・大文字小文字無視)
                in_correct_category = is_xp_enabled(member.voice.channel)
                
                if not in_correct_category:
                    # 条件を満たしていない場合はセッションを終了
                    self.vc_sessions.pop(user_id, None)
                    continue

                elapsed_minutes = int((now - last_reward_time).total_seconds() / 60)
                if elapsed_minutes >= 1:
                    xp_reward = elapsed_minutes * VC_XP_PER_MIN
                    category_name = member.voice.channel.category.name if member.voice.channel and member.voice.channel.category else "なし"
                    print(f"[DEBUG] VC XP Awarding: {member.display_name} in {category_name}")
                    new_lv = await database.add_xp(user_id, xp_reward, "vc")
                    
                    # 更新
                    self.vc_sessions[user_id] = now
                    
                    if new_lv:
                        lv_channel = self.get_channel(get_setting("LEVEL_UP_CHANNEL_ID"))
                        if lv_channel:
                            await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
                        await check_and_assign_level_roles(member, "vc", new_lv)
            else:
                # ユーザーがどのVCにもいない、またはオフライン
                self.vc_sessions.pop(user_id, None)

        # 評価時間対象カテゴリーの浮上時間（毎分中間保存）
        eval_cat_id = get_setting("EVAL_TIME_CATEGORY_ID")
        for user_id, last_reward_time in list(self.eval_vc_sessions.items()):
            member = None
            for guild in self.guilds:
                m = guild.get_member(user_id)
                if m and m.voice and m.voice.channel:
                    member = m
                    break
            
            if member:
                # 依然として評価時間対象カテゴリーにいるかチェック
                in_correct_category = member.voice.channel.category and member.voice.channel.category.id == eval_cat_id
                if not in_correct_category:
                    self.eval_vc_sessions.pop(user_id, None)
                    continue

                elapsed_seconds = int((now - last_reward_time).total_seconds())
                if elapsed_seconds >= 60:
                    await database.add_evaluation_vc_time(user_id, elapsed_seconds)
                    print(f"[Eval Time] Mid-loop added {elapsed_seconds}s to {member.display_name}")
                    self.eval_vc_sessions[user_id] = now
            else:
                self.eval_vc_sessions.pop(user_id, None)


bot = EconomyBot()

@bot.event
async def on_ready():
    now_aware = datetime.datetime.now(JST)
    eval_cat_id = get_setting("EVAL_TIME_CATEGORY_ID")
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            xp_enabled = is_xp_enabled(vc)
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


# --- ログ用ヘルパー ---
async def send_log(guild: discord.Guild, log_type: str, embed: discord.Embed):
    if not guild:
        return
    channel_id = await database.get_log_channel(guild.id, log_type)
    if channel_id:
        channel = guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await guild.fetch_channel(channel_id)
            except:
                pass
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"[ERROR] Failed to send log to channel {channel_id}: {e}")

async def send_economy_log(guild: discord.Guild, title: str, description: str, user: discord.Member = None, color: discord.Color = discord.Color.gold()):
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.datetime.now(JST))
    if user:
        embed.set_author(name=f"{user} (ID: {user.id})", icon_url=user.display_avatar.url)
    await send_log(guild, "economy", embed)

# --- イベント ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    user_id = message.author.id
    now = datetime.datetime.now(JST)

    # 荒らし対策: 連続同じメッセージ、連続@everyone
    if isinstance(message.author, discord.Member):
        user_tracker = bot.spam_tracker.setdefault(user_id, {
            "last_content": None,
            "content_count": 0,
            "everyone_count": 0,
            "last_time": now
        })

        # 60秒以上経過していればリセット
        if (now - user_tracker["last_time"]).total_seconds() > 60:
            user_tracker["content_count"] = 0
            user_tracker["everyone_count"] = 0

        user_tracker["last_time"] = now

        timeout_reason = None

        # 同じメッセージの連続検知 (内容が存在する場合)
        if message.content and message.content == user_tracker["last_content"]:
            user_tracker["content_count"] += 1
            if user_tracker["content_count"] >= 3:
                timeout_reason = "連続で同じメッセージを送信したため"
        else:
            user_tracker["last_content"] = message.content
            user_tracker["content_count"] = 1

        # @everyone or @here の連続検知
        if message.mention_everyone:
            user_tracker["everyone_count"] += 1
            if user_tracker["everyone_count"] >= 3:
                timeout_reason = "連続で@everyoneメンションを送信したため"
        else:
            user_tracker["everyone_count"] = 0

        if timeout_reason:
            try:
                # 10分間のタイムアウト
                timeout_duration = datetime.timedelta(minutes=10)
                await message.author.timeout(timeout_duration, reason=timeout_reason)
                await message.channel.send(f"🚨 {message.author.mention} がスパム行為（{timeout_reason}）によりタイムアウトされました。")
                
                # リセット
                user_tracker["content_count"] = 0
                user_tracker["everyone_count"] = 0
                return # スパムなら以降の処理をしない
            except Exception as e:
                print(f"[ERROR] Timeout failed for {message.author.display_name}: {e}")

    # 1. 通貨報酬の判定 (廃止済み)
    # 2. TC経験値の判定
    # カテゴリーのチェック (部分一致・大文字小文字無視)
    in_correct_category = is_xp_enabled(message.channel)

    if in_correct_category:
        last_xp_time = bot.tc_xp_cooldowns.get(user_id)
        if not last_xp_time or (now - last_xp_time).total_seconds() > TC_XP_COOLDOWN:
            category_name = message.channel.category.name if message.channel.category else "なし"
            print(f"[DEBUG] TC XP Awarding: {message.author.display_name} in {category_name}")
            new_lv = await database.add_xp(user_id, TC_XP_REWARD, "tc")
            bot.tc_xp_cooldowns[user_id] = now
            if new_lv:
                lv_channel = bot.get_channel(get_setting("LEVEL_UP_CHANNEL_ID"))
                if lv_channel:
                    await lv_channel.send(f"🎊 {message.author.mention} が **TCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
                if isinstance(message.author, discord.Member):
                    await check_and_assign_level_roles(message.author, "tc", new_lv)
    
    # 3. 自己紹介チャンネルでの発言検知（スレッド自動作成）
    guild = message.guild
    if guild:
        cfg = bot.get_evaluation_config(guild.id)
        if cfg["forum_channel_ids"] and message.channel.id in cfg["self_intro_channel_ids"]:
            human_role = get_role_by_setting(guild, "NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_NAME)
            if human_role and human_role in message.author.roles:
                for forum_id in cfg["forum_channel_ids"]:
                    forum_channel = bot.get_channel(forum_id)
                    if isinstance(forum_channel, discord.ForumChannel):
                        # 重複チェック: アクティブなスレッド名にユーザー名（アカウント名）が含まれているか
                        duplicate = any(message.author.name in thread.name for thread in forum_channel.threads)
                        
                        if not duplicate:
                            period = await database.get_evaluation_period(user_id)
                            if period:
                                start_str = format_evaluation_datetime(period['start_time'])
                                end_str = format_evaluation_datetime(period['end_time'])
                                content_thread = (
                                    f"**対象者:** {message.author.mention}\n"
                                    f"**評価期間:** {start_str} ～ {end_str}\n\n"
                                    f"**自己紹介へのリンク:**\n{message.jump_url}"
                                )
                            else:
                                content_thread = (
                                    f"**対象者:** {message.author.mention}\n"
                                    f"**評価期間:** データが見つかりませんでした。\n\n"
                                    f"**自己紹介へのリンク:**\n{message.jump_url}"
                                )
                                
                            thread_name = f"{message.author.display_name}_{message.author.name}"
                            try:
                                await forum_channel.create_thread(
                                    name=thread_name,
                                    content=content_thread,
                                    reason=f"Auto created evaluation thread for {message.author.display_name}"
                                )
                                print(f"[Evaluation Thread] Created for {message.author.display_name} in forum {forum_id}")
                            except Exception as e:
                                print(f"[ERROR] Failed to create forum thread in forum {forum_id}: {e}")
    
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
                await send_log(guild, "vc_join_leave", embed)
    except Exception as log_e:
        print(f"[ERROR] Failed to send VC log: {log_e}")

    try:
        if member.bot: return
        user_id = member.id
        now_naive = database.get_now_naive()
        now_aware = datetime.datetime.now(JST)

        # 評価時間対象カテゴリーの滞在時間追跡
        eval_cat_id = get_setting("EVAL_TIME_CATEGORY_ID")
        was_in_eval = before.channel and before.channel.category and before.channel.category.id == eval_cat_id
        is_in_eval = after.channel and after.channel.category and after.channel.category.id == eval_cat_id

        # 評価対象カテゴリーから退出・移動した時、滞在時間を加算
        if was_in_eval and not is_in_eval:
            join_time = bot.eval_vc_sessions.pop(user_id, None)
            if join_time:
                elapsed_seconds = int((now_aware - join_time).total_seconds())
                if elapsed_seconds > 0:
                    await database.add_evaluation_vc_time(user_id, elapsed_seconds)
                    print(f"[Eval Time] Added {elapsed_seconds}s to {member.display_name}")

        # 評価対象カテゴリーに参加・移動した時、セッション開始
        if is_in_eval and not was_in_eval:
            bot.eval_vc_sessions[user_id] = now_aware
            print(f"[Eval Time] Started session for {member.display_name}")

        # 1. VCから退出・移動した時 (先に処理してXPを付与し、セッションをクリーンアップ)
        if before.channel is not None and (after.channel is None or before.channel.id != after.channel.id):

            join_time = bot.vc_sessions.pop(user_id, None)
            if join_time:
                duration_minutes = int((now_aware - join_time).total_seconds() / 60)
                if duration_minutes > 0:
                    xp_reward = duration_minutes * VC_XP_PER_MIN
                    new_lv = await database.add_xp(user_id, xp_reward, "vc")
                    if new_lv:
                        lv_channel = bot.get_channel(get_setting("LEVEL_UP_CHANNEL_ID"))
                        if lv_channel:
                            await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
                        await check_and_assign_level_roles(member, "vc", new_lv)

            # 退出した部屋が無人になった場合
            if len(before.channel.members) == 0:
                room_data = await database.get_room(before.channel.id)
                if room_data:
                    if room_data["room_type"] in ["一時部屋", "宿"]:
                        try:
                            print(f"[Auto-VC] Deleting empty room: {before.channel.name}")
                            await before.channel.delete()
                            await database.remove_room(before.channel.id)
                        except Exception as del_e:
                            print(f"[Auto-VC] Delete error: {del_e}")
                    elif room_data["room_type"] == "カスタムVC":
                        bot.empty_custom_vcs[before.channel.id] = now_aware

        # 2. VCに参加・移動した時 (後に処理して新しいセッションを開始)
        if after.channel is not None:
            is_join = before.channel is None or before.channel.id != after.channel.id
            if is_join:
                # カテゴリーのチェックを満たす場合のみセッション開始
                in_correct_category = is_xp_enabled(after.channel)

                if in_correct_category:
                    print(f"[VC XP] Started session for {member.display_name}")
                    bot.vc_sessions[user_id] = now_aware

            if after.channel.id in bot.auto_vc_triggers:
                trigger_id = after.channel.id
                try:
                    pool = await database.get_pool()
                    async with pool.acquire() as conn:
                        existing_room = await conn.fetchrow('SELECT channel_id FROM rooms WHERE owner_id = $1 AND room_type = $2', member.id, "一時部屋")

                    if existing_room:
                        existing_channel = bot.get_channel(existing_room["channel_id"])
                        if not existing_channel:
                            try: existing_channel = await bot.fetch_channel(existing_room["channel_id"])
                            except: pass

                        if existing_channel:
                            await asyncio.sleep(0.3)
                            if member.voice and member.voice.channel and member.voice.channel.id == trigger_id:
                                await member.move_to(existing_channel)
                            return
                        else:
                            await database.remove_room(existing_room["channel_id"])

                    guild = member.guild
                    category = after.channel.category

                    channel_name = f"🔊│{member.display_name}の部屋"

                    # バックアップチェック: DBにはないが、既に同名のチャンネルがカテゴリ内にある場合
                    if category:
                        for existing_ch in category.voice_channels:
                            if existing_ch.name == channel_name:
                                now_naive_vc = database.get_now_naive()
                                far_future = now_naive_vc + datetime.timedelta(days=36500)
                                await database.add_room(existing_ch.id, member.id, "一時部屋", far_future)
                                await asyncio.sleep(0.3)
                                if member.voice and member.voice.channel and member.voice.channel.id == trigger_id:
                                    await member.move_to(existing_ch)
                                return
                    new_channel = await guild.create_voice_channel(
                        name=channel_name,
                        category=category,
                        reason=f"Auto-VC for {member.display_name}"
                    )

                    # 確実にDBに保存されるのを待つ
                    now_naive_vc = database.get_now_naive()
                    far_future = now_naive_vc + datetime.timedelta(days=36500)
                    await database.add_room(new_channel.id, member.id, "一時部屋", far_future)
                    print(f"[Auto-VC] Created room {new_channel.id} and registered in DB")

                    # 部屋の設定パネルを送信
                    embed = discord.Embed(
                        title="⚙️ 部屋の設定",
                        description="このボタンから部屋の名前や人数制限を変更できます。",
                        color=discord.Color.blue()
                    )
                    await new_channel.send(embed=embed, view=VCRenamePanelView())

                    # ユーザーを移動 (複数回試行)
                    for i in range(3):
                        await asyncio.sleep(0.5 if i == 0 else 1.0)
                        if member.voice and member.voice.channel and member.voice.channel.id == trigger_id:
                            try:
                                await member.move_to(new_channel)
                                print(f"[Auto-VC] Successfully moved {member.display_name} on attempt {i+1}")
                                break
                            except Exception as move_e:
                                print(f"[Auto-VC] Move attempt {i+1} failed: {move_e}")
                        else:
                            print(f"[Auto-VC] User already left the trigger channel.")
                            break
                except Exception as e:
                    print(f"[Auto-VC] Error: {e}")

            # カスタムVCへの入室であれば、無人タイマーを解除
            bot.empty_custom_vcs.pop(after.channel.id, None)
    except Exception as global_e:
        print(f"CRITICAL ERROR in on_voice_state_update: {global_e}")

@bot.event
async def on_guild_channel_delete(channel):
    # 手動でチャンネルが削除された場合、データベースからも消去する
    room_data = await database.get_room(channel.id)
    if room_data:
        await database.remove_room(channel.id)
        bot.empty_custom_vcs.pop(channel.id, None)
    
    # お問い合わせパネルが削除された場合、データベースから削除する
    await database.remove_inquiry_panel(channel.id)

    # 匿名チャット設定が削除された場合、データベースから削除する
    await database.remove_anonymous_chat(channel.id)
    
    # カスタムチケットパネルが削除された場合、データベースから削除する
    await database.remove_custom_ticket_panel(channel.id)

    # 評価設定のチャンネル削除ハンドラ
    if channel.guild:
        cfg = bot.get_evaluation_config(channel.guild.id)
        changed = False
        if channel.id in cfg["forum_channel_ids"]:
            cfg["forum_channel_ids"].discard(channel.id)
            changed = True
        if channel.id in cfg["self_intro_channel_ids"]:
            cfg["self_intro_channel_ids"].discard(channel.id)
            changed = True
        if changed:
            await database.set_evaluation_settings(channel.guild.id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
            
@bot.event
async def on_member_update(before, after):
    human_role = get_role_by_setting(after.guild, "NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_NAME)
    if human_role and human_role in after.roles and human_role not in before.roles:
        existing = await database.get_evaluation_period(after.id)
        if not existing:
            now = datetime.datetime.now(JST)
            if 23 <= now.hour <= 23:
                start_time = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                start_time = now + datetime.timedelta(minutes=5)
            
            end_time = start_time + datetime.timedelta(days=14)
            await database.add_evaluation_period(after.id, start_time, end_time)
            print(f"[Evaluation] Started for {after.display_name}: {start_time} to {end_time}")

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot:
        return
    if before.content == after.content:
        return
    
    guild = before.guild
    if not guild:
        return
    
    embed = discord.Embed(
        title="📝 メッセージ編集",
        color=discord.Color.orange(),
        timestamp=datetime.datetime.now(JST)
    )
    embed.set_author(name=f"{before.author} (ID: {before.author.id})", icon_url=before.author.display_avatar.url)
    embed.add_field(name="チャンネル", value=before.channel.mention, inline=True)
    embed.add_field(name="メッセージID", value=before.id, inline=True)
    
    before_content = before.content or "*メッセージ内容なし*"
    after_content = after.content or "*メッセージ内容なし*"
    
    if len(before_content) > 1024:
        before_content = before_content[:1020] + "..."
    if len(after_content) > 1024:
        after_content = after_content[:1020] + "..."
        
    embed.add_field(name="変更前", value=before_content, inline=False)
    embed.add_field(name="変更後", value=after_content, inline=False)
    embed.set_footer(text=f"編集者: {before.author.display_name}")
    
    await send_log(guild, "message_edit", embed)

@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot:
        return
        
    guild = message.guild
    if not guild:
        return
        
    embed = discord.Embed(
        title="🗑️ メッセージ削除",
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(JST)
    )
    embed.set_author(name=f"{message.author} (ID: {message.author.id})", icon_url=message.author.display_avatar.url)
    embed.add_field(name="チャンネル", value=message.channel.mention, inline=True)
    embed.add_field(name="メッセージID", value=message.id, inline=True)
    
    content = message.content or "*メッセージ内容なし*"
    if len(content) > 1024:
        content = content[:1020] + "..."
    embed.add_field(name="内容", value=content, inline=False)
    
    if message.attachments:
        attachment_urls = "\n".join([att.url for att in message.attachments])
        if len(attachment_urls) > 1024:
            attachment_urls = attachment_urls[:1020] + "..."
        embed.add_field(name="添付ファイル", value=attachment_urls, inline=False)
        
    embed.set_footer(text=f"作成者: {message.author.display_name}")
    
    await send_log(guild, "message_delete", embed)

@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    embed = discord.Embed(
        title="📥 メンバー参加",
        description=f"{member.mention} がサーバーに参加しました。",
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(JST)
    )
    embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
    
    created_at = member.created_at.astimezone(JST)
    embed.add_field(name="アカウント作成日", value=created_at.strftime("%Y/%m/%d %H:%M:%S"), inline=False)
    
    await send_log(guild, "member_join_leave", embed)

@bot.event
async def on_member_remove(member: discord.Member):
    guild = member.guild
    embed = discord.Embed(
        title="📤 メンバー退出",
        description=f"{member.mention} がサーバーから退出しました。",
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(JST)
    )
    embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
    
    if member.joined_at:
        joined_at = member.joined_at.astimezone(JST)
        embed.add_field(name="サーバー参加日", value=joined_at.strftime("%Y/%m/%d %H:%M:%S"), inline=False)
        
    await send_log(guild, "member_join_leave", embed)

# --- 運営権限チェック ---
def is_admin():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild:
            return False
        if has_admin_role(interaction.user):
            return True
        await interaction.response.send_message("このコマンドを実行する権限がありません（運営専用ロールが必要です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)

# --- 一般スラッシュコマンド ---

@bot.tree.command(name="balance", description="自分の所持金を確認します（管理者は他のユーザーも確認可能）")
async def balance(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    if target_user != interaction.user and not has_admin_role(interaction.user):
        await interaction.response.send_message("他人の残高を確認する権限がありません。", ephemeral=True)
        return
    bal = await database.get_balance(target_user.id)
    if target_user == interaction.user:
        await interaction.response.send_message(f"あなたの所持金は **{bal} {CURRENCY_NAME}** です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"{target_user.display_name} の所持金は **{bal} {CURRENCY_NAME}** です。", ephemeral=True)

@bot.tree.command(name="pay", description="他のユーザーに通貨を送ります（最大10人まで同時選択可能）")
@app_commands.describe(
    target1="送金先1",
    amount="1人あたりの金額",
    target2="送金先2（任意）",
    target3="送金先3（任意）",
    target4="送金先4（任意）",
    target5="送金先5（任意）",
    target6="送金先6（任意）",
    target7="送金先7（任意）",
    target8="送金先8（任意）",
    target9="送金先9（任意）",
    target10="送金先10（任意）"
)
async def pay(
    interaction: discord.Interaction, 
    target1: discord.Member, 
    amount: int, 
    target2: discord.Member = None,
    target3: discord.Member = None,
    target4: discord.Member = None,
    target5: discord.Member = None,
    target6: discord.Member = None,
    target7: discord.Member = None,
    target8: discord.Member = None,
    target9: discord.Member = None,
    target10: discord.Member = None
):
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
        return
        
    targets = [t for t in [target1, target2, target3, target4, target5, target6, target7, target8, target9, target10] if t is not None]
    valid_targets = []
    
    for t in targets:
        if t.id == interaction.user.id:
            await interaction.response.send_message("自分自身は送金先に含めることができません。", ephemeral=True)
            return
        if t.bot:
            await interaction.response.send_message("Botは送金先に含めることができません。", ephemeral=True)
            return
        if t not in valid_targets:
            valid_targets.append(t)
            
    total_amount = amount * len(valid_targets)
    
    # defer() でインタラクションを延長（DBアクセスが3秒を超えても Unknown Interaction にならないように）
    await interaction.response.defer()
    success = await database.remove_balance(interaction.user.id, total_amount)
    if not success:
        await interaction.followup.send(f"残高が不足しています。（合計 {total_amount} {CURRENCY_NAME} 必要です）", ephemeral=True)
        return
        
    for t in valid_targets:
        await database.add_balance(t.id, amount)
        await interaction.followup.send(f"{t.mention} に **{amount} {CURRENCY_NAME}** を送金しました！")
        await send_economy_log(
            interaction.guild, 
            "💸 送金・お渡し", 
            f"{interaction.user.mention} が {t.mention} に **{amount} {CURRENCY_NAME}** を送金しました。",
            user=interaction.user
        )

rank_group = app_commands.Group(name="rank", description="ランク（レベル）関連のコマンド")
bot.tree.add_command(rank_group)

rank_top_group = app_commands.Group(name="top", description="ランキング上位を表示します", parent=rank_group)

@rank_top_group.command(name="tc", description="テキストチャット(TC)のランキング上位10名を表示します")
async def rank_top_tc(interaction: discord.Interaction):
    await _show_ranking(interaction, "tc")

@rank_top_group.command(name="vc", description="ボイスチャット(VC)のランキング上位10名を表示します")
async def rank_top_vc(interaction: discord.Interaction):
    await _show_ranking(interaction, "vc")

async def _show_ranking(interaction: discord.Interaction, mode: str):
    await interaction.response.defer()
    try:
        top_users = await database.get_top_users(mode, 10)
        
        embed = discord.Embed(
            title="💬 TCランキング上位10名" if mode == "tc" else "🎙️ VCランキング上位10名",
            color=0x2f3136
        )
        
        desc = ""
        for i, u in enumerate(top_users):
            member = interaction.guild.get_member(u["user_id"])
            name = member.display_name if member else f"不明なユーザー({u['user_id']})"
            desc += f"**{i+1}位** {name} - Lv.{u['level']} ({u['xp']} XP)\n"
            
        if not desc:
            desc = "データがありません。"
            
        embed.description = desc
        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        embed.timestamp = datetime.datetime.now(JST)
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"[ERROR] rank top command: {e}")
        try:
            await interaction.followup.send(f"❌ エラーが発生しました: `{e}`", ephemeral=True)
        except:
            pass

@rank_group.command(name="status", description="自分または他ユーザーのランク（レベル）を表示します")
async def rank(interaction: discord.Interaction, user: discord.Member = None):
    # defer() の前に重い処理を一切入れない
    try:
        await interaction.response.defer()
    except:
        return

    try:
        target_user = user or interaction.user
        user_data = await database.get_user(target_user.id)
        
        tc_xp, tc_lv = user_data["tc_xp"], user_data["tc_level"]
        vc_xp, vc_lv = user_data["vc_xp"], user_data["vc_level"]
        tc_next = database.get_next_level_xp(tc_lv)
        vc_next = database.get_next_level_xp(vc_lv)

        def create_progress_bar(current, total, length=12):
            if total <= 0: total = 100
            pct = min(current / total, 1.0)
            filled = int(pct * length)
            bar = "▰" * filled + "▱" * (length - filled)
            return f"{bar}  **{int(pct*100)}%**"

        # あとどれくらいでレベルアップするか
        tc_needed = tc_next - tc_xp
        tc_est_msgs = -(-tc_needed // TC_XP_REWARD) # 切り上げ計算
        
        vc_needed = vc_next - vc_xp
        vc_est_mins = -(-vc_needed // VC_XP_PER_MIN) # 切り上げ計算

        embed = discord.Embed(
            title=f"✨ {target_user.display_name} のステータス",
            description=f"{target_user.mention} の活動記録です。",
            color=0x2f3136
        )
        
        embed.set_thumbnail(url=target_user.display_avatar.url)

        # TCランク
        tc_value = (
            f"**Level:** `{tc_lv}`\n"
            f"**Next:** `{tc_xp}` / `{tc_next}` XP\n"
            f"{create_progress_bar(tc_xp, tc_next)}\n"
            f"┗ 次のレベルまであと **{tc_needed}** XP\n"
            f"┗ 目安: あと **約{tc_est_msgs}通** のチャット"
        )
        embed.add_field(name="💬 テキスト活動 (TC)", value=tc_value, inline=False)

        # カテゴリー別VC滞在時間の表示
        # 評価時間対象カテゴリーを取得
        eval_time_cat_id = get_setting("EVAL_TIME_CATEGORY_ID")

        current_session_str = ""

        if target_user.voice and target_user.voice.channel:
            vc = target_user.voice.channel
            cat = vc.category
            join_time = bot.vc_sessions.get(target_user.id)
            if join_time:
                now_aware = datetime.datetime.now(JST)
                delta_sec = (now_aware - join_time).total_seconds()
                hours = int(delta_sec // 3600)
                mins = int((delta_sec % 3600) // 60)
                dur_str = f"{hours}時間{mins}分" if hours > 0 else f"{mins}分"
            else:
                dur_str = "0分"

            if cat and cat.id == eval_time_cat_id:
                current_session_str = (
                    f"\n🟢 **現在の滞在先:** {vc.mention} (評価対象)\n"
                    f"　⏱️ 今回の滞在時間: **{dur_str}**"
                )
            elif is_xp_enabled(vc):
                current_session_str = (
                    f"\n🟡 **現在の滞在先:** {vc.mention} (XP対象・評価対象外)\n"
                    f"　⏱️ 今回の滞在時間: **{dur_str}**"
                )
            else:
                current_session_str = (
                    f"\n⚪ **現在の滞在先:** {vc.mention} (XP対象外)\n"
                    f"　⏱️ 今回の滞在時間: **{dur_str}**"
                )

        # VCランク
        vc_value = (
            f"**Level:** `{vc_lv}`\n"
            f"**Next:** `{vc_xp}` / `{vc_next}` XP\n"
            f"{create_progress_bar(vc_xp, vc_next)}\n"
            f"┗ 次のレベルまであと **{vc_needed}** XP\n"
            f"┗ 目安: あと **約{vc_est_mins}分** の滞在"
            f"{current_session_str}"
        )
        embed.add_field(name="🎙️ ボイス活動 (VC)", value=vc_value, inline=False)

        # 評価浮上時間
        eval_time_sec = user_data.get("evaluation_vc_time", 0)
        join_time = bot.eval_vc_sessions.get(target_user.id)
        if join_time:
            now_aware = datetime.datetime.now(JST)
            current_sec = int((now_aware - join_time).total_seconds())
            if current_sec > 0:
                eval_time_sec += current_sec

        def format_duration(seconds: int) -> str:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if hours > 0:
                return f"{hours}時間{minutes}分"
            return f"{minutes}分"

        embed.add_field(
            name="⏱️ 評価浮上時間",
            value=f"**{format_duration(eval_time_sec)}**",
            inline=False
        )


        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        embed.timestamp = datetime.datetime.now(JST)

        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"[ERROR] rank command: {e}")
        try:
            await interaction.followup.send(f"❌ エラーが発生しました: `{e}`", ephemeral=True)
        except:
            pass

# --- VCコントロールパネル系 ---

class ExtendInnSelectView(discord.ui.View):
    def __init__(self, is_free: bool):
        super().__init__(timeout=60)
        p12 = ROOM_SETTINGS["宿"][12]["price"]
        p24 = ROOM_SETTINGS["宿"][24]["price"]
        self.twelve.label = f"12時間 ({p12:,} {CURRENCY_NAME})"
        self.twenty_four.label = f"24時間 ({p24:,} {CURRENCY_NAME})"
        if is_free:
            self.twelve.label = "12時間 (無料)"
            self.twenty_four.label = "24時間 (無料)"
            
    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success)
    async def twelve(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = ROOM_SETTINGS["宿"][12]["price"]
        await process_room_extension(interaction, "宿", 12, price)
        
    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success)
    async def twenty_four(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = ROOM_SETTINGS["宿"][24]["price"]
        await process_room_extension(interaction, "宿", 24, price)
        
    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class ExtendLuxuryInnSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p12 = ROOM_SETTINGS["高級宿"][12]["price"]
        p24 = ROOM_SETTINGS["高級宿"][24]["price"]
        self.twelve.label = f"12時間 ({p12:,} {CURRENCY_NAME})"
        self.twenty_four.label = f"24時間 ({p24:,} {CURRENCY_NAME})"
        
    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success)
    async def twelve(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = ROOM_SETTINGS["高級宿"][12]["price"]
        await process_room_extension(interaction, "高級宿", 12, price)
        
    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success)
    async def twenty_four(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = ROOM_SETTINGS["高級宿"][24]["price"]
        await process_room_extension(interaction, "高級宿", 24, price)
        
    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

async def process_room_extension(interaction: discord.Interaction, room_type: str, duration: int, price: int):
    await interaction.response.defer(ephemeral=True)
    channel_id = interaction.channel_id
    room_data = await database.get_room(channel_id)
    if not room_data:
        return await interaction.edit_original_response(content="この部屋のデータが見つかりません。", view=None)
        
    if room_data.get("expire_at") is None:
        return await interaction.edit_original_response(content="この部屋は無制限のため延長の必要はありません。", view=None)
        
    if interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
        return await interaction.edit_original_response(content="延長は作成者または管理者のみ可能です。", view=None)

    if await database.get_balance(interaction.user.id) < price:
        return await interaction.edit_original_response(content=f"残高が不足しています！(必要: {price} {CURRENCY_NAME})", view=None)
        
    if price == 0 or await database.remove_balance(interaction.user.id, price):
        new_expire = room_data["expire_at"] + datetime.timedelta(hours=duration)
        await database.extend_room(channel_id, new_expire)
        embed = discord.Embed(
            title="⏱️ 部屋の延長",
            description=f"**{price} {CURRENCY_NAME}** を支払い、部屋の時間を **{duration}時間** 延長しました！\n新しい終了予定時刻: <t:{int(new_expire.timestamp())}:F>",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(content="✅ 延長手続きが完了しました！", view=None)
        await interaction.channel.send(embed=embed)
        if price > 0:
            await send_economy_log(
                interaction.guild,
                "🏨 部屋延長",
                f"{interaction.user.mention} が **{price} {CURRENCY_NAME}** を支払い、部屋 (<#{channel_id}>) を **{duration}時間** 延長しました。",
                user=interaction.user
            )

async def handle_extend(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    room_data = await database.get_room(channel_id)
    if not room_data:
        await interaction.response.send_message("この部屋のデータが見つかりません。", ephemeral=True)
        return
    if room_data.get("expire_at") is None:
        await interaction.response.send_message("この部屋は無制限のため延長の必要はありません。", ephemeral=True)
        return
    if interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("延長は作成者または管理者のみ可能です。", ephemeral=True)
        return
        
    room_type = room_data["room_type"]
    is_free_inn = room_type == "宿" and is_main_or_sub_member(interaction.user)
    
    if room_type == "宿":
        view = ExtendInnSelectView(is_free_inn)
        msg = "「一般宿」の延長期間を選択してください。"
        if is_free_inn:
            msg += "\nあなたは対象ロールのため **無料** で延長可能です。"
        await interaction.response.send_message(msg, view=view, ephemeral=True)
    elif room_type == "高級宿":
        view = ExtendLuxuryInnSelectView()
        await interaction.response.send_message("「高級宿」の延長期間を選択してください。", view=view, ephemeral=True)
    elif room_type == "カスタムVC":
        price = ROOM_SETTINGS["カスタムVC"][24]["price"]
        await process_room_extension(interaction, "カスタムVC", 24, price)

async def handle_delete(interaction: discord.Interaction):
    room_data = await database.get_room(interaction.channel_id)
    if room_data and interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("削除は作成者または管理者のみ可能です。", ephemeral=True)
        return
    await interaction.response.send_message("部屋を削除します...")
    await asyncio.sleep(2)
    try: await interaction.channel.delete()
    except discord.NotFound: pass
    if room_data: await database.remove_room(interaction.channel_id)

class RenameModal(discord.ui.Modal, title='チャンネル名の変更'):
    name_input = discord.ui.TextInput(label='新しいチャンネル名', max_length=100, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.channel.edit(name=self.name_input.value)
            await interaction.response.send_message(f"チャンネル名を「{self.name_input.value}」に変更しました！", ephemeral=True)
        except: await interaction.response.send_message("変更に失敗しました。", ephemeral=True)

class LimitModal(discord.ui.Modal, title='人数制限の設定'):
    limit_input = discord.ui.TextInput(label='人数 (0 で無制限)', max_length=2, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.limit_input.value)
            await interaction.channel.edit(user_limit=limit)
            await interaction.response.send_message(f"人数制限を {limit if limit > 0 else '無制限'} に変更しました！", ephemeral=True)
        except: await interaction.response.send_message("数字を正しく入力してください。", ephemeral=True)

class InnControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="延長", style=discord.ButtonStyle.primary, emoji="⏱", custom_id="inn_extend_btn")
    async def extend_button(self, interaction, button): await handle_extend(interaction)
    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, emoji="🗑", custom_id="inn_delete_btn")
    async def delete_button(self, interaction, button): await handle_delete(interaction)
    @discord.ui.button(label="名前変更", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="inn_rename_btn", row=1)
    async def rename_button(self, interaction, button):
        room_data = await database.get_room(interaction.channel_id)
        if room_data and interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("作成者のみ可能です。", ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal())

class RoomControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="延長", style=discord.ButtonStyle.primary, custom_id="persistent_extend_btn")
    async def extend_button(self, interaction, button): await handle_extend(interaction)
    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, custom_id="persistent_delete_btn")
    async def delete_button(self, interaction, button): await handle_delete(interaction)
    @discord.ui.button(label="名前変更", style=discord.ButtonStyle.secondary, custom_id="persistent_rename_btn", row=1)
    async def rename_button(self, interaction, button): await interaction.response.send_modal(RenameModal())
    @discord.ui.button(label="人数制限", style=discord.ButtonStyle.secondary, custom_id="persistent_limit_btn", row=1)
    async def limit_button(self, interaction, button): await interaction.response.send_modal(LimitModal())

class CustomRoomControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="延長", style=discord.ButtonStyle.primary, custom_id="custom_extend_btn")
    async def extend_button(self, interaction, button): await handle_extend(interaction)
    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, custom_id="custom_delete_btn")
    async def delete_button(self, interaction, button): await handle_delete(interaction)
    @discord.ui.button(label="名前変更", style=discord.ButtonStyle.secondary, custom_id="custom_rename_btn", row=1)
    async def rename_button(self, interaction, button): await interaction.response.send_modal(RenameModal())
    @discord.ui.button(label="人数制限", style=discord.ButtonStyle.secondary, custom_id="custom_limit_btn", row=1)
    async def limit_button(self, interaction, button): await interaction.response.send_modal(LimitModal())

# --- 面接・入界システム ---

class InterviewNicknameModal(discord.ui.Modal, title='入界手続き：名前の設定'):
    name_input = discord.ui.TextInput(label='サーバーでの名前（ニックネーム）', placeholder='例: ヤマダ太郎', max_length=32, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_role = get_role_by_setting(interaction.guild, "NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_NAME)
        pending_role = get_role_by_setting(interaction.guild, "PENDING_MEMBER_ROLE_ID", PENDING_MEMBER_ROLE_NAME)
        if not new_role:
            await interaction.followup.send(f"エラー: ロール「{NEW_MEMBER_ROLE_NAME}」が見つかりません。", ephemeral=True)
            return
        if new_role in interaction.user.roles:
            await interaction.followup.send("既に手続きは完了しています。", ephemeral=True)
            return
        try:
            await interaction.user.edit(nick=self.name_input.value)
            await interaction.user.add_roles(new_role)
            if pending_role and pending_role in interaction.user.roles:
                await interaction.user.remove_roles(pending_role)
            await database.add_balance(interaction.user.id, INITIAL_COINS)
            await database.set_initial_issued(interaction.user.id)
            await interaction.followup.send(f"✅ 完了！名前を「{self.name_input.value}」にし、{INITIAL_COINS} {CURRENCY_NAME} を発行しました。", ephemeral=True)
            await send_economy_log(
                interaction.guild,
                "🆕 初期通貨発行",
                f"{interaction.user.mention} が入界手続きを行い、初期通貨 **{INITIAL_COINS} {CURRENCY_NAME}** を受け取りました。",
                user=interaction.user
            )
        except: await interaction.followup.send("エラー: 権限不足です。Botのロール順位を確認してください。", ephemeral=True)

class InterviewPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="入界手続きを開始", style=discord.ButtonStyle.success, emoji="📝", custom_id="persistent_interview_btn")
    async def start_button(self, interaction, button): await interaction.response.send_modal(InterviewNicknameModal())

class VCRenamePanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    @discord.ui.button(label="VC名を変更", style=discord.ButtonStyle.primary, emoji="📝", custom_id="persistent_vc_rename_panel_btn")
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("ボイスチャンネルに参加していません。", ephemeral=True)
        
        room_data = await database.get_room(interaction.user.voice.channel.id)
        if not room_data or room_data["owner_id"] != interaction.user.id:
            # 管理者なら許可
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("自分が作成した（所有している）部屋ではありません。", ephemeral=True)
        
        await interaction.response.send_modal(RenameModal())

    @discord.ui.button(label="人数制限を変更", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="persistent_vc_limit_panel_btn")
    async def limit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("ボイスチャンネルに参加していません。", ephemeral=True)
        
        room_data = await database.get_room(interaction.user.voice.channel.id)
        if not room_data or room_data["owner_id"] != interaction.user.id:
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("自分が作成した（所有している）部屋ではありません。", ephemeral=True)
        
        await interaction.response.send_modal(LimitModal())

# --- スタンプ依頼システム ---

class EmblemRequestModal(discord.ui.Modal, title='スタンプ制作依頼'):
    details = discord.ui.TextInput(
        label='依頼内容の詳細',
        style=discord.TextStyle.paragraph,
        placeholder='例: 自分のアイコンを使った「了解」スタンプをお願いします！',
        required=True,
        max_length=500
    )

    def __init__(self, target_member):
        super().__init__()
        self.target_member = target_member

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        # チケット番号の決定 (空いている最小の番号を探す)
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith("ticket-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"ticket-{ticket_num:03d}"
        
        # 権限設定
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.target_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # 管理・紋章統括ロールに権限を付与（担当以外の一般の紋章師ロールには権限を付与しない）
        roles_to_overwrite = []
        for role_name in ADMIN_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                roles_to_overwrite.append(role)
        
        manager_role = get_role_by_setting(guild, "EMBLEM_MANAGER_ROLE_ID", EMBLEM_MANAGER_ROLE_NAME)
        if manager_role and manager_role not in roles_to_overwrite:
            roles_to_overwrite.append(manager_role)
            
        for role in roles_to_overwrite:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            # チャンネル作成 (パネルがあるカテゴリに作成)
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Stamp request ticket for {interaction.user.display_name}"
            )
            
            # チケット内での案内メッセージ
            embed = discord.Embed(
                title="🎨 スタンプ制作依頼チケット",
                description=(
                    f"**依頼者:** {interaction.user.mention}\n"
                    f"**担当者:** {self.target_member.mention}\n\n"
                    f"**【依頼内容】**\n{self.details.value}\n\n"
                    "内容の確認や相談はこちらのチャンネルで行ってください。\n"
                    "完了したら下のボタンでチケットを閉じることができます。"
                ),
                color=discord.Color.blue()
            )
            
            # 紋章統括のみをメンション（通知用）
            mentions = [interaction.user.mention, self.target_member.mention]
            manager_role = get_role_by_setting(guild, "EMBLEM_MANAGER_ROLE_ID", EMBLEM_MANAGER_ROLE_NAME)
            if manager_role:
                mentions.append(manager_role.mention)
            
            mention_str = " ".join(mentions)
            await ticket_channel.send(content=mention_str, embed=embed, view=TicketControlView())
            
            await interaction.followup.send(f"✅ チケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class EmblemSelectView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=60)
        # 「紋章師」と「紋章師統括」ロールを持つメンバーを取得
        master_role = get_role_by_setting(guild, "EMBLEM_MASTER_ROLE_ID", EMBLEM_MASTER_ROLE_NAME)
        manager_role = get_role_by_setting(guild, "EMBLEM_MANAGER_ROLE_ID", EMBLEM_MANAGER_ROLE_NAME)
        
        member_set = set()
        if master_role: member_set.update(master_role.members)
        if manager_role: member_set.update(manager_role.members)
        
        options = []
        for member in sorted(member_set, key=lambda m: m.display_name):
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"{member.name}"
            ))
        
        if not options:
            self.add_item(discord.ui.Button(label="現在、依頼可能な製作者がいません", disabled=True))
        else:
            select = discord.ui.Select(
                placeholder="担当する製作者を選択してください...",
                options=options[:25]
            )
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_member = interaction.guild.get_member(user_id)
        if not target_member:
            await interaction.response.send_message("メンバーが見つかりませんでした。", ephemeral=True)
            return
        
        await interaction.response.send_modal(EmblemRequestModal(target_member))

class EmblemRequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="スタンプを依頼する", style=discord.ButtonStyle.primary, emoji="🎨", custom_id="persistent_emblem_req_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EmblemSelectView(interaction.guild)
        await interaction.response.send_message("担当者を選択してください：", view=view, ephemeral=True)


# --- 告解チケットシステム ---

class ConfessionRequestModal(discord.ui.Modal, title='告解・相談依頼'):
    details = discord.ui.TextInput(
        label='依頼内容の詳細',
        style=discord.TextStyle.paragraph,
        placeholder='例: 告解をお願いしたいです。 / ○○について相談したいです。',
        required=True,
        max_length=500
    )

    def __init__(self, target_member):
        super().__init__()
        self.target_member = target_member

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        # チケット番号の決定 (空いている最小の番号を探す)
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith("confess-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"confess-{ticket_num:03d}"
        
        # 権限設定
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.target_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # 管理・告解司祭・司祭系ロールにも権限を付与
        for role_name in ADMIN_ROLE_NAMES + [CONFESSION_PRIEST_ROLE_NAME, PRIEST_ROLE_NAME]:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            # チャンネル作成 (パネルがあるカテゴリに作成)
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Confession ticket for {interaction.user.display_name}"
            )
            
            # チケット内での案内メッセージ
            embed = discord.Embed(
                title="⛪ 告解・相談チケット",
                description=(
                    f"**依頼者:** {interaction.user.mention}\n"
                    f"**担当者:** {self.target_member.mention}\n\n"
                    f"**【相談内容】**\n{self.details.value}\n\n"
                    "内容の確認や相談はこちらのチャンネルで行ってください。\n"
                    "完了したら下のボタンでチケットを閉じることができます。"
                ),
                color=discord.Color.purple()
            )
            
            # 管理・告解司祭・司祭をメンション（通知用）
            mentions = []
            for role_name in ADMIN_ROLE_NAMES + [CONFESSION_PRIEST_ROLE_NAME, PRIEST_ROLE_NAME]:
                role = discord.utils.get(guild.roles, name=role_name)
                if role: mentions.append(role.mention)
            
            mention_str = " ".join(mentions)
            await ticket_channel.send(content=f"{interaction.user.mention} {self.target_member.mention} {mention_str}", embed=embed, view=TicketControlView())
            
            await interaction.followup.send(f"✅ チケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class ConfessionSelectView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=60)
        # 「告解司祭」と「司祭」ロールを持つメンバーを取得
        priest1_role = get_role_by_setting(guild, "CONFESSION_PRIEST_ROLE_ID", CONFESSION_PRIEST_ROLE_NAME)
        priest2_role = get_role_by_setting(guild, "PRIEST_ROLE_ID", PRIEST_ROLE_NAME)
        
        member_set = set()
        if priest1_role: member_set.update(priest1_role.members)
        if priest2_role: member_set.update(priest2_role.members)
        
        options = []
        for member in sorted(member_set, key=lambda m: m.display_name):
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"{member.name}"
            ))
        
        if not options:
            self.add_item(discord.ui.Button(label="現在、対応可能な司祭がいません", disabled=True))
        else:
            select = discord.ui.Select(
                placeholder="担当する司祭を選択してください...",
                options=options[:25]
            )
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_member = interaction.guild.get_member(user_id)
        if not target_member:
            await interaction.response.send_message("メンバーが見つかりませんでした。", ephemeral=True)
            return
        
        await interaction.response.send_modal(ConfessionRequestModal(target_member))

class ConfessionRequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="告解・相談をする", style=discord.ButtonStyle.primary, emoji="⛪", custom_id="persistent_confession_req_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfessionSelectView(interaction.guild)
        await interaction.response.send_message("担当者を選択してください：", view=view, ephemeral=True)



# --- お問い合わせチケットシステム ---

class InquiryRequestModal(discord.ui.Modal, title="お問い合わせ"):
    subject = discord.ui.TextInput(
        label="件名",
        placeholder="例: ○○について質問",
        max_length=100,
        required=True
    )
    details = discord.ui.TextInput(
        label="内容",
        style=discord.TextStyle.paragraph,
        placeholder="お問い合わせ内容の具体的な詳細をご記入ください。",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        # 通知先ロールIDをDBから取得
        role_ids = await database.get_inquiry_panel_roles(interaction.channel.id)
        mention_roles = [guild.get_role(rid) for rid in role_ids]
        mention_roles = [r for r in mention_roles if r is not None]
        
        # チケット番号の決定 (空いている最小の番号を探す)
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith("inquiry-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"inquiry-{ticket_num:03d}"
        
        # 権限設定
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # 管理者ロールと通知先ロールに権限を付与
        for role_name in ADMIN_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        for m_role in mention_roles:
            overwrites[m_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            # チャンネル作成
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Inquiry ticket for {interaction.user.display_name}"
            )
            
            # チケット内での案内メッセージ
            embed = discord.Embed(
                title="✉️ お問い合わせチケット",
                description=(
                    f"**件名:** {self.subject.value}\n\n"
                    f"**内容:**\n{self.details.value}\n\n"
                    f"**作成者:** {interaction.user.mention}\n\n"
                    "内容の確認はこちらのチャンネルで行ってください。\n"
                    "完了したら下のボタンでチケットを閉じることができます。"
                ),
                color=discord.Color.blue()
            )
            
            mention_str = f"{interaction.user.mention}"
            if mention_roles:
                mention_str += " " + " ".join([r.mention for r in mention_roles])
            else:
                mentions = []
                for role_name in ADMIN_ROLE_NAMES:
                    role = discord.utils.get(guild.roles, name=role_name)
                    if role: mentions.append(role.mention)
                if mentions:
                    mention_str += " " + " ".join(mentions)

            await ticket_channel.send(content=mention_str, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ お問い合わせチケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class InquiryRequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="お問い合わせチケットを作成", style=discord.ButtonStyle.primary, emoji="✉️", custom_id="persistent_inquiry_req_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(InquiryRequestModal())

class InquirySetupRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="通知先（メンション）ロールを選択...",
            min_values=1,
            max_values=10
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        roles = self.values
        channel = interaction.channel
        
        # DBに保存
        await database.add_inquiry_panel(channel.id, [r.id for r in roles])
        
        # チャンネルにお問い合わせボタン付きEmbedを送信
        embed = discord.Embed(
            title="✉️ お問い合わせ窓口",
            description=(
                "お問い合わせやご相談はこちらのボタンからチケットを作成してください。\n\n"
                "ボタンを押すと「件名」と「内容」の入力画面が開きます。"
            ),
            color=discord.Color.blue()
        )
        await channel.send(embed=embed, view=InquiryRequestPanelView())
        
        # 管理者に完了を通知
        mentions_str = ", ".join([r.mention for r in roles])
        await interaction.followup.send(f"✅ お問い合わせパネルを設置し、通知先ロールを {mentions_str} に設定しました。", ephemeral=True)

class InquirySetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(InquirySetupRoleSelect())


# --- カスタムチケットパネルシステム ---

class CustomTicketSetupModal(discord.ui.Modal, title="カスタムチケットパネル設定"):
    panel_title = discord.ui.TextInput(
        label="パネルのタイトル",
        placeholder="例: スタンプ制作 依頼所",
        max_length=100,
        required=True
    )
    panel_description = discord.ui.TextInput(
        label="パネルの説明文",
        style=discord.TextStyle.paragraph,
        placeholder="例: ここからスタンプの制作を依頼できます。\n下のボタンを押して担当者を選択してください。",
        max_length=1000,
        required=True
    )
    button_label = discord.ui.TextInput(
        label="ボタンのテキスト",
        placeholder="例: スタンプを依頼する",
        max_length=20,
        default="チケットを作成する",
        required=True
    )
    button_emoji = discord.ui.TextInput(
        label="ボタンの絵文字 (任意 - 絵文字1つ)",
        placeholder="例: 🎨 / ✉️ / ⛪",
        max_length=10,
        required=False
    )
    ticket_prefix = discord.ui.TextInput(
        label="チケット接頭辞 (チャンネル名の頭につく英数字)",
        placeholder="例: ticket (ticket-001のようになります)",
        max_length=15,
        default="ticket",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        view = CustomTicketMentionRoleSelectView(
            title=self.panel_title.value,
            description=self.panel_description.value,
            button_label=self.button_label.value,
            button_emoji=self.button_emoji.value or None,
            prefix=self.ticket_prefix.value
        )
        
        embed = discord.Embed(
            title="🎫 カスタムチケット設定 (1/2)",
            description="チケット作成時に**通知（メンション）するロール**を選択してください。",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CustomTicketMentionRoleSelectView(discord.ui.View):
    def __init__(self, title, description, button_label, button_emoji, prefix):
        super().__init__(timeout=180)
        self.panel_title = title
        self.panel_description = description
        self.button_label = button_label
        self.button_emoji = button_emoji
        self.ticket_prefix = prefix
        
        self.add_item(CustomTicketMentionRoleSelect())


class CustomTicketMentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="通知先（メンション）ロールを選択...",
            min_values=1,
            max_values=10
        )

    async def callback(self, interaction: discord.Interaction):
        roles = self.values
        mention_role_ids = [r.id for r in roles]
        
        view = CustomTicketTargetRoleSelectView(
            title=self.view.panel_title,
            description=self.view.panel_description,
            button_label=self.view.button_label,
            button_emoji=self.view.button_emoji,
            prefix=self.view.ticket_prefix,
            mention_role_ids=mention_role_ids
        )
        
        embed = discord.Embed(
            title="🎫 カスタムチケット設定 (2/2)",
            description=(
                "**依頼先となる人のロール**を選択してください。\n"
                "ここにロールを設定すると、チケット作成時にそのロールを持つメンバーのリストが選択肢として表示されます。\n"
                "設定しない（誰宛てでもない直接のお問い合わせ）場合は、「設定しない（直接作成）」を押してください。"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)


class CustomTicketTargetRoleSelectView(discord.ui.View):
    def __init__(self, title, description, button_label, button_emoji, prefix, mention_role_ids):
        super().__init__(timeout=180)
        self.panel_title = title
        self.panel_description = description
        self.button_label = button_label
        self.button_emoji = button_emoji
        self.ticket_prefix = prefix
        self.mention_role_ids = mention_role_ids
        
        self.add_item(CustomTicketTargetRoleSelect())

    @discord.ui.button(label="設定しない（直接作成）", style=discord.ButtonStyle.secondary, row=2)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.save_and_send_panel(interaction, target_role_ids=[])

    async def save_and_send_panel(self, interaction: discord.Interaction, target_role_ids: list[int]):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        
        # DBに保存
        await database.add_custom_ticket_panel(
            channel_id=channel.id,
            panel_title=self.panel_title,
            panel_description=self.panel_description,
            button_label=self.button_label,
            button_emoji=self.button_emoji,
            mention_role_ids=self.mention_role_ids,
            target_role_ids=target_role_ids,
            ticket_prefix=self.ticket_prefix
        )
        
        # パネル送信
        embed = discord.Embed(
            title=self.panel_title,
            description=self.panel_description,
            color=discord.Color.blue()
        )
        
        view = CustomTicketPanelView()
        button = view.children[0]
        button.label = self.button_label
        if self.button_emoji:
            button.emoji = self.button_emoji
            
        await channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ カスタムチケットパネルを設置しました！", ephemeral=True)


class CustomTicketTargetRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="依頼先（担当）ロールを選択...",
            min_values=1,
            max_values=10,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        roles = self.values
        target_role_ids = [r.id for r in roles]
        await self.view.save_and_send_panel(interaction, target_role_ids)


class CustomTicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(style=discord.ButtonStyle.primary, custom_id="persistent_custom_ticket_panel_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel = await database.get_custom_ticket_panel(interaction.channel.id)
        if not panel:
            return await interaction.response.send_message("❌ パネルの設定が見つかりません。設定が削除された可能性があります。", ephemeral=True)
            
        guild = interaction.guild
        target_role_ids = panel.get("target_role_ids", [])
        
        if target_role_ids:
            member_set = set()
            for rid in target_role_ids:
                role = guild.get_role(rid)
                if role:
                    member_set.update(role.members)
            
            options = []
            for member in sorted(member_set, key=lambda m: m.display_name):
                options.append(discord.SelectOption(
                    label=member.display_name,
                    value=str(member.id),
                    description=f"{member.name}"
                ))
                
            if not options:
                return await interaction.response.send_message("❌ 現在、対応可能な担当者がいません（指定されたロールを持つメンバーがいません）。", ephemeral=True)
            
            view = CustomTicketSelectView(options, panel)
            await interaction.response.send_message("担当者を選択してください：", view=view, ephemeral=True)
        else:
            modal = CustomTicketRequestModal(target_member=None, panel=panel)
            await interaction.response.send_modal(modal)


class CustomTicketSelectView(discord.ui.View):
    def __init__(self, options, panel):
        super().__init__(timeout=60)
        self.panel = panel
        
        select = discord.ui.Select(
            placeholder="担当者を選択してください...",
            options=options[:25]
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_member = interaction.guild.get_member(user_id)
        if not target_member:
            return await interaction.response.send_message("メンバーが見つかりませんでした。", ephemeral=True)
            
        modal = CustomTicketRequestModal(target_member=target_member, panel=self.panel)
        await interaction.response.send_modal(modal)


class CustomTicketRequestModal(discord.ui.Modal):
    details = discord.ui.TextInput(
        label="ご用件・相談内容の詳細",
        style=discord.TextStyle.paragraph,
        placeholder="内容を詳しく入力してください。",
        required=True,
        max_length=1000
    )

    def __init__(self, target_member, panel):
        title = panel["panel_title"]
        if len(title) > 45:
            title = title[:42] + "..."
        super().__init__(title=title)
        self.target_member = target_member
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        prefix = self.panel.get("ticket_prefix") or "ticket"
        
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith(f"{prefix}-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"{prefix}-{ticket_num:03d}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        if self.target_member:
            overwrites[self.target_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
        for role_name in ADMIN_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
        admin_role_ids = get_setting("ADMIN_ROLE_IDS") or []
        for rid in admin_role_ids:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
        for rid in self.panel.get("mention_role_ids", []):
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
        try:
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Custom ticket ({prefix}) for {interaction.user.display_name}"
            )
            
            title_text = f"🎫 {self.panel['panel_title']} チケット"
            desc_text = f"**作成者:** {interaction.user.mention}\n"
            if self.target_member:
                desc_text += f"**担当者:** {self.target_member.mention}\n"
            desc_text += f"\n**【内容】**\n{self.details.value}\n\n"
            desc_text += "内容の確認や相談はこちらのチャンネルで行ってください。\n"
            desc_text += "完了したら下のボタンでチケットを閉じることができます。"
            
            embed = discord.Embed(
                title=title_text,
                description=desc_text,
                color=discord.Color.blue()
            )
            
            mentions = [interaction.user.mention]
            if self.target_member:
                mentions.append(self.target_member.mention)
                
            for rid in self.panel.get("mention_role_ids", []):
                role = guild.get_role(rid)
                if role:
                    mentions.append(role.mention)
                    
            mention_str = " ".join(mentions)
            
            await ticket_channel.send(content=mention_str, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ チケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを閉じる", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="persistent_close_ticket_btn")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="確認", description="このチケットを閉じてもよろしいですか？", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, view=TicketCloseConfirmView(), ephemeral=True)

class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="閉じる", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("チケットを削除します...")
        await asyncio.sleep(2)
        await interaction.channel.delete()

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", embed=None, view=None)

# --- VC購入システム ---

async def process_room_purchase(interaction: discord.Interaction, room_type: str, duration: int):
    await interaction.response.defer(ephemeral=True)
    owner_id = interaction.user.id
    if room_type in ["宿", "高級宿"] and await database.has_room_type(owner_id, ["宿", "高級宿"]):
        return await interaction.edit_original_response(content="既に「宿」を持っています！(1人1つまで)")
    if room_type == "カスタムVC" and await database.has_room_type(owner_id, ["カスタムVC"]):
        return await interaction.edit_original_response(content="既に「カスタムVC」を持っています！")
    
    if duration == 0:
        price = 0
    else:
        settings = ROOM_SETTINGS[room_type][duration]
        price = settings["price"]

    if price > 0 and await database.get_balance(owner_id) < price:
        return await interaction.edit_original_response(content="残高が不足しています。")
    
    if price == 0 or await database.remove_balance(owner_id, price):
        try:
            if room_type == "高級宿":
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True, manage_permissions=True)
                }
            else:
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(connect=True),
                    interaction.user: discord.PermissionOverwrite(move_members=True)
                }
            channel = await interaction.guild.create_voice_channel(name=f"{room_type}-{interaction.user.display_name}", category=interaction.channel.category, overwrites=overwrites, user_limit=(2 if room_type=="宿" else 0))
            
            if duration == 0:
                expire_at = None
                dur_str = "無制限"
                end_str = "無制限"
            else:
                expire_at = database.get_now_naive() + datetime.timedelta(hours=duration)
                dur_str = f"{duration}時間"
                end_str = f"<t:{int(expire_at.timestamp())}:F>"
                
            await database.add_room(channel.id, owner_id, room_type, expire_at)
            await interaction.edit_original_response(content=f"✅ {channel.mention} を作成しました！", view=None)
            view = CustomRoomControlView() if room_type=="カスタムVC" else (RoomControlView() if room_type=="高級宿" else InnControlView())
            embed = discord.Embed(title=f"🏠 {room_type}", description=f"作成者: {interaction.user.mention}\n利用期間: {dur_str}\n終了予定: {end_str}", color=discord.Color.blue())
            await channel.send(content=f"{interaction.user.mention}", embed=embed, view=view)
            if price > 0:
                await send_economy_log(
                    interaction.guild,
                    "🏨 部屋作成",
                    f"{interaction.user.mention} が **{price} {CURRENCY_NAME}** を支払い、部屋 ({channel.mention}) を作成しました。",
                    user=interaction.user
                )
        except Exception as e:
            if price > 0:
                await database.add_balance(owner_id, price)
            await interaction.edit_original_response(content=f"エラー: {e}")

class TempInnDurationSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p12 = ROOM_SETTINGS["宿"][12]["price"]
        p24 = ROOM_SETTINGS["宿"][24]["price"]
        self.twelve_hours.label = f"12時間 ({p12:,} {CURRENCY_NAME})"
        self.twenty_four_hours.label = f"24時間 ({p24:,} {CURRENCY_NAME})"

    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success, emoji="🛖")
    async def twelve_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "宿", 12)

    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success, emoji="🛖")
    async def twenty_four_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "宿", 24)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class LuxuryInnDurationSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p12 = ROOM_SETTINGS["高級宿"][12]["price"]
        p24 = ROOM_SETTINGS["高級宿"][24]["price"]
        self.twelve_hours.label = f"12時間 ({p12:,} {CURRENCY_NAME})"
        self.twenty_four_hours.label = f"24時間 ({p24:,} {CURRENCY_NAME})"

    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success, emoji="🏰")
    async def twelve_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "高級宿", 12)

    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success, emoji="🏰")
    async def twenty_four_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "高級宿", 24)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class CustomRoomConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p24 = ROOM_SETTINGS["カスタムVC"][24]["price"]
        self.confirm.label = f"確定 (24時間 / {p24:,} {CURRENCY_NAME})"

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "カスタムVC", 24)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class MainInnConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="作成する", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "宿", 0)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class MainInnPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="一般宿を作成 (無料・無制限)", style=discord.ButtonStyle.primary, emoji="🛖", custom_id="persistent_inn_main_btn")
    async def inn_main(self, it, btn):
        if not is_main_or_sub_member(it.user):
            return await it.response.send_message("このパネルは対象ロール(本・準メンバー)をお持ちの方のみ利用可能です。仮メンバーの方は有料の一般宿をご利用ください。", ephemeral=True)
        await it.response.send_message("「一般宿」を無料・時間無制限で作成しますか？", view=MainInnConfirmView(), ephemeral=True)

class TempInnPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="一般宿を作成 (有料)", style=discord.ButtonStyle.primary, emoji="🛖", custom_id="persistent_inn_temp_btn")
    async def inn_temp(self, it, btn):
        if is_main_or_sub_member(it.user):
            return await it.response.send_message("あなたは対象ロール(本・準メンバー)をお持ちのため、専用の無料パネルをご利用ください。", ephemeral=True)
        await it.response.send_message("「一般宿」の利用期間を選択してください。", view=TempInnDurationSelectView(), ephemeral=True)

class LuxuryInnPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="高級宿を作成", style=discord.ButtonStyle.primary, emoji="🏰", custom_id="persistent_luxury_inn_panel_btn")
    async def luxury(self, it, btn):
        await it.response.send_message("「高級宿」の利用期間を選択してください。", view=LuxuryInnDurationSelectView(), ephemeral=True)

class CustomRoomView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="カスタムVCを作成", style=discord.ButtonStyle.primary, emoji="✨", custom_id="persistent_custom_room_btn")
    async def custom(self, it, btn):
        await it.response.send_message("「カスタムVC」を購入しますか？", view=CustomRoomConfirmView(), ephemeral=True)

# --- ギャンブル システム ---

class ChinchiroBetModal(discord.ui.Modal, title='チンチロリン：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000: return await interaction.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(JST)
            today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str); count = 0
            if count >= 10: return await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
            if await database.get_balance(interaction.user.id) < bet: return await interaction.followup.send("残高不足です。", ephemeral=True)
            await database.remove_balance(interaction.user.id, bet)
            await database.increment_gambling_count(interaction.user.id)
            view = ChinchiroGameView(interaction.user, bet)
            await interaction.followup.send(f"🎲 **チンチロリン開始！** (本日 {count+1}/10回目)\n賭け金: **{bet} {CURRENCY_NAME}**", view=view, ephemeral=True)
        except: await interaction.response.send_message("数字を入力してください。", ephemeral=True)

class ChinchiroGameView(discord.ui.View):
    def __init__(self, user, bet): super().__init__(timeout=60); self.user, self.bet = user, bet
    @discord.ui.button(label="🎲 サイコロを振る！", style=discord.ButtonStyle.success)
    async def roll(self, interaction, button):
        if interaction.user != self.user: return
        def get_rank(d):
            d.sort()
            if d == [1,1,1]: return "ピンゾロ", 1000
            if d[0]==d[1]==d[2]: return f"アラシ({d[0]})", 900+d[0]
            if d == [4,5,6]: return "シゴロ", 800
            if d == [1,2,3]: return "ヒフミ", -100
            if d[0]==d[1]: return f"出目{d[2]}", 100+d[2]
            if d[1]==d[2]: return f"出目{d[0]}", 100+d[0]
            if d[0]==d[2]: return f"出目{d[1]}", 100+d[1]
            return "役なし", 0
        bd, pd = [random.randint(1,6) for _ in range(3)], [random.randint(1,6) for _ in range(3)]
        bh, br = get_rank(bd); ph, pr = get_rank(pd)
        if pr > br:
            mul = 9 if ph=="ピンゾロ" else (4 if "アラシ" in ph else (2 if ph=="シゴロ" else (1 if "出目" in ph else 0)))
            await database.add_balance(self.user.id, int(self.bet*(1+mul))); await send_economy_log(interaction.guild, "🎲 カジノ(チンチロ)", f"{self.user.mention} がチンチロで {int(self.bet*mul)} {CURRENCY_NAME} 獲得しました。", user=self.user)
            res, color = f"🏆 勝ち！ {int(self.bet*mul)} {CURRENCY_NAME} 獲得", discord.Color.gold()
        elif pr < br: res, color = "💀 負け…", discord.Color.red()
        else: await database.add_balance(self.user.id, self.bet); await send_economy_log(interaction.guild, "🎲 カジノ(チンチロ)", f"{self.user.mention} がチンチロで引き分け、{self.bet} {CURRENCY_NAME} 返還されました。", user=self.user); res, color = "🤝 引き分け", discord.Color.light_grey()
        embed = discord.Embed(title="🎲 チンチロリン結果", color=color)
        embed.add_field(name="🤖 Bot", value=f"{bd} {bh}"); embed.add_field(name="👤 あなた", value=f"{pd} {ph}")
        embed.add_field(name="結果", value=res, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

class ChinchiroView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎲 チンチロリンで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_chinchiro_btn")
    async def play(self, it, btn): await it.response.send_modal(ChinchiroBetModal())

class CoinflipBetModal(discord.ui.Modal, title='コイントス：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, it: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000: return await it.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await it.response.defer(ephemeral=True)
            user_data = await database.get_user(it.user.id)
            now = datetime.datetime.now(JST); today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(it.user.id, today_str); count = 0
            if count >= 10: return await it.followup.send("本日の上限に達しました。", ephemeral=True)
            if await database.get_balance(it.user.id) < bet: return await it.followup.send("残高不足です。", ephemeral=True)
            await it.followup.send(f"🪙 **コイントス！** (本日 {count+1}/10回目)\n「表」か「裏」か？", view=CoinflipGameView(it.user, bet, count), ephemeral=True)
        except: await it.response.send_message("数字を入力してください。", ephemeral=True)

class CoinflipGameView(discord.ui.View):
    def __init__(self, user, bet, count): super().__init__(timeout=60); self.user, self.bet, self.count = user, bet, count
    async def process(self, it, choice):
        if it.user != self.user: return
        if not await database.remove_balance(self.user.id, self.bet): return await it.response.edit_message(content="残高不足", view=None)
        await database.increment_gambling_count(self.user.id)
        res = random.choice(["heads", "tails"])
        if choice == res:
            await database.add_balance(self.user.id, int(self.bet*2.0)); await send_economy_log(interaction.guild, "🎲 カジノ(コイントス)", f"{self.user.mention} がコイントスで {int(self.bet*1.0)} {CURRENCY_NAME} 獲得しました。", user=self.user)
            msg, color = f"🏆 当たり！ {int(self.bet*2.0)} {CURRENCY_NAME} 獲得", discord.Color.gold()
        else: msg, color = f"💀 外れ… {self.bet} {CURRENCY_NAME} 没収", discord.Color.red()
        await it.response.edit_message(content=None, embed=discord.Embed(title="🪙 結果", description=f"結果: {'表' if res=='heads' else '裏'}\n{msg}", color=color), view=None)
    @discord.ui.button(label="表", emoji="⚪")
    async def heads(self, it, btn): await self.process(it, "heads")
    @discord.ui.button(label="裏", emoji="⚫")
    async def tails(self, it, btn): await self.process(it, "tails")

class CoinflipView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🪙 コイントスで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_coinflip_btn")
    async def play(self, it, btn): await it.response.send_modal(CoinflipBetModal())

class SlotBetModal(discord.ui.Modal, title='スロット：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, it: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000: return await it.response.send_message("不正な金額です。", ephemeral=True)
            await it.response.defer(ephemeral=True)
            user_data = await database.get_user(it.user.id)
            now = datetime.datetime.now(JST); today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(it.user.id, today_str); count = 0
            if count >= 10: return await it.followup.send("回数制限です。", ephemeral=True)
            if not await database.remove_balance(it.user.id, bet): return await it.followup.send("残高不足です。", ephemeral=True)
            await database.increment_gambling_count(it.user.id)
            emo = ["🍒", "🍋", "🍉", "🔔", "⭐", "7️⃣", "💎", "🍀"]
            r = [random.choice(emo) for _ in range(3)]
            mul = 10 if r[0]==r[1]==r[2]=="7️⃣" else (5 if r[0]==r[1]==r[2]=="⭐" else (3 if r[0]==r[1]==r[2] else (1.5 if len(set(r))<3 else 0)))
            win = int(bet * mul)
            if win > 0:
                await database.add_balance(it.user.id, win)
                await send_economy_log(it.guild, "🎲 カジノ(スロット)", f"{it.user.mention} がスロットで {win} {CURRENCY_NAME} 獲得しました。", user=it.user)
            embed = discord.Embed(title="🎰 スロット結果", description=f"{r}\n{'🏆 当たり！' if win>0 else '💀 ハズレ'} {win} 獲得", color=discord.Color.gold() if win>0 else discord.Color.red())
            await it.followup.send(embed=embed, ephemeral=True)
        except: await it.response.send_message("エラー", ephemeral=True)

class SlotView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎰 スロットで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_slot_btn")
    async def play(self, it, btn): await it.response.send_modal(SlotBetModal())

def create_blackjack_deck():
    suits = ["♠️", "♥️", "♦️", "♣️"]
    values = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    deck = [{"suit": suit, "value": val} for suit in suits for val in values]
    random.shuffle(deck)
    return deck

def calculate_blackjack_score(hand):
    score = 0
    aces = 0
    for card in hand:
        val = card["value"]
        if val in ["J", "Q", "K"]:
            score += 10
        elif val == "A":
            score += 11
            aces += 1
        else:
            score += int(val)
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

class BlackjackBetModal(discord.ui.Modal, title='ブラックジャック：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000:
                return await interaction.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(JST)
            today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str); count = 0
            if count >= 10:
                return await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
            if await database.get_balance(interaction.user.id) < bet:
                return await interaction.followup.send("残高不足です。", ephemeral=True)
            
            await database.remove_balance(interaction.user.id, bet)
            await database.increment_gambling_count(interaction.user.id)
            
            view = BlackjackGameView(interaction.user, bet)
            initial_blackjack_embed = await view.check_initial_blackjack()
            if initial_blackjack_embed:
                await interaction.followup.send(f"🃏 **ブラックジャック開始！** (本日 {count+1}/10回目)\n賭け金: **{bet} {CURRENCY_NAME}**", embed=initial_blackjack_embed, ephemeral=True)
            else:
                embed = view.build_embed(description="カードが配られました。どうしますか？")
                msg = await interaction.followup.send(f"🃏 **ブラックジャック開始！** (本日 {count+1}/10回目)\n賭け金: **{bet} {CURRENCY_NAME}**", embed=embed, view=view, ephemeral=True)
                view.message = msg
        except ValueError:
            try:
                await interaction.followup.send("金額は半角数字で入力してください。", ephemeral=True)
            except Exception:
                await interaction.response.send_message("金額は半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] BlackjackBetModal: {e}")
            try:
                await interaction.followup.send("エラーが発生しました。", ephemeral=True)
            except Exception:
                await interaction.response.send_message("エラーが発生しました。", ephemeral=True)

class BlackjackGameView(discord.ui.View):
    def __init__(self, user, bet):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet
        self.deck = create_blackjack_deck()
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.message = None

    def format_hand(self, hand, hide_second=False):
        if hide_second:
            return f"{hand[0]['suit']} **{hand[0]['value']}**,  ❓ **?**"
        return ", ".join(f"{card['suit']} **{card['value']}**" for card in hand)

    def get_visible_score(self, hand, hide_second=False):
        if hide_second:
            return calculate_blackjack_score([hand[0]])
        return calculate_blackjack_score(hand)

    def build_embed(self, title="🃏 ブラックジャック", color=0x3498db, description="", is_final=False):
        embed = discord.Embed(title=title, color=color, description=description)
        
        dealer_cards = self.format_hand(self.dealer_hand, hide_second=not is_final)
        dealer_score = self.get_visible_score(self.dealer_hand, hide_second=not is_final)
        embed.add_field(
            name=f"🤖 ディーラー (Score: {dealer_score}{' + ?' if not is_final else ''})",
            value=dealer_cards,
            inline=False
        )
        
        player_cards = self.format_hand(self.player_hand)
        player_score = calculate_blackjack_score(self.player_hand)
        embed.add_field(
            name=f"👤 あなた (Score: {player_score})",
            value=player_cards,
            inline=False
        )
        return embed

    async def check_initial_blackjack(self):
        player_score = calculate_blackjack_score(self.player_hand)
        if player_score == 21:
            dealer_score = calculate_blackjack_score(self.dealer_hand)
            if dealer_score == 21:
                win_amount = self.bet
                await database.add_balance(self.user.id, win_amount)
                title = "🤝 引き分け"
                color = discord.Color.light_grey()
                description = f"双方ブラックジャック！引き分け（プッシュ）です。\n**{win_amount} {CURRENCY_NAME}** が戻ります。"
            else:
                win_amount = int(self.bet * 2.5)
                await database.add_balance(self.user.id, win_amount)
                title = "🃏 ブラックジャック！"
                color = discord.Color.gold()
                description = f"ブラックジャック達成！\n**{win_amount} {CURRENCY_NAME}** 獲得！"
            return self.build_embed(title=title, color=color, description=description, is_final=True)
        return None

    async def on_timeout(self):
        for child in self.children:
            if not child.disabled:
                break
        else:
            return
        await self.resolve_stand(None)

    @discord.ui.button(label="カードを引く (Hit)", style=discord.ButtonStyle.success, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        
        self.player_hand.append(self.deck.pop())
        score = calculate_blackjack_score(self.player_hand)
        
        if score > 21:
            await self.resolve_bust(interaction)
        elif score == 21:
            await self.resolve_stand(interaction)
        else:
            embed = self.build_embed(description="どうしますか？")
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="勝負する (Stand)", style=discord.ButtonStyle.danger, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        
        await self.resolve_stand(interaction)

    async def resolve_bust(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        embed = self.build_embed(
            title="💀 バスト！",
            color=discord.Color.red(),
            description=f"合計が21を超えました！\n**{self.bet} {CURRENCY_NAME}** 没収...",
            is_final=True
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def resolve_stand(self, interaction: discord.Interaction = None):
        for child in self.children:
            child.disabled = True
            
        player_score = calculate_blackjack_score(self.player_hand)
        while calculate_blackjack_score(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
            
        dealer_score = calculate_blackjack_score(self.dealer_hand)
        
        win_amount = 0
        if dealer_score > 21:
            win_amount = self.bet * 2
            title = "🏆 勝ち！"
            color = discord.Color.gold()
            description = f"ディーラーがバストしました！\n**{win_amount} {CURRENCY_NAME}** 獲得！"
        elif player_score > dealer_score:
            win_amount = self.bet * 2
            title = "🏆 勝ち！"
            color = discord.Color.gold()
            description = f"ディーラーを上回りました！\n**{win_amount} {CURRENCY_NAME}** 獲得！"
        elif player_score < dealer_score:
            title = "💀 負け…"
            color = discord.Color.red()
            description = f"ディーラーに敗北しました...\n**{self.bet} {CURRENCY_NAME}** 没収..."
        else:
            win_amount = self.bet
            title = "🤝 引き分け"
            color = discord.Color.light_grey()
            description = f"引き分け（プッシュ）です。\n**{win_amount} {CURRENCY_NAME}** が戻ります。"
            
        if win_amount > 0:
            await database.add_balance(self.user.id, win_amount)
            
        embed = self.build_embed(title=title, color=color, description=description, is_final=True)
        
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass

class BlackjackView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🃏 ブラックジャックで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_blackjack_btn")
    async def play(self, it, btn):
        await it.response.send_modal(BlackjackBetModal())

def check_roulette_win(number, bet_type, target_val=None):
    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    black_numbers = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
    
    if number == 0:
        if bet_type == "number" and target_val == 0:
            return True, 36
        return False, 0

    if bet_type == "red":
        is_win = number in red_numbers
        return is_win, 2 if is_win else 0
    elif bet_type == "black":
        is_win = number in black_numbers
        return is_win, 2 if is_win else 0
    elif bet_type == "even":
        is_win = number % 2 == 0
        return is_win, 2 if is_win else 0
    elif bet_type == "odd":
        is_win = number % 2 != 0
        return is_win, 2 if is_win else 0
    elif bet_type == "low":
        is_win = 1 <= number <= 18
        return is_win, 2 if is_win else 0
    elif bet_type == "high":
        is_win = 19 <= number <= 36
        return is_win, 2 if is_win else 0
    elif bet_type == "dozen1":
        is_win = 1 <= number <= 12
        return is_win, 3 if is_win else 0
    elif bet_type == "dozen2":
        is_win = 13 <= number <= 24
        return is_win, 3 if is_win else 0
    elif bet_type == "dozen3":
        is_win = 25 <= number <= 36
        return is_win, 3 if is_win else 0
    elif bet_type == "number":
        is_win = number == target_val
        return is_win, 36 if is_win else 0
        
    return False, 0

def format_bet_type(bet_type, target_num=None):
    names = {
        "red": "🔴 赤 (Red)",
        "black": "⚫ 黒 (Black)",
        "even": "🔢 偶数 (Even)",
        "odd": "🔣 奇数 (Odd)",
        "low": "⬇️ ロー (Low: 1-18)",
        "high": "⬆️ ハイ (High: 19-36)",
        "dozen1": "1️⃣ 第1ダズン (1-12)",
        "dozen2": "2️⃣ 第2ダズン (13-24)",
        "dozen3": "3️⃣ 第3ダズン (25-36)",
    }
    if bet_type == "number":
        return f"🎯 数字 1点賭け: {target_num}"
    return names.get(bet_type, bet_type)

class RouletteBetModal(discord.ui.Modal, title='ルーレット：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000:
                return await interaction.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(JST)
            today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str)
                count = 0
                
            if count >= 10:
                return await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
                
            if await database.get_balance(interaction.user.id) < bet:
                return await interaction.followup.send("残高不足です。", ephemeral=True)
            
            view = RouletteBetTypeView(interaction.user, bet, count)
            embed = discord.Embed(
                title="🎡 ルーレット",
                description=(
                    f"**現在のベット額**: {bet} {CURRENCY_NAME}\n\n"
                    "賭け先を以下から選択してください。\n"
                    "- 赤 / 黒 / 偶数 / 奇数 / ロー / ハイ: **配当2.0倍**\n"
                    "- ダズン (1-12, 13-24, 25-36): **配当3.0倍**\n"
                    "- 数字1点賭け (0-36): **配当36.0倍**"
                ),
                color=0x3498db
            )
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.message = msg
        except ValueError:
            await interaction.followup.send("金額は半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] RouletteBetModal: {e}")

class RouletteBetTypeView(discord.ui.View):
    def __init__(self, user, bet, count):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet
        self.count = count
        self.message = None
        self.add_item(RouletteTypeSelect())

    @discord.ui.button(label="🎯 数字1点賭け (0-36)", style=discord.ButtonStyle.secondary, row=1)
    async def bet_number_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        await interaction.response.send_modal(RouletteNumberModal(self.bet, self.count, self.message))

class RouletteTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="🔴 赤に賭ける", description="配当 2.0倍", value="red"),
            discord.SelectOption(label="⚫ 黒に賭ける", description="配当 2.0倍", value="black"),
            discord.SelectOption(label="🔢 偶数に賭ける", description="配当 2.0倍 (0は除く)", value="even"),
            discord.SelectOption(label="🔣 奇数に賭ける", description="配当 2.0倍", value="odd"),
            discord.SelectOption(label="⬇️ ローに賭ける (1-18)", description="配当 2.0倍", value="low"),
            discord.SelectOption(label="⬆️ ハイに賭ける (19-36)", description="配当 2.0倍", value="high"),
            discord.SelectOption(label="1️⃣ 第1ダズン (1-12)", description="配当 3.0倍", value="dozen1"),
            discord.SelectOption(label="2️⃣ 第2ダズン (13-24)", description="配当 3.0倍", value="dozen2"),
            discord.SelectOption(label="3️⃣ 第3ダズン (25-36)", description="配当 3.0倍", value="dozen3"),
        ]
        super().__init__(placeholder="賭け先を選択してください...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if interaction.user != view.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        await run_roulette_game(interaction, view.user, view.bet, view.count, self.values[0], None)

class RouletteNumberModal(discord.ui.Modal, title='ルーレット：数字1点賭け'):
    number_input = discord.ui.TextInput(label='賭ける数字 (0〜36)', placeholder='例: 7', max_length=2, required=True)
    def __init__(self, bet, count, game_msg):
        super().__init__()
        self.bet = bet
        self.count = count
        self.game_msg = game_msg

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_num = int(self.number_input.value)
            if target_num < 0 or target_num > 36:
                return await interaction.response.send_message("0から36の間の数字を入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            await run_roulette_game(interaction, interaction.user, self.bet, self.count, "number", target_num)
        except ValueError:
            await interaction.response.send_message("数字は半角で入力してください。", ephemeral=True)

async def run_roulette_game(interaction: discord.Interaction, user, bet, count, bet_type, target_num):
    user_data = await database.get_user(user.id)
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y-%m-%d")
    current_count = user_data.get("chinchiro_count", 0)
    
    if user_data.get("chinchiro_last_date") != today_str:
        await database.reset_gambling_count(user.id, today_str)
        current_count = 0
        
    if current_count >= 10:
        try:
            await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
        except Exception:
            await interaction.response.send_message("本日の上限(10回)に達しました。", ephemeral=True)
        return
        
    if not await database.remove_balance(user.id, bet):
        try:
            await interaction.followup.send("残高不足です。", ephemeral=True)
        except Exception:
            await interaction.response.send_message("残高不足です。", ephemeral=True)
        return
        
    await database.increment_gambling_count(user.id)
    
    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    
    def get_color_emoji(n):
        if n == 0:
            return "🟢0"
        return f"🔴{n}" if n in red_numbers else f"⚫{n}"
        
    spin_sequence = []
    for _ in range(5):
        dummy_num = random.randint(0, 36)
        spin_sequence.append(get_color_emoji(dummy_num))
        
    final_number = random.randint(0, 36)
    
    embed = discord.Embed(
        title="🎡 ルーレット回転中...",
        description=f"賭け先: **{format_bet_type(bet_type, target_num)}**\n賭け金: **{bet} {CURRENCY_NAME}**\n\n"
                    f"spinning: [ {' ➔ '.join(spin_sequence[:3])} ]",
        color=0x3498db
    )
    
    if not interaction.is_expired():
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=None)
    else:
        await interaction.channel.send(embed=embed)
        
    await asyncio.sleep(1.2)
    
    embed.title = "🎡 ルーレット減速中..."
    embed.description = f"賭け先: **{format_bet_type(bet_type, target_num)}**\n賭け金: **{bet} {CURRENCY_NAME}**\n\n" \
                        f"spinning: [ {' ➔ '.join(spin_sequence[2:])} ➔ ??? ]"
    
    await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed)
    
    await asyncio.sleep(1.2)
    
    is_win, multiplier = check_roulette_win(final_number, bet_type, target_num)
    win_amount = int(bet * multiplier) if is_win else 0
    
    if win_amount > 0:
        await database.add_balance(user.id, win_amount)
        
    color_emoji = get_color_emoji(final_number)
    if is_win:
        title = "🏆 当たり！"
        color = discord.Color.gold()
        desc = f"結果: **{color_emoji}**\n賭け先: **{format_bet_type(bet_type, target_num)}**\n\n" \
               f"見事に的中しました！\n**{win_amount} {CURRENCY_NAME}** 獲得！"
    else:
        title = "💀 ハズレ…"
        color = discord.Color.red()
        desc = f"結果: **{color_emoji}**\n賭け先: **{format_bet_type(bet_type, target_num)}**\n\n" \
               f"残念、ハズレです...\n**{bet} {CURRENCY_NAME}** 没収。"
               
    embed = discord.Embed(title=title, description=desc, color=color)
    embed.set_footer(text=f"本日 {current_count+1}/10回目")
    
    await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed)

class RouletteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🎡 ルーレットで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_roulette_btn")
    async def play(self, it, btn):
        await it.response.send_modal(RouletteBetModal())

class PanelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="チンチロリン", description="チンチロリンゲームのパネルを設置します", emoji="🎲", value="chinchiro"),
            discord.SelectOption(label="コイントス", description="コイントスゲームのパネルを設置します", emoji="🪙", value="coinflip"),
            discord.SelectOption(label="スロット", description="スロットゲームのパネルを設置します", emoji="🎰", value="slot"),
            discord.SelectOption(label="ブラックジャック", description="ブラックジャックゲームのパネルを設置します", emoji="🃏", value="blackjack"),
            discord.SelectOption(label="ルーレット", description="ルーレットゲームのパネルを設置します", emoji="🎡", value="roulette"),
            discord.SelectOption(label="一般宿 (本・準メンバー用)", description="本・準メンバー用の無料宿パネルを設置します", emoji="🛖", value="inn_main"),
            discord.SelectOption(label="一般宿 (仮メンバー用)", description="仮メンバー用の有料宿パネルを設置します", emoji="🛖", value="inn_temp"),
            discord.SelectOption(label="高級宿", description="高級宿の購入パネルを設置します", emoji="🏰", value="inn_luxury"),
            discord.SelectOption(label="カスタムVC", description="カスタムVCの作成パネルを設置します", emoji="✨", value="custom_vc"),
            discord.SelectOption(label="スタンプ依頼", description="スタンプ制作依頼のパネルを設置します", emoji="🎨", value="stamp"),
            discord.SelectOption(label="告解・相談室", description="告解・相談依頼のパネルを設置します", emoji="⛪", value="confession"),
            discord.SelectOption(label="VC管理", description="VC名・人数制限変更のパネルを設置します", emoji="⚙️", value="vc_manage"),
            discord.SelectOption(label="入界手続き", description="新規メンバーの入界手続きパネルを設置します", emoji="📝", value="interview"),
            discord.SelectOption(label="お問い合わせ", description="お問い合わせ作成パネルを設置します", emoji="✉️", value="inquiry"),
            discord.SelectOption(label="匿名チャット", description="匿名チャットのパネルを設置します", emoji="💬", value="anonymous_chat"),
            discord.SelectOption(label="カスタムチケット", description="任意のタイトル・説明文・担当ロールを指定したチケットパネルを設置します", emoji="🎫", value="custom_ticket"),
            discord.SelectOption(label="任意ロール", description="任意のロールをリアクションで付与するパネルを設置します", emoji="🎭", value="custom_role_panel")
        ]
        super().__init__(placeholder="設置するパネルを選択してください...", min_values=1, max_values=1, options=options, custom_id="admin_panel_setup_select")

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        channel = interaction.channel
        
        # 権限チェック (一般にこのインタラクションを押せるのは呼び出した本人だけだが念のため)
        if not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            # 面接用パネルだけは面接官ロールでも許可
            if val == "interview":
                user_roles = [r.name for r in interaction.user.roles]
                is_interviewer = any(r in INTERVIEWER_ROLE_NAMES for r in user_roles)
                if not is_interviewer:
                    return await interaction.response.send_message("この操作を実行する権限がありません。", ephemeral=True)
            else:
                return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        if val == "chinchiro":
            embed = discord.Embed(title="🎲 チンチロリン", description="カジノへようこそ！", color=discord.Color.dark_green())
            await channel.send(embed=embed, view=ChinchiroView())
            await interaction.response.send_message("✅ チンチロリンパネルを設置しました。", ephemeral=True)
        elif val == "coinflip":
            embed = discord.Embed(title="🪙 コイントス", description="表か裏か！", color=discord.Color.blue())
            await channel.send(embed=embed, view=CoinflipView())
            await interaction.response.send_message("✅ コイントスパネルを設置しました。", ephemeral=True)
        elif val == "slot":
            embed = discord.Embed(title="🎰 スロット", description="絵柄を揃えろ！", color=discord.Color.orange())
            await channel.send(embed=embed, view=SlotView())
            await interaction.response.send_message("✅ スロットパネルを設置しました。", ephemeral=True)
        elif val == "blackjack":
            embed = discord.Embed(
                title="🃏 ブラックジャック",
                description=(
                    "カジノへようこそ！ディーラーと勝負して21を目指そう！\n\n"
                    "**【基本ルール】**\n"
                    "- 配られたカードの合計値が **21** に近い方が勝利となります。\n"
                    "- 合計値が **21 を超えると敗北 (Bust)** となります。\n\n"
                    "**【カードの数え方】**\n"
                    "- `2`〜`10`: そのままの数字で計算します。\n"
                    "- `J`, `Q`, `K`: すべて `10` として計算します。\n"
                    "- `A`: `1` または `11` の都合が良い方の値で自動計算されます。\n\n"
                    "**【操作方法】**\n"
                    "- **「カードを引く (Hit)」**: 手札にカードを1枚追加します。\n"
                    "- **「勝負する (Stand)」**: 現在の手札でディーラーと勝負します。\n"
                    "- ※ディーラーは手札の合計が **17 以上になるまで** 自動でカードを引き続けます。\n\n"
                    "**【配当と制限】**\n"
                    "- 勝利時: 賭け金の **2.0倍**\n"
                    "- ブラックジャック勝利時 (初期手札で21点): 賭け金の **2.5倍**\n"
                    "- 引き分け時: 賭け金を払い戻し (1.0倍)\n"
                    "- 1プレイあたり **1 〜 100,000 Rune** までベット可能。\n"
                    "- ※他のゲームと共通で1日10回の回数制限があります。"
                ),
                color=discord.Color.dark_purple()
            )
            await channel.send(embed=embed, view=BlackjackView())
            await interaction.response.send_message("✅ ブラックジャックパネルを設置しました。", ephemeral=True)
        elif val == "roulette":
            embed = discord.Embed(
                title="🎡 ルーレット",
                description=(
                    "カジノへようこそ！ルーレットの出目を予想してRuneを増やそう！\n\n"
                    "**【基本ルール】**\n"
                    "- 0〜36の計37個の数字からなるホイールが回転し、ボールが落ちた箇所が当選番号となります。\n\n"
                    "**【賭け方と配当】**\n"
                    "- **2.0倍配当**: 🔴赤 / ⚫黒 / 🔢偶数 / 🔣奇数 / ⬇️ロー (1-18) / ⬆️ハイ (19-36)\n"
                    "- **3.0倍配当**: ダズン (1-12 / 13-24 / 25-36)\n"
                    "- **36.0倍配当**: 🎯数字1点賭け (0〜36の特定の数字)\n\n"
                    "**【注意事項】**\n"
                    "- ※当選番号が `0`（緑色）の場合、数字の0への1点賭けを除き、すべての賭け（赤黒、偶奇など）はハズレとなります。\n"
                    "- 1プレイあたり **1 〜 100,000 Rune** までベット可能。\n"
                    "- ※他のゲームと共通で1日10回の回数制限があります。"
                ),
                color=discord.Color.dark_red()
            )
            await channel.send(embed=embed, view=RouletteView())
            await interaction.response.send_message("✅ ルーレットパネルを設置しました。", ephemeral=True)
        elif val == "inn_main":
            main_sub_roles_str = format_setting_status(interaction.guild, 'MAIN_SUB_MEMBER_ROLE_IDS')
            if "❌" in main_sub_roles_str: 
                main_sub_roles_str = f"「{'」や「'.join(MAIN_SUB_MEMBER_ROLE_NAMES)}」"
            
            embed = discord.Embed(
                title="🏠 一般宿 (本・準メンバー用)", 
                description=f"部屋を無料で借りる（時間無制限）\n※対象ロール {main_sub_roles_str} をお持ちの方専用", 
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=MainInnPanelView())
            await interaction.response.send_message("✅ 宿屋(本・準メンバー用)パネルを設置しました。", ephemeral=True)
        elif val == "inn_temp":
            embed = discord.Embed(
                title="🏠 一般宿 (仮メンバー用)", 
                description="部屋を有料で借りる", 
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=TempInnPanelView())
            await interaction.response.send_message("✅ 宿屋(仮メンバー用)パネルを設置しました。", ephemeral=True)
        elif val == "inn_luxury":
            embed = discord.Embed(
                title="🏰 高級宿", 
                description="高級宿を有料で借りる", 
                color=discord.Color.purple()
            )
            await channel.send(embed=embed, view=LuxuryInnPanelView())
            await interaction.response.send_message("✅ 高級宿パネルを設置しました。", ephemeral=True)
        elif val == "custom_vc":
            embed = discord.Embed(title="✨ カスタムVC", description="自分だけの部屋を作成", color=discord.Color.purple())
            await channel.send(embed=embed, view=CustomRoomView())
            await interaction.response.send_message("✅ カスタムVCパネルを設置しました。", ephemeral=True)
        elif val == "stamp":
            embed = discord.Embed(
                title="スタンプ制作 依頼所",
                description=(
                    "こちらから製作者の方々へスタンプの制作を依頼できます。\n\n"
                    "**【依頼方法】**\n"
                    "1. 下の「スタンプを依頼する」ボタンを押す\n"
                    "2. 制作を依頼したい担当者を選択する\n"
                    "3. 依頼内容の詳細を記入して送信\n\n"
                    "※依頼送信後、担当者から連絡があるまでお待ちください。"
                ),
                color=discord.Color.blue()
            )
            await channel.send(embed=embed, view=EmblemRequestPanelView())
            await interaction.response.send_message("✅ スタンプ依頼パネルを設置しました。", ephemeral=True)
        elif val == "confession":
            embed = discord.Embed(
                title="告解・相談室 依頼所",
                description=(
                    "こちらから司祭の方々へ告解や相談を依頼できます。\n\n"
                    "**【依頼方法】**\n"
                    "1. 下の「告解・相談をする」ボタンを押す\n"
                    "2. 相談したい担当司祭を選択する\n"
                    "3. 相談内容を記入して送信\n\n"
                    "※依頼送信後、担当者から連絡があるまでお待ちください。"
                ),
                color=discord.Color.purple()
            )
            await channel.send(embed=embed, view=ConfessionRequestPanelView())
            await interaction.response.send_message("✅ 告解パネルを設置しました。", ephemeral=True)
        elif val == "vc_manage":
            embed = discord.Embed(
                title="⚙️ VC管理パネル",
                description=(
                    "自分が作成した部屋（一時部屋、カスタムVC、宿など）の設定を変更できます。\n\n"
                    "**1. 設定したいVCに参加する**\n"
                    "**2. 下のボタンを押す**"
                ),
                color=discord.Color.blue()
            )
            await channel.send(embed=embed, view=VCRenamePanelView())
            await interaction.response.send_message("✅ VC管理パネルを設置しました。", ephemeral=True)
        elif val == "interview":
            embed = discord.Embed(title="✨ 入界手続き", description="下のボタンから登録してください。", color=discord.Color.green())
            await channel.send(embed=embed, view=InterviewPanelView())
            await interaction.response.send_message("✅ 入界手続きパネルを設置しました。", ephemeral=True)
        elif val == "inquiry":
            embed = discord.Embed(
                title="✉️ お問い合わせ設定",
                description="お問い合わせの際に通知（メンション）するロールを選択してください。",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, view=InquirySetupView(), ephemeral=True)
        elif val == "anonymous_chat":
            embed = discord.Embed(
                title="💬 匿名チャット設定",
                description=(
                    "匿名チャットの設置設定を行います。\n\n"
                    "**1. パネル（送信ボタン）を設置するテキストチャンネル** を選択してください。\n"
                    "**2. 匿名メッセージが掲載されるテキストチャンネル** を選択してください。"
                ),
                color=discord.Color.purple()
            )
            await interaction.response.send_message(embed=embed, view=AnonymousChatSetupView(), ephemeral=True)
        elif val == "custom_ticket":
            await interaction.response.send_modal(CustomTicketSetupModal())
        elif val == "custom_role_panel":
            await interaction.response.send_modal(CustomRolePanelSetupModal())

# --- VC作成トリガー管理パネル用UI ---

async def update_config_view(interaction: discord.Interaction, bot):
    view = VCTriggersConfigView(bot)
    
    embed = discord.Embed(
        title="🎙️ VC作成トリガー設定パネル",
        description=(
            "ユーザーが参加した際に一時部屋を自動作成するチャンネルを設定できます。\n\n"
            "**【追加】** 下のドロップダウンからボイスチャンネルを選択してください。\n"
            "**【削除】** 登録済みのチャンネルを削除するには、削除用ドロップダウンを使用してください。"
        ),
        color=discord.Color.blue()
    )
    
    triggers_str = ""
    for tid in bot.auto_vc_triggers:
        ch = bot.get_channel(tid)
        if ch:
            triggers_str += f"• {ch.mention} (ID: `{tid}`)\n"
        else:
            triggers_str += f"• ⚠️ 不明なチャンネル (ID: `{tid}`)\n"
    if not triggers_str:
        triggers_str = "登録されているトリガーチャンネルはありません。"
    embed.add_field(name="現在の登録チャンネル", value=triggers_str, inline=False)
    
    await interaction.response.edit_message(embed=embed, view=view)

class AddVCTriggerSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="追加するボイスチャンネルを選択...",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel = self.values[0]
        
        if channel.id in bot.auto_vc_triggers:
            return await interaction.response.send_message(f"❌ {channel.mention} は既に登録されています。", ephemeral=True)
            
        await database.add_auto_vc_trigger(channel.id)
        bot.auto_vc_triggers.add(channel.id)
        
        await update_config_view(interaction, bot)

class RemoveVCTriggerSelect(discord.ui.Select):
    def __init__(self, bot):
        options = []
        for tid in bot.auto_vc_triggers:
            ch = bot.get_channel(tid)
            name = ch.name if ch else f"不明なチャンネル ({tid})"
            options.append(discord.SelectOption(
                label=name,
                value=str(tid),
                description=f"ID: {tid}"
            ))
        super().__init__(
            placeholder="削除するトリガーチャンネルを選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel_id = int(self.values[0])
        
        if channel_id not in bot.auto_vc_triggers:
            return await interaction.response.send_message(f"❌ そのチャンネルは登録されていません。", ephemeral=True)
            
        await database.remove_auto_vc_trigger(channel_id)
        bot.auto_vc_triggers.discard(channel_id)
        
        await update_config_view(interaction, bot)

class VCTriggersConfigView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.add_item(AddVCTriggerSelect())
        if bot.auto_vc_triggers:
            self.add_item(RemoveVCTriggerSelect(bot))

class ManageVCTriggersButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="VC作成トリガーを設定",
            style=discord.ButtonStyle.secondary,
            emoji="🎙️",
            custom_id="persistent_admin_manage_vc_triggers_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        bot = interaction.client
        view = VCTriggersConfigView(bot)
        
        embed = discord.Embed(
            title="🎙️ VC作成トリガー設定パネル",
            description=(
                "ユーザーが参加した際に一時部屋を自動作成するチャンネルを設定できます。\n\n"
                "**【追加】** 下のドロップダウンからボイスチャンネルを選択してください。\n"
                "**【削除】** 登録済みのチャンネルを削除するには、削除用ドロップダウンを使用してください。"
            ),
            color=discord.Color.blue()
        )
        
        triggers_str = ""
        for tid in bot.auto_vc_triggers:
            ch = bot.get_channel(tid)
            if ch:
                triggers_str += f"• {ch.mention} (ID: `{tid}`)\n"
            else:
                triggers_str += f"• ⚠️ 不明なチャンネル (ID: `{tid}`)\n"
        if not triggers_str:
            triggers_str = "登録されているトリガーチャンネルはありません。"
        embed.add_field(name="現在の登録チャンネル", value=triggers_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --- レベルロール設定用UI ---

class LevelTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="💬 テキスト活動 (TC)", value="tc", description="TCレベルに基づく報酬"),
            discord.SelectOption(label="🎙️ ボイス活動 (VC)", value="vc", description="VCレベルに基づく報酬")
        ]
        super().__init__(placeholder="レベルタイプ（TC/VC）を選択...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_level_type = self.values[0]
        await interaction.response.defer()

class LevelRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="付与するロールを選択...", min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_role = self.values[0]
        await interaction.response.defer()

class LevelInputModal(discord.ui.Modal, title='レベルロール設定：レベル入力'):
    level_input = discord.ui.TextInput(label='目標レベル', placeholder='例: 10', max_length=5, required=True)

    def __init__(self, level_type: str, role: discord.Role, parent_view):
        super().__init__()
        self.level_type = level_type
        self.role = role
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(self.level_input.value)
            if level <= 0:
                return await interaction.response.send_message("❌ 1以上のレベルを指定してください。", ephemeral=True)
            
            # 登録処理
            await database.add_level_role_reward(self.level_type, level, self.role.id)
            
            # ビューのリセット
            self.parent_view.selected_role = None
            self.parent_view.selected_level_type = None
            
            # パネル表示を更新
            await update_level_roles_config_view(interaction)
        except ValueError:
            await interaction.response.send_message("❌ レベルは半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] LevelInputModal: {e}")
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True)

class AddLevelRoleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="レベルを指定して追加", style=discord.ButtonStyle.success, emoji="➕", row=2)

    async def callback(self, interaction: discord.Interaction):
        if not getattr(self.view, "selected_level_type", None):
            return await interaction.response.send_message("❌ 先にレベルタイプ（TC/VC）を選択してください。", ephemeral=True)
        if not getattr(self.view, "selected_role", None):
            return await interaction.response.send_message("❌ 先に付与するロールを選択してください。", ephemeral=True)

        modal = LevelInputModal(self.view.selected_level_type, self.view.selected_role, self.view)
        await interaction.response.send_modal(modal)

class RemoveLevelRoleSelect(discord.ui.Select):
    def __init__(self, rewards, guild: discord.Guild):
        options = []
        for r in rewards:
            ltype = "TC" if r["level_type"] == "tc" else "VC"
            role = guild.get_role(r["role_id"])
            role_name = role.name if role else f"不明なロール (ID: {r['role_id']})"
            options.append(discord.SelectOption(
                label=f"[{ltype}] Lv.{r['level']} ➔ {role_name}",
                value=f"{r['level_type']}:{r['level']}:{r['role_id']}",
                description=f"ロールID: {r['role_id']}"
            ))
        super().__init__(
            placeholder="削除するレベルロール報酬を選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        level_type, level_str, role_id_str = val.split(":")
        level = int(level_str)
        role_id = int(role_id_str)
        
        await database.remove_level_role_reward(level_type, level, role_id)
        
        await update_level_roles_config_view(interaction)

class LevelRolesConfigView(discord.ui.View):
    def __init__(self, rewards, guild: discord.Guild):
        super().__init__(timeout=180)
        self.selected_level_type = None
        self.selected_role = None
        
        self.add_item(LevelTypeSelect())
        self.add_item(LevelRoleSelect())
        self.add_item(AddLevelRoleButton())
        if rewards:
            self.add_item(RemoveLevelRoleSelect(rewards, guild))

async def update_level_roles_config_view(interaction: discord.Interaction):
    rewards = await database.get_level_role_rewards()
    view = LevelRolesConfigView(rewards, interaction.guild)
    
    embed = discord.Embed(
        title="🎁 レベルロール設定パネル",
        description=(
            "レベルに応じて付与されるロールを設定します。\n\n"
            "**【設定手順】**\n"
            "1. **レベルタイプ**（TC/VC）を選択します。\n"
            "2. **付与するロール**を選択します。\n"
            "3. **「レベルを指定して追加」**ボタンを押し、目標レベルを入力します。\n\n"
            "**【削除手順】**\n"
            "一番下の削除用ドロップダウンから、削除したい報酬設定を選択します。"
        ),
        color=discord.Color.blue()
    )
    
    rewards_str = ""
    for r in rewards:
        ltype = "💬 TC" if r["level_type"] == "tc" else "🎙️ VC"
        role = interaction.guild.get_role(r["role_id"])
        role_mention = role.mention if role else f"⚠️ 不明なロール (ID: `{r['role_id']}`)"
        rewards_str += f"• **{ltype}** Lv.{r['level']} ➔ {role_mention}\n"
        
    if not rewards_str:
        rewards_str = "登録されているレベルロール報酬はありません。"
        
    embed.add_field(name="現在の設定一覧", value=rewards_str, inline=False)
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class ManageLevelRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="レベルロールを設定",
            style=discord.ButtonStyle.secondary,
            emoji="🎁",
            custom_id="persistent_admin_manage_level_roles_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        rewards = await database.get_level_role_rewards()
        view = LevelRolesConfigView(rewards, interaction.guild)
        
        embed = discord.Embed(
            title="🎁 レベルロール設定パネル",
            description=(
                "レベルに応じて付与されるロールを設定します。\n\n"
                "**【設定手順】**\n"
                "1. **レベルタイプ**（TC/VC）を選択します。\n"
                "2. **付与するロール**を選択します。\n"
                "3. **「レベルを指定して追加」**ボタンを押し、目標レベルを入力します。\n\n"
                "**【削除手順】**\n"
                "一番下の削除用ドロップダウンから、削除したい報酬設定を選択します。"
            ),
            color=discord.Color.blue()
        )
        
        rewards_str = ""
        for r in rewards:
            ltype = "💬 TC" if r["level_type"] == "tc" else "🎙️ VC"
            role = interaction.guild.get_role(r["role_id"])
            role_mention = role.mention if role else f"⚠️ 不明なロール (ID: `{r['role_id']}`)"
            rewards_str += f"• **{ltype}** Lv.{r['level']} ➔ {role_mention}\n"
            
        if not rewards_str:
            rewards_str = "登録されているレベルロール報酬はありません。"
            
        embed.add_field(name="現在の設定一覧", value=rewards_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# --- 部屋価格設定用UI ---

class RoomPriceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="一般宿 - 12時間", value="宿:12", emoji="🛖"),
            discord.SelectOption(label="一般宿 - 24時間", value="宿:24", emoji="🛖"),
            discord.SelectOption(label="高級宿 - 12時間", value="高級宿:12", emoji="🏰"),
            discord.SelectOption(label="高級宿 - 24時間", value="高級宿:24", emoji="🏰"),
            discord.SelectOption(label="カスタムVC - 24時間", value="カスタムVC:24", emoji="✨")
        ]
        super().__init__(placeholder="価格を変更する部屋タイプを選択...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        rtype, dur_str = self.values[0].split(":")
        duration = int(dur_str)
        
        modal = PriceInputModal(rtype, duration)
        await interaction.response.send_modal(modal)

class PriceInputModal(discord.ui.Modal, title='部屋価格の設定'):
    price_input = discord.ui.TextInput(label='新しい価格', placeholder='例: 12000', max_length=10, required=True)

    def __init__(self, room_type: str, duration: int):
        super().__init__()
        self.room_type = room_type
        self.duration = duration
        self.price_input.label = f"新しい価格 ({CURRENCY_NAME})"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price_input.value)
            if price < 0:
                return await interaction.response.send_message("❌ 0以上の価格を入力してください。", ephemeral=True)
            
            # DB更新
            await database.update_room_price(self.room_type, self.duration, price)
            
            # メモリ内のキャッシュ(ROOM_SETTINGS)も更新
            ROOM_SETTINGS[self.room_type][self.duration]["price"] = price
            
            # ビューを更新
            await update_room_prices_config_view(interaction)
        except ValueError:
            await interaction.response.send_message("❌ 半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] PriceInputModal: {e}")
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True)

class RoomPricesConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(RoomPriceSelect())

async def update_room_prices_config_view(interaction: discord.Interaction):
    view = RoomPricesConfigView()
    embed = discord.Embed(
        title="🏨 部屋の価格設定",
        description=(
            "一般宿・高級宿・カスタムVCの作成/延長時の価格を変更します。\n\n"
            "**【変更手順】**\n"
            "下のドロップダウンメニューから、価格を変更したい部屋と時間を選択し、開いたモーダルで新しい価格を入力してください。"
        ),
        color=discord.Color.blue()
    )
    
    prices_str = ""
    for rtype, dur_map in ROOM_SETTINGS.items():
        emoji = "🛖" if rtype == "宿" else ("🏰" if rtype == "高級宿" else "✨")
        display_name = "一般宿" if rtype == "宿" else rtype
        for dur, settings in dur_map.items():
            prices_str += f"{emoji} **{display_name} ({dur}時間)**: {settings['price']:,} {CURRENCY_NAME}\n"
            
    embed.add_field(name="現在の価格設定", value=prices_str, inline=False)
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class ManageRoomPricesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="部屋価格を設定",
            style=discord.ButtonStyle.secondary,
            emoji="💰",
            custom_id="persistent_admin_manage_room_prices_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        view = RoomPricesConfigView()
        embed = discord.Embed(
            title="🏨 部屋の価格設定",
            description=(
                "一般宿・高級宿・カスタムVCの作成/延長時の価格を変更します。\n\n"
                "**【変更手順】**\n"
                "下のドロップダウンメニューから、価格を変更したい部屋と時間を選択し、開いたモーダルで新しい価格を入力してください。"
            ),
            color=discord.Color.blue()
        )
        
        prices_str = ""
        for rtype, dur_map in ROOM_SETTINGS.items():
            emoji = "🛖" if rtype == "宿" else ("🏰" if rtype == "高級宿" else "✨")
            display_name = "一般宿" if rtype == "宿" else rtype
            for dur, settings in dur_map.items():
                prices_str += f"{emoji} **{display_name} ({dur}時間)**: {settings['price']:,} {CURRENCY_NAME}\n"
                
        embed.add_field(name="現在の価格設定", value=prices_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# --- 匿名チャットシステム ---

class AnonymousMessageModal(discord.ui.Modal, title="匿名メッセージ送信"):
    message_input = discord.ui.TextInput(
        label="メッセージ内容",
        style=discord.TextStyle.paragraph,
        placeholder="ここにメッセージを入力してください...",
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # 掲載先チャンネルをDBから取得
        dest_channel_id = await database.get_anonymous_chat(interaction.channel.id)
        if not dest_channel_id:
            return await interaction.followup.send("❌ 掲載先チャンネルが設定されていません。", ephemeral=True)
            
        guild = interaction.guild
        dest_channel = guild.get_channel(dest_channel_id)
        if not dest_channel:
            try:
                dest_channel = await guild.fetch_channel(dest_channel_id)
            except:
                pass
        
        if not dest_channel:
            return await interaction.followup.send("❌ 掲載先チャンネルが見つかりません。削除された可能性があります。", ephemeral=True)
            
        # プレミアム機能: 日替わり一時IDの生成
        import hashlib
        today_str = datetime.datetime.now(JST).strftime("%Y-%m-%d")
        salt = os.getenv("ANONYMOUS_SALT", "anon_default_salt_998")
        user_hash = hashlib.sha256(f"{interaction.user.id}-{today_str}-{salt}".encode()).hexdigest()
        anon_id = user_hash[:8].upper()
        
        embed = discord.Embed(
            description=self.message_input.value,
            color=0x2f3136
        )
        embed.set_author(
            name=f"匿名ユーザー (ID: {anon_id})",
            icon_url="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=150"
        )
        embed.timestamp = datetime.datetime.now(JST)
        
        try:
            await dest_channel.send(embed=embed)
            await interaction.followup.send("✅ 匿名メッセージを送信しました！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 送信に失敗しました: {e}", ephemeral=True)

class AnonymousChatPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="匿名メッセージを送信", style=discord.ButtonStyle.primary, emoji="💬", custom_id="persistent_anon_chat_btn")
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AnonymousMessageModal())

class AnonymousPanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="① パネルを設置するテキストチャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.panel_channel = self.values[0]
        await self.view.update_state(interaction)

class AnonymousDestChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="② 掲載するテキストチャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.dest_channel = self.values[0]
        await self.view.update_state(interaction)

class ConfirmAnonymousSetupButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="設定を確定",
            style=discord.ButtonStyle.success,
            emoji="✅",
            row=2,
            disabled=True,
            custom_id="admin_anon_setup_confirm_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel_ch_raw = self.view.panel_channel
        dest_ch_raw = self.view.dest_channel
        
        if not panel_ch_raw or not dest_ch_raw:
            return await interaction.followup.send("❌ 設置先と掲載先の両方を選択してください。", ephemeral=True)
            
        guild = interaction.guild
        panel_ch = guild.get_channel(panel_ch_raw.id)
        dest_ch = guild.get_channel(dest_ch_raw.id)
        
        if not panel_ch:
            try:
                panel_ch = await guild.fetch_channel(panel_ch_raw.id)
            except:
                pass
        if not dest_ch:
            try:
                dest_ch = await guild.fetch_channel(dest_ch_raw.id)
            except:
                pass
                
        if not panel_ch or not dest_ch:
            return await interaction.followup.send("❌ 選択されたチャンネルが見つかりませんでした。", ephemeral=True)
            
        try:
            await database.add_anonymous_chat(panel_ch.id, dest_ch.id)
            
            embed = discord.Embed(
                title="💬 匿名チャット窓口",
                description=(
                    "こちらのチャンネルは匿名チャットの送信窓口です。\n\n"
                    "下の「匿名メッセージを送信」ボタンを押すと、入力フォーム（モーダル）が開きます。\n"
                    "送信したメッセージは、設定された掲載チャンネルへ匿名で送信されます。\n"
                    "※発言者を特定することはできませんが、なりすまし防止のため毎日ランダムに変わる「日替わり一時ID」が付与されます。"
                ),
                color=discord.Color.purple()
            )
            await panel_ch.send(embed=embed, view=AnonymousChatPanelView())
            
            await interaction.followup.send(
                f"✅ 匿名チャットの設置が完了しました！\n"
                f"設置先: {panel_ch.mention}\n"
                f"掲載先: {dest_ch.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 設置に失敗しました: {e}", ephemeral=True)

class AnonymousChatSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.panel_channel = None
        self.dest_channel = None
        
        self.panel_select = AnonymousPanelChannelSelect()
        self.dest_select = AnonymousDestChannelSelect()
        self.confirm_button = ConfirmAnonymousSetupButton()
        
        self.add_item(self.panel_select)
        self.add_item(self.dest_select)
        self.add_item(self.confirm_button)

    async def update_state(self, interaction: discord.Interaction):
        if self.panel_channel and self.dest_channel:
            self.confirm_button.disabled = False
        else:
            self.confirm_button.disabled = True
            
        embed = discord.Embed(
            title="💬 匿名チャット設定",
            description=(
                "匿名チャットの設置設定を行います。\n\n"
                "**1. パネル（送信ボタン）を設置するテキストチャンネル** を選択してください。\n"
                "**2. 匿名メッセージが掲載されるテキストチャンネル** を選択してください。"
            ),
            color=discord.Color.purple()
        )
        
        panel_mention = self.panel_channel.mention if self.panel_channel else "❌ 未選択"
        dest_mention = self.dest_channel.mention if self.dest_channel else "❌ 未選択"
        
        embed.add_field(name="① パネル設置先", value=panel_mention, inline=True)
        embed.add_field(name="② メッセージ掲載先", value=dest_mention, inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)


class LogTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="📝 メッセージ編集", value="message_edit", description="メッセージ編集ログ"),
            discord.SelectOption(label="🗑️ メッセージ削除", value="message_delete", description="メッセージ削除ログ"),
            discord.SelectOption(label="🎙️ VC参加・退出", value="vc_join_leave", description="VC参加・移動・退出ログ"),
            discord.SelectOption(label="👥 メンバー入退", value="member_join_leave", description="サーバー参加・退出ログ"),
            discord.SelectOption(label="💰 通貨・経済", value="economy", description="通貨の付与・送金・お渡し等のログ")
        ]
        super().__init__(placeholder="設定するログの種類を選択...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_log_type = self.values[0]
        await interaction.response.defer()

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="送信先テキストチャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_channel = self.values[0]
        await interaction.response.defer()

class SaveLogSettingButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="ログ設定を保存", style=discord.ButtonStyle.success, emoji="💾", row=2)

    async def callback(self, interaction: discord.Interaction):
        log_type = getattr(self.view, "selected_log_type", None)
        channel = getattr(self.view, "selected_channel", None)
        
        if not log_type:
            return await interaction.response.send_message("❌ 先にログの種類を選択してください。", ephemeral=True)
        if not channel:
            return await interaction.response.send_message("❌ 先に送信先チャンネルを選択してください。", ephemeral=True)

        try:
            await database.set_log_channel(interaction.guild_id, log_type, channel.id)
            self.view.selected_log_type = None
            self.view.selected_channel = None
            await update_log_settings_config_view(interaction)
        except Exception as e:
            print(f"[ERROR] SaveLogSettingButton: {e}")
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True)

class RemoveLogSettingSelect(discord.ui.Select):
    def __init__(self, settings, guild: discord.Guild):
        options = []
        log_types = {
            "message_edit": "メッセージ編集",
            "message_delete": "メッセージ削除",
            "vc_join_leave": "VC参加・退出",
            "member_join_leave": "メンバー入退"
        }
        for l_type, ch_id in settings.items():
            ch = guild.get_channel(ch_id)
            ch_name = f"#{ch.name}" if ch else f"不明なチャンネル (ID: {ch_id})"
            options.append(discord.SelectOption(
                label=f"{log_types.get(l_type, l_type)} ➔ {ch_name}",
                value=l_type,
                description=f"ログ設定を解除します"
            ))
        super().__init__(
            placeholder="解除するログ設定を選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        log_type = self.values[0]
        await database.remove_log_channel(interaction.guild_id, log_type)
        await update_log_settings_config_view(interaction)

class LogSettingsConfigView(discord.ui.View):
    def __init__(self, settings, guild: discord.Guild):
        super().__init__(timeout=180)
        self.selected_log_type = None
        self.selected_channel = None
        
        self.add_item(LogTypeSelect())
        self.add_item(LogChannelSelect())
        self.add_item(SaveLogSettingButton())
        if settings:
            self.add_item(RemoveLogSettingSelect(settings, guild))

async def update_log_settings_config_view(interaction: discord.Interaction):
    settings = await database.get_all_log_settings(interaction.guild_id)
    view = LogSettingsConfigView(settings, interaction.guild)
    
    embed = discord.Embed(
        title="📋 サーバーログ設定パネル",
        description=(
            "サーバー内で発生する各種イベント of ログ送信先を設定します。\n\n"
            "**【設定手順】**\n"
            "1. **ログの種類**を選択します。\n"
            "2. **送信先テキストチャンネル**を選択します。\n"
            "3. **「ログ設定を保存」**ボタンを押します。\n\n"
            "**【解除手順】**\n"
            "一番下の解除用ドロップダウンから、解除したい設定を選択します。"
        ),
        color=discord.Color.blue()
    )
    
    log_types = {
        "message_edit": "📝 メッセージ編集",
        "message_delete": "🗑️ メッセージ削除",
        "vc_join_leave": "🎙️ VC参加・退出",
        "member_join_leave": "👥 メンバー入退"
    }
    
    settings_str = ""
    for l_type, display_name in log_types.items():
        ch_id = settings.get(l_type)
        if ch_id:
            channel = interaction.guild.get_channel(ch_id)
            ch_mention = channel.mention if channel else f"⚠️ 不明なチャンネル (ID: `{ch_id}`)"
        else:
            ch_mention = "未設定"
        settings_str += f"• **{display_name}**: {ch_mention}\n"
        
    embed.add_field(name="現在の設定一覧", value=settings_str, inline=False)
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class ManageLogSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="ログを設定",
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            custom_id="persistent_admin_manage_log_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        settings = await database.get_all_log_settings(interaction.guild_id)
        view = LogSettingsConfigView(settings, interaction.guild)
        
        embed = discord.Embed(
            title="📋 サーバーログ設定パネル",
            description=(
                "サーバー内で発生する各種イベントのログ送信先を設定します。\n\n"
                "**【設定手順】**\n"
                "1. **ログの種類**を選択します。\n"
                "2. **送信先テキストチャンネル**を選択します。\n"
                "3. **「ログ設定を保存」**ボタンを押します。\n\n"
                "**【解除手順】**\n"
                "一番下の解除用ドロップダウンから、解除したい設定を選択します。"
            ),
            color=discord.Color.blue()
        )
        
        log_types = {
            "message_edit": "📝 メッセージ編集",
            "message_delete": "🗑️ メッセージ削除",
            "vc_join_leave": "🎙️ VC参加・退出",
            "member_join_leave": "👥 メンバー入退"
        }
        
        settings_str = ""
        for l_type, display_name in log_types.items():
            ch_id = settings.get(l_type)
            if ch_id:
                channel = interaction.guild.get_channel(ch_id)
                ch_mention = channel.mention if channel else f"⚠️ 不明なチャンネル (ID: `{ch_id}`)"
            else:
                ch_mention = "未設定"
            settings_str += f"• **{display_name}**: {ch_mention}\n"
            
        embed.add_field(name="現在の設定一覧", value=settings_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def update_evaluation_settings_config_view(interaction: discord.Interaction, bot):
    cfg = bot.get_evaluation_config(interaction.guild_id)
    view = EvaluationSettingsConfigView(bot, interaction.guild_id)
    
    embed = discord.Embed(
        title="📋 自己紹介・評価設定パネル",
        description=(
            "自己紹介チャンネルと評価用フォーラムの設定を行います。\n\n"
            "**【設定方法】**\n"
            "1. **評価用フォーラムを追加**から、評価用スレッドを作成したいフォーラムを選択して追加します（複数選択可）。\n"
            "2. **削除する評価用フォーラムを選択**から、登録を解除できます。\n"
            "3. **追加する自己紹介チャンネルを選択**から、発言検知（スレッド自動作成）の対象となるテキストチャンネルを追加します（複数選択可）。\n"
            "4. **削除する自己紹介チャンネルを選択**から、登録を解除できます。"
        ),
        color=discord.Color.blue()
    )
    
    forum_strs = []
    for fid in cfg["forum_channel_ids"]:
        ch = interaction.guild.get_channel(fid)
        if ch:
            forum_strs.append(ch.mention)
        else:
            forum_strs.append(f"⚠️ 不明なフォーラム (ID: `{fid}`)")
    forum_ch_str = ", ".join(forum_strs) if forum_strs else "登録されている評価用フォーラムはありません。"
    
    self_intro_strs = []
    for cid in cfg["self_intro_channel_ids"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            self_intro_strs.append(ch.mention)
        else:
            self_intro_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    self_intro_ch_str = ", ".join(self_intro_strs) if self_intro_strs else "登録されている自己紹介チャンネルはありません。"
    
    embed.add_field(name="現在の設定一覧", value=f"• **評価用フォーラム**: {forum_ch_str}\n• **自己紹介チャンネル**: {self_intro_ch_str}", inline=False)
    
    # 評価対象カテゴリーに滞在中のメンバーと滞在時間を表示
    rank_cfg = bot.get_rank_config(interaction.guild_id)
    eval_categories = rank_cfg.get("categories", set()) or rank_cfg.get("whitelist_categories", set())
    # フォールバック: EVAL_TIME_CATEGORY_ID
    if not eval_categories:
        fallback_cat_id = get_setting("EVAL_TIME_CATEGORY_ID")
        if fallback_cat_id and fallback_cat_id != 123456789012345678:
            eval_categories = {fallback_cat_id}

    
    if eval_categories:
        now_aware = datetime.datetime.now(JST)
        staying_strs = []
        guild = interaction.guild
        for member in guild.members:
            if member.bot:
                continue
            if not (member.voice and member.voice.channel):
                continue
            vc = member.voice.channel
            if not vc.category:
                continue
            if vc.category.id not in eval_categories:
                continue
            # 評価対象カテゴリーに滞在中
            join_time = bot.vc_sessions.get(member.id)
            if join_time:
                delta_sec = (now_aware - join_time).total_seconds()
                hours = int(delta_sec // 3600)
                mins = int((delta_sec % 3600) // 60)
                if hours > 0:
                    dur_str = f"{hours}時間{mins}分"
                else:
                    dur_str = f"{mins}分"
            else:
                dur_str = "0分"
            staying_strs.append(f"• {member.mention} — {vc.mention} — **{dur_str}**")
        
        cat_names = []
        for cid in eval_categories:
            cat = guild.get_channel(cid)
            cat_names.append(f"📁 {cat.name}" if cat else f"ID: {cid}")
        cat_label = ", ".join(cat_names)
        
        if staying_strs:
            staying_value = "\n".join(staying_strs[:20])  # 最大20人まで表示
            if len(staying_strs) > 20:
                staying_value += f"\n… 他 {len(staying_strs) - 20} 人"
        else:
            staying_value = "現在滞在しているメンバーはいません。"
        
        embed.add_field(
            name=f"🟢 評価対象カテゴリー滞在状況 ({cat_label})",
            value=staying_value,
            inline=False
        )
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class AddEvaluationForumSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="評価用フォーラムを追加...",
            channel_types=[discord.ChannelType.forum],
            min_values=1,
            max_values=10,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        added_count = 0
        for channel in self.values:
            if channel.id not in cfg["forum_channel_ids"]:
                cfg["forum_channel_ids"].add(channel.id)
                added_count += 1
                
        if added_count > 0:
            await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        else:
            return await interaction.response.send_message("❌ 選択されたフォーラムは全て既に登録されています。", ephemeral=True)
            
        await update_evaluation_settings_config_view(interaction, bot)

class RemoveEvaluationForumSelect(discord.ui.Select):
    def __init__(self, bot, guild_id):
        cfg = bot.get_evaluation_config(guild_id)
        options = []
        guild = bot.get_guild(guild_id)
        for fid in cfg["forum_channel_ids"]:
            ch = guild.get_channel(fid) if guild else None
            name = ch.name if ch else f"不明なフォーラム ({fid})"
            options.append(discord.SelectOption(
                label=name,
                value=str(fid),
                description=f"ID: {fid}"
            ))
        super().__init__(
            placeholder="削除する評価用フォーラムを選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel_id = int(self.values[0])
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        if channel_id not in cfg["forum_channel_ids"]:
            return await interaction.response.send_message(f"❌ そのチャンネルは登録されていません。", ephemeral=True)
            
        cfg["forum_channel_ids"].discard(channel_id)
        await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        
        await update_evaluation_settings_config_view(interaction, bot)

class AddSelfIntroChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="追加する自己紹介チャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=10,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        added_count = 0
        for channel in self.values:
            if channel.id not in cfg["self_intro_channel_ids"]:
                cfg["self_intro_channel_ids"].add(channel.id)
                added_count += 1
                
        if added_count > 0:
            await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        else:
            return await interaction.response.send_message("❌ 選択されたチャンネルは全て既に登録されています。", ephemeral=True)
            
        await update_evaluation_settings_config_view(interaction, bot)

class RemoveSelfIntroChannelSelect(discord.ui.Select):
    def __init__(self, bot, guild_id):
        cfg = bot.get_evaluation_config(guild_id)
        options = []
        guild = bot.get_guild(guild_id)
        for cid in cfg["self_intro_channel_ids"]:
            ch = guild.get_channel(cid) if guild else None
            name = ch.name if ch else f"不明なチャンネル ({cid})"
            options.append(discord.SelectOption(
                label=name,
                value=str(cid),
                description=f"ID: {cid}"
            ))
        super().__init__(
            placeholder="削除する自己紹介チャンネルを選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel_id = int(self.values[0])
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        if channel_id not in cfg["self_intro_channel_ids"]:
            return await interaction.response.send_message(f"❌ そのチャンネルは登録されていません。", ephemeral=True)
            
        cfg["self_intro_channel_ids"].discard(channel_id)
        await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        
        await update_evaluation_settings_config_view(interaction, bot)

class EvaluationSettingsConfigView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=180)
        self.add_item(AddEvaluationForumSelect())
        cfg = bot.get_evaluation_config(guild_id)
        if cfg["forum_channel_ids"]:
            self.add_item(RemoveEvaluationForumSelect(bot, guild_id))
        self.add_item(AddSelfIntroChannelSelect())
        if cfg["self_intro_channel_ids"]:
            self.add_item(RemoveSelfIntroChannelSelect(bot, guild_id))

class ManageEvaluationSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="自己紹介・評価を設定",
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            custom_id="persistent_admin_manage_evaluation_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        bot = interaction.client
        await update_evaluation_settings_config_view(interaction, bot)


# --- ランク設定用ビュー・ボタン・セレクト ---

async def update_rank_settings_config_view(interaction: discord.Interaction, bot):
    cfg = bot.get_rank_config(interaction.guild_id)
    view = RankSettingsConfigView(bot, interaction.guild_id)
    
    embed = discord.Embed(
        title="📊 ランク対象設定 (TC/VC XP)",
        description=(
            "テキスト（TC）およびボイス（VC）の経験値が貯まるチャンネル・カテゴリーを設定します。\n"
            "チャンネル単位でもカテゴリー単位でもまとめて指定できます。\n\n"
            "**【判定ルール】**\n"
            "1. **有効の指定がない場合**: 無効に指定したチャンネル・カテゴリー**以外**すべてが対象になります。\n"
            "2. **無効の指定がない場合**: 有効に指定したチャンネル・カテゴリー**のみ**が対象になります。\n"
            "3. **両方指定されている場合**: 有効リストに含まれ、かつ無効リストに含まれないチャンネルが対象になります。\n"
            "4. **どちらも指定がない場合**: すべてのチャンネルが対象になります。\n\n"
            "**【設定手順】**\n"
            "- チャンネル単位: 上2つのドロップダウンから有効/無効チャンネルを選択します（各最大25個）。\n"
            "- カテゴリー単位: 下2つのドロップダウンからカテゴリーを選択するとそのカテゴリー内全チャンネルに適用されます。\n"
            "- 各「クリア」ボタンで設定を初期化できます。"
        ),
        color=discord.Color.blue()
    )
    
    whitelist_strs = []
    for cid in cfg.get("whitelist", set()):
        ch = interaction.guild.get_channel(cid)
        if ch:
            whitelist_strs.append(ch.mention)
        else:
            whitelist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    whitelist_ch_str = ", ".join(whitelist_strs) if whitelist_strs else "未設定 (無効チャンネル以外が対象)"

    blacklist_strs = []
    for cid in cfg.get("blacklist", set()):
        ch = interaction.guild.get_channel(cid)
        if ch:
            blacklist_strs.append(ch.mention)
        else:
            blacklist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    blacklist_ch_str = ", ".join(blacklist_strs) if blacklist_strs else "未設定 (制限なし)"

    wl_cat_strs = []
    for cid in cfg.get("whitelist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        if cat:
            wl_cat_strs.append(f"📁 {cat.name}")
        else:
            wl_cat_strs.append(f"⚠️ 不明なカテゴリー (ID: `{cid}`)") 
    wl_cat_str = ", ".join(wl_cat_strs) if wl_cat_strs else "未設定"

    bl_cat_strs = []
    for cid in cfg.get("blacklist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        if cat:
            bl_cat_strs.append(f"📁 {cat.name}")
        else:
            bl_cat_strs.append(f"⚠️ 不明なカテゴリー (ID: `{cid}`)")
    bl_cat_str = ", ".join(bl_cat_strs) if bl_cat_strs else "未設定"

    embed.add_field(
        name="現在の設定",
        value=(
            f"• **対応チャンネル (有効)**: {whitelist_ch_str}\n"
            f"• **非対応チャンネル (無効)**: {blacklist_ch_str}\n"
            f"• **対応カテゴリー (有効)**: {wl_cat_str}\n"
            f"• **非対応カテゴリー (無効)**: {bl_cat_str}"
        ),
        inline=False
    )
    
    if interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class WhitelistChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="対応チャンネル (有効) を選択/変更...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.news,
                discord.ChannelType.forum,
                discord.ChannelType.stage_voice
            ],
            min_values=1,
            max_values=25,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist"] = {ch.id for ch in self.values}
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class BlacklistChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="非対応チャンネル (無効) を選択/変更...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.news,
                discord.ChannelType.forum,
                discord.ChannelType.stage_voice
            ],
            min_values=1,
            max_values=25,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist"] = {ch.id for ch in self.values}
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class WhitelistCategorySelect(discord.ui.ChannelSelect):
    """XP対象カテゴリー（有効）選択"""
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="対応カテゴリー (有効) を選択/変更...",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=25,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist_categories"] = {ch.id for ch in self.values}
        cfg["categories"] = cfg["whitelist_categories"]  # legacy互換
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg["whitelist_categories"]), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class BlacklistCategorySelect(discord.ui.ChannelSelect):
    """XP非対象カテゴリー（無効）選択"""
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="非対応カテゴリー (無効) を選択/変更...",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=25,
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist_categories"] = {ch.id for ch in self.values}
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg["blacklist_categories"])
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearWhitelistButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="対応CHをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearBlacklistButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="非対応CHをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearWlCategoriesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="対応CATをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist_categories"] = set()
        cfg["categories"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg["whitelist_categories"]), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearBlCategoriesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="非対応CATをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist_categories"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg["blacklist_categories"])
        )
        await update_rank_settings_config_view(interaction, bot)

class BackToAdminPanelButton(discord.ui.Button):
    def __init__(self, row=4):
        super().__init__(
            label="戻る",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        await update_main_admin_panel(interaction, bot)

class ManageRankSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="ランク対象を設定",
            style=discord.ButtonStyle.secondary,
            emoji="📊",
            custom_id="persistent_admin_manage_rank_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)
        bot = interaction.client
        await update_rank_settings_config_view(interaction, bot)

class RankSettingsConfigView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=180)
        # row=0: 対応チャンネル（有効）
        self.add_item(WhitelistChannelSelect(bot, guild_id))
        # row=1: 非対応チャンネル（無効）
        self.add_item(BlacklistChannelSelect(bot, guild_id))
        # row=2: 対応カテゴリー（有効）
        self.add_item(WhitelistCategorySelect(bot, guild_id))
        # row=3: 非対応カテゴリー（無効）
        self.add_item(BlacklistCategorySelect(bot, guild_id))
        # row=4: クリアボタン群 + 戻るボタン
        self.add_item(ClearWhitelistButton())
        self.add_item(ClearBlacklistButton())
        self.add_item(ClearWlCategoriesButton())
        self.add_item(ClearBlCategoriesButton())
        self.add_item(BackToAdminPanelButton(row=4))


async def update_main_admin_panel(interaction: discord.Interaction, bot):
    embed = discord.Embed(
        title="⚙️ サーバー設定・パネル設置",
        description="下のメニューから設置したいパネルを選択してください。現在の設定情報は以下の通りです。",
        color=0x2f3136
    )

    # 経済
    embed.add_field(
        name="💰 経済設定",
        value=f"通貨名: **{CURRENCY_NAME}**\n初期所持金: **{INITIAL_COINS} {CURRENCY_NAME}**",
        inline=False
    )

    main_sub_roles_str = format_setting_status(interaction.guild, 'MAIN_SUB_MEMBER_ROLE_IDS')
    if "❌" in main_sub_roles_str: main_sub_roles_str = "名前一致: " + ", ".join(MAIN_SUB_MEMBER_ROLE_NAMES)
    
    admin_str = format_setting_status(interaction.guild, 'ADMIN_ROLE_IDS')
    if "❌" in admin_str: admin_str = "名前一致: " + ", ".join(ADMIN_ROLE_NAMES)
    evaluator_str = format_setting_status(interaction.guild, 'EVALUATOR_ROLE_IDS')
    if "❌" in evaluator_str: evaluator_str = "名前一致: " + ", ".join(EVALUATOR_ROLE_NAMES)
    new_member_str = format_setting_status(interaction.guild, 'NEW_MEMBER_ROLE_ID')
    if "❌" in new_member_str: new_member_str = "名前一致: " + NEW_MEMBER_ROLE_NAME
    pending_member_str = format_setting_status(interaction.guild, 'PENDING_MEMBER_ROLE_ID')
    if "❌" in pending_member_str: pending_member_str = "名前一致: " + PENDING_MEMBER_ROLE_NAME
    interviewer_str = format_setting_status(interaction.guild, 'INTERVIEWER_ROLE_IDS')
    if "❌" in interviewer_str: interviewer_str = "名前一致: " + ", ".join(INTERVIEWER_ROLE_NAMES)
    emblem_manager_str = format_setting_status(interaction.guild, 'EMBLEM_MANAGER_ROLE_ID')
    if "❌" in emblem_manager_str: emblem_manager_str = "名前一致: " + EMBLEM_MANAGER_ROLE_NAME
    emblem_master_str = format_setting_status(interaction.guild, 'EMBLEM_MASTER_ROLE_ID')
    if "❌" in emblem_master_str: emblem_master_str = "名前一致: " + EMBLEM_MASTER_ROLE_NAME
    confession_priest_str = format_setting_status(interaction.guild, 'CONFESSION_PRIEST_ROLE_ID')
    if "❌" in confession_priest_str: confession_priest_str = "名前一致: " + CONFESSION_PRIEST_ROLE_NAME
    priest_str = format_setting_status(interaction.guild, 'PRIEST_ROLE_ID')
    if "❌" in priest_str: priest_str = "名前一致: " + PRIEST_ROLE_NAME

    # 宿・カスタムVC
    embed.add_field(
        name="🏨 部屋・宿設定",
        value=(
            f"🛖 **一般宿** (対象: {main_sub_roles_str}):\n"
            f"  ┗ 12時間: {ROOM_SETTINGS['宿'][12]['price']:,} {CURRENCY_NAME}\n"
            f"  ┗ 24時間: {ROOM_SETTINGS['宿'][24]['price']:,} {CURRENCY_NAME}\n"
            f"🏰 **高級宿**:\n"
            f"  ┗ 12時間: {ROOM_SETTINGS['高級宿'][12]['price']:,} {CURRENCY_NAME}\n"
            f"  ┗ 24時間: {ROOM_SETTINGS['高級宿'][24]['price']:,} {CURRENCY_NAME}\n"
            f"✨ **カスタムVC**:\n"
            f"  ┗ 24時間: {ROOM_SETTINGS['カスタムVC'][24]['price']:,} {CURRENCY_NAME}"
        ),
        inline=False
    )

    # ロール・メンバーシップ
    embed.add_field(
        name="👥 ロール設定",
        value=(
            f"管理者ロール: {admin_str}\n"
            f"評価員ロール: {evaluator_str}\n"
            f"入界後ロール: {new_member_str}\n"
            f"待機者ロール: {pending_member_str}\n"
            f"面接官ロール: {interviewer_str}"
        ),
        inline=False
    )

    # 制作・告解
    embed.add_field(
        name="🎨 制作・告解設定",
        value=(
            f"紋章師: {emblem_manager_str}, {emblem_master_str}\n"
            f"司祭: {confession_priest_str}, {priest_str}"
        ),
        inline=False
    )

    # VC作成トリガー
    triggers_str = ""
    for tid in bot.auto_vc_triggers:
        ch = bot.get_channel(tid)
        if ch:
            triggers_str += f"• {ch.mention} (ID: `{tid}`)\n"
        else:
            triggers_str += f"• ⚠️ 不明なチャンネル (ID: `{tid}`)\n"
    if not triggers_str:
        triggers_str = "登録されているトリガーチャンネルはありません。"
    embed.add_field(
        name="🎙️ VC作成トリガー設定",
        value=triggers_str,
        inline=False
    )

    # レベルロール報酬設定
    rewards = await database.get_level_role_rewards()
    rewards_str = ""
    for r in rewards:
        ltype = "💬 TC" if r["level_type"] == "tc" else "🎙️ VC"
        role = interaction.guild.get_role(r["role_id"])
        role_name = role.mention if role else f"不明なロール (ID: {r['role_id']})"
        rewards_str += f"• **{ltype}** Lv.{r['level']} ➔ {role_name}\n"
    if not rewards_str:
        rewards_str = "登録されているレベルロール報酬はありません。"
    embed.add_field(
        name="🎁 レベルロール設定",
        value=rewards_str,
        inline=False
    )

    # 自己紹介・評価設定
    cfg = bot.get_evaluation_config(interaction.guild_id)
    forum_strs = []
    for fid in cfg["forum_channel_ids"]:
        ch = interaction.guild.get_channel(fid)
        if ch:
            forum_strs.append(ch.mention)
        else:
            forum_strs.append(f"⚠️ 不明なフォーラム (ID: `{fid}`)")
    forum_ch_str = ", ".join(forum_strs) if forum_strs else "未設定"

    self_intro_strs = []
    for cid in cfg["self_intro_channel_ids"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            self_intro_strs.append(ch.mention)
        else:
            self_intro_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    self_intro_ch_str = ", ".join(self_intro_strs) if self_intro_strs else "未設定"
    embed.add_field(
        name="📋 自己紹介・評価設定",
        value=(
            f"評価用フォーラム: {forum_ch_str}\n"
            f"自己紹介チャンネル: {self_intro_ch_str}"
        ),
        inline=False
    )

    # ランク設定 (TC/VC XP対象)
    rank_cfg = bot.get_rank_config(interaction.guild_id)
    whitelist_strs = []
    for cid in rank_cfg["whitelist"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            whitelist_strs.append(ch.mention)
        else:
            whitelist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    whitelist_ch_str = ", ".join(whitelist_strs) if whitelist_strs else "未設定 (無効チャンネル以外が対象)"

    blacklist_strs = []
    for cid in rank_cfg["blacklist"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            blacklist_strs.append(ch.mention)
        else:
            blacklist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    blacklist_ch_str = ", ".join(blacklist_strs) if blacklist_strs else "未設定 (制限なし)"

    wl_cat_strs = []
    for cid in rank_cfg.get("whitelist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        wl_cat_strs.append(f"📁 {cat.name}" if cat else f"⚠️ 不明 (ID: `{cid}`)")
    wl_cat_str = ", ".join(wl_cat_strs) if wl_cat_strs else "未設定"

    bl_cat_strs = []
    for cid in rank_cfg.get("blacklist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        bl_cat_strs.append(f"📁 {cat.name}" if cat else f"⚠️ 不明 (ID: `{cid}`)")
    bl_cat_str = ", ".join(bl_cat_strs) if bl_cat_strs else "未設定"

    embed.add_field(
        name="📊 ランク設定 (TC/VC XP対象)",
        value=(
            f"• **対応チャンネル (有効)**: {whitelist_ch_str}\n"
            f"• **非対応チャンネル (無効)**: {blacklist_ch_str}\n"
            f"• **対応カテゴリー (有効)**: {wl_cat_str}\n"
            f"• **非対応カテゴリー (無効)**: {bl_cat_str}"
        ),
        inline=False
    )

    view = PanelSetupView()
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)


class PanelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PanelSelect())
        self.add_item(ManageVCTriggersButton())
        self.add_item(ManageLevelRolesButton())
        self.add_item(ManageRoomPricesButton())
        self.add_item(ManageLogSettingsButton())
        self.add_item(ManageEvaluationSettingsButton())
        self.add_item(ManageRankSettingsButton())

# --- Bot初期設定インタラクティブUI ---
def format_setting_status(guild, key):
    val = get_setting(key)
    is_unset = False
    if val is None:
        is_unset = True
    elif isinstance(val, list) and not val:
        is_unset = True
    elif isinstance(val, int) and (val == 123456789012345678 or val == 0):
        is_unset = True
    
    if is_unset:
        return "❌ 未設定"
        
    if "ROLE" in key:
        if isinstance(val, list):
            roles = [guild.get_role(rid) for rid in val]
            mentions = [role.mention for role in roles if role]
            return ", ".join(mentions) if mentions else "❌ 未設定 (ロールが見つかりません)"
        else:
            role = guild.get_role(val)
            return role.mention if role else "❌ 未設定 (ロールが見つかりません)"
    elif "CHANNEL" in key or "FORUM" in key:
        if isinstance(val, list):
            channels = [guild.get_channel(cid) for cid in val]
            mentions = [ch.mention for ch in channels if ch]
            return ", ".join(mentions) if mentions else "❌ 未設定 (チャンネルが見つかりません)"
        else:
            ch = guild.get_channel(val)
            return ch.mention if ch else "❌ 未設定 (チャンネルが見つかりません)"
    elif "CATEGORY" in key:
        cat = guild.get_channel(val)
        return f"📁 {cat.name}" if cat else "❌ 未設定 (カテゴリーが見つかりません)"
    return str(val)

class BotSetupMainSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👥 管理者ロール", value="ADMIN_ROLE_IDS", description="管理者のロールを設定します"),
            discord.SelectOption(label="👥 見習い・初級評価員", value="EVALUATOR_TIER1_ROLE_IDS", description="見習い・初級ランクの評価員ロール"),
            discord.SelectOption(label="👥 中級・上級評価員", value="EVALUATOR_TIER2_ROLE_IDS", description="中級・上級ランクの評価員ロール"),
            discord.SelectOption(label="👥 特級・統括評価員", value="EVALUATOR_TIER3_ROLE_IDS", description="特級・統括ランクの評価員ロール"),
            discord.SelectOption(label="👥 新規メンバーロール", value="NEW_MEMBER_ROLE_ID", description="入界後の一般メンバーロール"),
            discord.SelectOption(label="👥 入界待機者ロール", value="PENDING_MEMBER_ROLE_ID", description="面接待ちメンバーのロール"),
            discord.SelectOption(label="👥 面接官ロール", value="INTERVIEWER_ROLE_IDS", description="面接を行える権限ロール"),
            discord.SelectOption(label="👥 本・準メンバーロール", value="MAIN_SUB_MEMBER_ROLE_IDS", description="一般宿を無料・無制限で利用できる本・準メンバーのロール"),
            discord.SelectOption(label="👥 スタンプ統括ロール", value="EMBLEM_MANAGER_ROLE_ID", description="スタンプ制作を管理するロール"),
            discord.SelectOption(label="👥 スタンプ制作ロール", value="EMBLEM_MASTER_ROLE_ID", description="スタンプを制作するロール"),
            discord.SelectOption(label="👥 告解司祭ロール", value="CONFESSION_PRIEST_ROLE_ID", description="告解を対応する司祭ロール"),
            discord.SelectOption(label="👥 司祭ロール", value="PRIEST_ROLE_ID", description="相談を対応する司祭ロール"),
            discord.SelectOption(label="👥 イベント管理ロール", value="EVENT_MANAGER_ROLE_IDS", description="イベント登録・編集・削除ができるロール"),
            discord.SelectOption(label="📺 レベルアップチャンネル", value="LEVEL_UP_CHANNEL_ID", description="レベルアップ通知を送る先"),
            discord.SelectOption(label="📺 VC作成トリガー", value="CREATE_VC_CHANNEL_ID", description="入室すると自動VCを作る部屋"),
            discord.SelectOption(label="📺 評価時間対象カテゴリー", value="EVAL_TIME_CATEGORY_ID", description="評価時間を計測するカテゴリー"),
            discord.SelectOption(label="📺 自己紹介チャンネル", value="SELF_INTRO_CHANNEL_IDS", description="自己紹介を行う部屋（複数可）"),
            discord.SelectOption(label="📺 見習い・初級フォーラム", value="EVALUATION_FORUM_TIER1_IDS", description="見習い・初級用の評価フォーラム"),
            discord.SelectOption(label="📺 中級・上級フォーラム", value="EVALUATION_FORUM_TIER2_IDS", description="中級・上級用の評価フォーラム"),
            discord.SelectOption(label="📺 特級・統括フォーラム", value="EVALUATION_FORUM_TIER3_IDS", description="特級・統括用の評価フォーラム")
        ]
        super().__init__(placeholder="設定する項目を選択してください...", options=options, custom_id="admin_bot_setup_main_select")

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        view = BotSetupConfigureView(interaction.user, key)
        embed = view.build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)

class BotSetupMainView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=300)
        self.user = user
        self.add_item(BotSetupMainSelect())

    def build_embed(self, guild):
        embed = discord.Embed(
            title="⚙️ Bot初期設定・管理パネル",
            description="Discord内の各種設定を調整します。選択メニューから項目を選んでください。",
            color=0x2f3136
        )
        roles_text = (
            f"• 管理者: {format_setting_status(guild, 'ADMIN_ROLE_IDS')}\n"
            f"• 見習い・初級評価員: {format_setting_status(guild, 'EVALUATOR_TIER1_ROLE_IDS')}\n"
            f"• 中級・上級評価員: {format_setting_status(guild, 'EVALUATOR_TIER2_ROLE_IDS')}\n"
            f"• 特級・統括評価員: {format_setting_status(guild, 'EVALUATOR_TIER3_ROLE_IDS')}\n"
            f"• 新規メンバー: {format_setting_status(guild, 'NEW_MEMBER_ROLE_ID')}\n"
            f"• 入界待機者: {format_setting_status(guild, 'PENDING_MEMBER_ROLE_ID')}\n"
            f"• 面接官: {format_setting_status(guild, 'INTERVIEWER_ROLE_IDS')}\n"
            f"• 無料宿対象: {format_setting_status(guild, 'MAIN_SUB_MEMBER_ROLE_IDS')}\n"
            f"• スタンプ統括: {format_setting_status(guild, 'EMBLEM_MANAGER_ROLE_ID')}\n"
            f"• スタンプ制作: {format_setting_status(guild, 'EMBLEM_MASTER_ROLE_ID')}\n"
            f"• 告解司祭: {format_setting_status(guild, 'CONFESSION_PRIEST_ROLE_ID')}\n"
            f"• 司祭: {format_setting_status(guild, 'PRIEST_ROLE_ID')}\n"
            f"• イベント管理: {format_setting_status(guild, 'EVENT_MANAGER_ROLE_IDS')}"
        )
        embed.add_field(name="👥 ロール設定", value=roles_text, inline=False)
        
        channels_text = (
            f"• レベルアップ通知: {format_setting_status(guild, 'LEVEL_UP_CHANNEL_ID')}\n"
            f"• VC作成トリガー: {format_setting_status(guild, 'CREATE_VC_CHANNEL_ID')}\n"
            f"• 評価時間対象カテゴリ: {format_setting_status(guild, 'EVAL_TIME_CATEGORY_ID')}\n"
            f"• 自己紹介部屋: {format_setting_status(guild, 'SELF_INTRO_CHANNEL_IDS')}\n"
            f"• 見習い・初級フォーラム: {format_setting_status(guild, 'EVALUATION_FORUM_TIER1_IDS')}\n"
            f"• 中級・上級フォーラム: {format_setting_status(guild, 'EVALUATION_FORUM_TIER2_IDS')}\n"
            f"• 特級・統括フォーラム: {format_setting_status(guild, 'EVALUATION_FORUM_TIER3_IDS')}"
        )
        embed.add_field(name="📺 チャンネル・カテゴリー設定", value=channels_text, inline=False)
        return embed


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.user:
            await interaction.response.send_message("このパネルは操作できません。", ephemeral=True)
            return False
        return True

class BotSetupRoleSelect(discord.ui.RoleSelect):
    def __init__(self, key, is_multi):
        super().__init__(
            placeholder="設定するロールを選択してください...",
            min_values=1,
            max_values=10 if is_multi else 1,
            custom_id="admin_bot_setup_role_select"
        )
        self.key = key
        self.is_multi = is_multi

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        guild = interaction.guild
        if self.is_multi:
            value = [role.id for role in self.values]
        else:
            value = self.values[0].id
            
        await database.save_setting(self.key, value)
        interaction.client.bot_settings[self.key] = value

        embed = discord.Embed(
            title="✅ 設定完了",
            description=f"`{self.key}` を正常に設定しました！\n\n現在の設定値: {format_setting_status(guild, self.key)}",
            color=discord.Color.green()
        )
        back_view = BotSetupConfigureView(view.user, self.key)
        await interaction.response.edit_message(embed=embed, view=back_view)

class BotSetupChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, key, is_multi, channel_types):
        super().__init__(
            placeholder="設定するチャンネルを選択してください...",
            min_values=1,
            max_values=10 if is_multi else 1,
            channel_types=channel_types,
            custom_id="admin_bot_setup_channel_select"
        )
        self.key = key
        self.is_multi = is_multi

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        guild = interaction.guild
        if self.is_multi:
            value = [ch.id for ch in self.values]
        else:
            value = self.values[0].id
            
        await database.save_setting(self.key, value)
        interaction.client.bot_settings[self.key] = value
        
        if self.key == "CREATE_VC_CHANNEL_ID":
            await database.add_auto_vc_trigger(value)
            interaction.client.auto_vc_triggers.add(value)

        embed = discord.Embed(
            title="✅ 設定完了",
            description=f"`{self.key}` を正常に設定しました！\n\n現在の設定値: {format_setting_status(guild, self.key)}",
            color=discord.Color.green()
        )
        back_view = BotSetupConfigureView(view.user, self.key)
        await interaction.response.edit_message(embed=embed, view=back_view)

class BotSetupConfigureView(discord.ui.View):
    def __init__(self, user, key):
        super().__init__(timeout=300)
        self.user = user
        self.key = key
        
        is_multi = "IDS" in key
        if "ROLE" in key:
            self.add_item(BotSetupRoleSelect(key, is_multi))
        elif "CHANNEL" in key or "FORUM" in key:
            types = [discord.ChannelType.text]
            if "FORUM" in key:
                types = [discord.ChannelType.forum]
            elif "VC" in key:
                types = [discord.ChannelType.voice]
            self.add_item(BotSetupChannelSelect(key, is_multi, types))
        elif "CATEGORY" in key:
            types = [discord.ChannelType.category]
            self.add_item(BotSetupChannelSelect(key, is_multi, types))

    def build_embed(self, guild):
        embed = discord.Embed(
            title=f"🛠️ 設定の変更: {self.key}",
            description=(
                f"**現在の設定値:** {format_setting_status(guild, self.key)}\n\n"
                "下のドロップダウンメニューから、この項目に設定したいロールやチャンネルを選択してください。"
            ),
            color=0x3498db
        )
        return embed

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = BotSetupMainView(self.user)
        embed = view.build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.user:
            await interaction.response.send_message("このパネルは操作できません。", ephemeral=True)
            return False
        return True

class AdminGroup(app_commands.Group):
    def __init__(self): super().__init__(name="管理者", description="【管理者専用】管理コマンド")

    @app_commands.command(name="bot初期設定", description="【管理者専用】Discord内でBotのロールやチャンネルを設定できる管理画面を表示します")
    @is_admin()
    async def bot_setup(self, interaction: discord.Interaction):
        view = BotSetupMainView(interaction.user)
        embed = view.build_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="パネル設置", description="【管理者専用】自分にしか見えないパネル設定画面を表示し、各種パネルを設置します")
    @is_admin()
    async def panel_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await update_main_admin_panel(interaction, bot)

    @app_commands.command(name="ランクリセット", description="ランクを初期化します")
    @is_admin()
    @app_commands.describe(user="リセットする特定のユーザー", all_players="サーバー全員をリセットする場合は『はい』を選択")
    async def rank_reset(self, interaction: discord.Interaction, user: discord.Member = None, all_players: bool = False):
        await interaction.response.defer(ephemeral=True)
        
        if all_players:
            # 全ユーザーのリセット
            p = await database.get_pool()
            async with p.acquire() as conn:
                await conn.execute('UPDATE users SET tc_xp = 0, tc_level = 1, vc_xp = 0, vc_level = 1')
            await interaction.followup.send("✅ 全ユーザーのランクをリセットしました。", ephemeral=True)
        elif user:
            # 特定ユーザーのリセット
            await database.reset_user_rank(user.id)
            await interaction.followup.send(f"✅ {user.mention} のランクをリセットしました。", ephemeral=True)
        else:
            # 何も指定されていない場合
            await interaction.followup.send("❌ エラー: ユーザーを指定するか、『全プレイヤー』に『はい』を選択してください。", ephemeral=True)

    @app_commands.command(name="通貨付与", description="指定ユーザーに通貨を付与（最大10人まで）")
    @app_commands.describe(
        target1="付与先1",
        amount="1人あたりの金額",
        target2="付与先2（任意）",
        target3="付与先3（任意）",
        target4="付与先4（任意）",
        target5="付与先5（任意）",
        target6="付与先6（任意）",
        target7="付与先7（任意）",
        target8="付与先8（任意）",
        target9="付与先9（任意）",
        target10="付与先10（任意）"
    )
    @is_admin()
    async def give(
        self, 
        it: discord.Interaction, 
        target1: discord.Member, 
        amount: int,
        target2: discord.Member = None,
        target3: discord.Member = None,
        target4: discord.Member = None,
        target5: discord.Member = None,
        target6: discord.Member = None,
        target7: discord.Member = None,
        target8: discord.Member = None,
        target9: discord.Member = None,
        target10: discord.Member = None
    ):
        targets = [t for t in [target1, target2, target3, target4, target5, target6, target7, target8, target9, target10] if t is not None]
        valid_targets = []
        for t in targets:
            if t not in valid_targets:
                valid_targets.append(t)
                
        await it.response.defer()
        
        for t in valid_targets:
            await database.add_balance(t.id, amount)
            await it.followup.send(f"✅ {t.mention} に {amount} {CURRENCY_NAME} 付与しました。")
            await send_economy_log(
                it.guild,
                "💰 通貨付与",
                f"管理者の {it.user.mention} が {t.mention} に **{amount} {CURRENCY_NAME}** を付与しました。",
                user=it.user
            )

    @app_commands.command(name="通貨没収", description="指定ユーザーから通貨を没収")
    @is_admin()
    async def remove(self, it, target: discord.Member, amount: int):
        await database.remove_balance(target.id, amount)
        await it.response.send_message(f"✅ {target.mention} から {amount} {CURRENCY_NAME} 没収しました。")
        await send_economy_log(
            it.guild,
            "📉 通貨没収",
            f"管理者の {it.user.mention} が {target.mention} から **{amount} {CURRENCY_NAME}** を没収しました。",
            user=it.user,
            color=discord.Color.red()
        )

    @app_commands.command(name="所持金リセット", description="所持金の初期化")
    @app_commands.checks.has_permissions(administrator=True)
    async def rbal(self, it, user: discord.Member):
        await database.reset_user_balance(user.id); await it.response.send_message("リセット完了", ephemeral=True)
        await send_economy_log(
            it.guild,
            "🔄 所持金リセット",
            f"管理者の {it.user.mention} が {user.mention} の所持金をリセットしました。",
            user=it.user,
            color=discord.Color.red()
        )


    @app_commands.command(name="デバッグ_vc", description="【管理者用】一時部屋のDB登録状況を確認します")
    @is_admin()
    async def debug_vc(self, it):
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM rooms WHERE room_type = $1', "一時部屋")
        
        if not rows:
            return await it.response.send_message("現在、DBに登録されている一時部屋はありません。", ephemeral=True)
        
        txt = "【DB登録済みの一時部屋】\n"
        for r in rows:
            ch = bot.get_channel(r['channel_id'])
            status = f"✅ 存在 ({ch.name})" if ch else "❌ チャンネル消失"
            txt += f"- CH ID: {r['channel_id']} | 所有者ID: {r['owner_id']} | {status}\n"
        
        await it.response.send_message(txt[:2000], ephemeral=True)

class InterviewerGroup(app_commands.Group):
    def __init__(self): super().__init__(name="面接官", description="【面接官専用】手続きコマンド")

    @app_commands.command(name="help", description="面接官用コマンドの使い方を表示します")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(title="👔 面接官コマンドの使い方", color=discord.Color.blue())
        embed.add_field(name="/面接官 パネル設置_入界手続き", value="新規メンバーが入界手続きを行うためのボタン付きパネルを現在のチャンネルに送信します。", inline=False)
        embed.add_field(name="/面接官 入界手続き実行", value="現在のチャンネルの履歴（最大50件）から、待機者ロールを持つユーザーの発言を読み取り、「入力された名前への変更」「新規メンバーロールの付与」「待機者ロールの剥奪」「初期通貨の付与」を一括で自動実行します。", inline=False)
        embed.add_field(name="/面接官 チャット削除", value="現在のチャンネルのチャット履歴を、指定した件数分（デフォルト100件）削除します。", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @app_commands.command(name="パネル設置_入界手続き", description="入界手続きパネルを送信")
    async def s_int(self, it):
        if not has_interviewer_role(it.user) and not has_admin_role(it.user) and not it.user.guild_permissions.administrator:
            return await it.response.send_message("権限がありません。", ephemeral=True)
        await it.channel.send(embed=discord.Embed(title="✨ 入界手続き", description="下のボタンから登録してください。", color=discord.Color.green()), view=InterviewPanelView())
        await it.response.send_message("設置完了", ephemeral=True)

    @app_commands.command(name="入界手続き実行", description="VCチャットの履歴から入界待機者の発言を取得し、入界手続きを一括実行します")
    async def execute_interview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        
        if not has_interviewer_role(interaction.user) and not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("権限がありません。", ephemeral=True)
            
        pending_role = get_role_by_setting(interaction.guild, "PENDING_MEMBER_ROLE_ID", PENDING_MEMBER_ROLE_NAME)
        new_role = get_role_by_setting(interaction.guild, "NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_NAME)
        
        if not pending_role or not new_role:
            return await interaction.followup.send("エラー：ロールの設定が見つかりません。", ephemeral=True)
            
        target_users = {}
        try:
            async for msg in interaction.channel.history(limit=50):
                if msg.author.bot: continue
                if isinstance(msg.author, discord.Member) and pending_role in msg.author.roles:
                    if msg.author not in target_users:
                        name_str = msg.content.strip()[:32]
                        if name_str:
                            target_users[msg.author] = name_str
        except Exception as e:
            return await interaction.followup.send(f"履歴の取得に失敗しました: {e}", ephemeral=True)
            
        if not target_users:
            return await interaction.followup.send("対象となる入界待機者の発言が見つかりませんでした。", ephemeral=True)
            
        results = []
        for member, desired_name in target_users.items():
            duplicate = False
            for m in interaction.guild.members:
                if m.id != member.id and m.display_name == desired_name and pending_role not in m.roles:
                    duplicate = True
                    break
            
            if duplicate:
                await interaction.channel.send(f"{member.mention} 鯖内にて使用済みの名前です。")
                results.append(f"❌ {member.display_name} -> {desired_name} (名前重複)")
                continue
                
            try:
                await member.edit(nick=desired_name)
                await member.add_roles(new_role)
                await member.remove_roles(pending_role)
                await database.add_balance(member.id, INITIAL_COINS)
                await database.set_initial_issued(member.id)
                results.append(f"✅ {member.mention} -> **{desired_name}**")
                await send_economy_log(
                    interaction.guild,
                    "🆕 初期通貨発行 (一括)",
                    f"面接官の {interaction.user.mention} が {member.mention} の入界手続きを実行し、初期通貨 **{INITIAL_COINS} {CURRENCY_NAME}** を付与しました。",
                    user=member
                )
            except Exception as e:
                results.append(f"❌ {member.display_name} -> 権限エラー等")
                
        embed = discord.Embed(title="✨ 入界手続き一括実行結果", description="\n".join(results), color=discord.Color.green())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="初期発行", description="指定ユーザーの手動入界手続き（初期発行）を行います")
    @app_commands.describe(user="対象ユーザー")
    async def manual_issue(self, interaction: discord.Interaction, user: discord.Member):
        if not has_interviewer_role(interaction.user) and not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=False)
        
        pending_role = get_role_by_setting(interaction.guild, "PENDING_MEMBER_ROLE_ID", PENDING_MEMBER_ROLE_NAME)
        new_role = get_role_by_setting(interaction.guild, "NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_NAME)
        
        if not pending_role or not new_role:
            return await interaction.followup.send("エラー：ロールの設定が見つかりません。", ephemeral=True)
            
        try:
            if pending_role in user.roles:
                await user.remove_roles(pending_role)
            if new_role not in user.roles:
                await user.add_roles(new_role)
                
            await database.add_balance(user.id, INITIAL_COINS)
            await database.set_initial_issued(user.id)
            
            embed = discord.Embed(
                title="✨ 手動入界手続き完了", 
                description=f"✅ {user.mention} の初期発行を完了しました。\n（ロールの付与・剥奪、初期通貨の付与）", 
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)
            await send_economy_log(
                interaction.guild,
                "🆕 初期通貨発行 (手動)",
                f"面接官の {interaction.user.mention} が {user.mention} の手動入界手続きを実行し、初期通貨 **{INITIAL_COINS} {CURRENCY_NAME}** を付与しました。",
                user=user
            )
        except Exception as e:
            await interaction.followup.send(f"❌ {user.display_name} の手続き中にエラーが発生しました: {e}", ephemeral=True)

    @app_commands.command(name="未発行者一括付与", description="過去のログから未発行のメンバーを抽出し、初期発行を一括で行います")
    @app_commands.describe(log_channel_id="ログを参照するチャンネルID（デフォルトは指定のチャンネル）")
    async def batch_initial_issue(self, interaction: discord.Interaction, log_channel_id: str = "1506457200149795006"):
        if not has_interviewer_role(interaction.user) and not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=False)
        try:
            target_channel_id = int(log_channel_id)
            channel = interaction.guild.get_channel(target_channel_id)
            if not channel:
                return await interaction.followup.send("エラー：指定されたチャンネルが見つかりません。")

            issued_user_ids = set()
            give_pattern = re.compile(r"✅\s*<@!?(\d+)>\s*に\s*([0-9,]+)\s*Rune\s*付与しました")
            issue_pattern = re.compile(r"✅\s*<@!?(\d+)>\s*の初期発行を完了しました")

            async for message in channel.history(limit=None, oldest_first=True):
                if message.author.id != interaction.client.user.id: continue
                content = message.content or ""
                if message.embeds:
                    for embed in message.embeds:
                        if embed.description: content += "\n" + embed.description

                match_give = give_pattern.search(content)
                if match_give:
                    user_id = int(match_give.group(1))
                    amount = int(match_give.group(2).replace(",", ""))
                    if amount >= 30000:
                        issued_user_ids.add(user_id)
                match_issue = issue_pattern.search(content)
                if match_issue:
                    user_id = int(match_issue.group(1))
                    issued_user_ids.add(user_id)

            new_issue_count = 0
            already_issued_count = 0
            for member in interaction.guild.members:
                if member.bot: continue
                if member.id in issued_user_ids:
                    await database.set_initial_issued(member.id)
                    already_issued_count += 1
                else:
                    user_data = await database.get_user(member.id)
                    if user_data["initial_issued"]:
                        already_issued_count += 1
                        continue
                    
                    await database.add_balance(member.id, INITIAL_COINS)
                    await database.set_initial_issued(member.id)
                    new_issue_count += 1
                    await send_economy_log(
                        interaction.guild,
                        "🆕 初期通貨発行 (未発行者一括)",
                        f"管理者の {interaction.user.mention} による一括処理で、{member.mention} に初期通貨 **{INITIAL_COINS} {CURRENCY_NAME}** が付与されました。",
                        user=member
                    )

            embed = discord.Embed(title="✨ 一括初期発行 完了", color=discord.Color.green())
            embed.add_field(name="新規発行", value=f"{new_issue_count} 名", inline=True)
            embed.add_field(name="発行済み確認", value=f"{already_issued_count} 名", inline=True)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}")

    @app_commands.command(name="チャット削除", description="現在のチャンネルのチャット履歴を削除します（最大100件）")
    async def clear_chat(self, interaction: discord.Interaction, amount: int = 100):
        if not has_interviewer_role(interaction.user) and not has_admin_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"✅ {len(deleted)}件のメッセージを削除しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ メッセージを削除する権限（メッセージの管理）がBotにありません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

async def get_thread_reaction_counts(interaction: discord.Interaction, user: discord.Member):
    b010 = 0
    b011 = 0
    tier = get_evaluator_tier(interaction.user)
    forum_ids = set()
    if tier >= 1:
        if get_setting("EVALUATION_FORUM_TIER1_IDS"): forum_ids.update(get_setting("EVALUATION_FORUM_TIER1_IDS"))
        if get_setting("EVALUATION_FORUM_CHANNEL_IDS"): forum_ids.update(get_setting("EVALUATION_FORUM_CHANNEL_IDS"))
    if tier >= 2:
        if get_setting("EVALUATION_FORUM_TIER2_IDS"): forum_ids.update(get_setting("EVALUATION_FORUM_TIER2_IDS"))
    if tier >= 3:
        if get_setting("EVALUATION_FORUM_TIER3_IDS"): forum_ids.update(get_setting("EVALUATION_FORUM_TIER3_IDS"))
    
    for fid in forum_ids:
        ch = interaction.guild.get_channel(fid)
        if not ch: continue
            
        target_threads = []
        if hasattr(ch, "threads"):
            for t in ch.threads:
                if user.name in t.name or user.display_name in t.name:
                    target_threads.append(t)
                
        if hasattr(ch, 'archived_threads'):
            async for t in ch.archived_threads(limit=100):
                if user.name in t.name or user.display_name in t.name:
                    target_threads.append(t)
                
        for t in target_threads:
            try:
                first_msg = None
                async for msg in t.history(limit=1, oldest_first=True):
                    first_msg = msg
                    break
                
                if first_msg and str(user.id) in first_msg.content:
                    for r in first_msg.reactions:
                        name = r.emoji if isinstance(r.emoji, str) else r.emoji.name
                        if name == "b_010":
                            b010 += r.count
                        elif name == "b_011":
                            b011 += r.count
            except:
                pass
                
    return b010, b011

class EvaluationGroup(app_commands.Group):
    def __init__(self): super().__init__(name="評価期間", description="評価期間関連コマンド")

    @app_commands.command(name="help", description="評価期間関連コマンドの使い方を表示します")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⏳ 評価期間コマンドの使い方", color=discord.Color.green())
        embed.add_field(name="/評価期間 一覧", value="【運営・評価員専用】現在評価期間中となっているユーザーとその終了予定日時の一覧を表示します。", inline=False)
        embed.add_field(name="/評価期間 確認 [ユーザー]", value="指定したユーザー（指定なしの場合は自分）の評価期間の開始・終了日時を確認します。", inline=False)
        embed.add_field(name="/評価期間 延長 <ユーザー> <日数>", value="【運営・評価員専用】指定したユーザーの評価期間を、指定した日数分だけ延長します。", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="一覧", description="【運営・評価員専用】評価期間中のユーザー一覧を表示")
    async def list_periods(self, interaction: discord.Interaction):
        if not has_evaluator_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        periods = await database.get_all_evaluation_periods()
        if not periods:
            return await interaction.response.send_message("現在評価期間中のユーザーはいません。", ephemeral=True)
            
        embed = discord.Embed(title="📋 評価期間中ユーザー一覧", color=discord.Color.blue())
        for p in periods:
            member = interaction.guild.get_member(p['user_id'])
            name = member.display_name if member else f"ID: {p['user_id']}"
            end_str = format_evaluation_datetime(p['end_time'])
            embed.add_field(name=name, value=f"終了予定: {end_str} (<t:{int(p['end_time'].timestamp())}:R>)", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="確認", description="ユーザーの評価期間を確認します")
    async def check_period(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        is_evaluator = has_evaluator_role(interaction.user) or interaction.user.guild_permissions.administrator
        
        if target.id != interaction.user.id:
            if not is_evaluator:
                return await interaction.response.send_message("他人の評価期間を見る権限がありません。", ephemeral=True)
                
        period = await database.get_evaluation_period(target.id)
        if not period:
            return await interaction.response.send_message(f"{target.display_name} は評価期間中ではありません。", ephemeral=True)
            
        start_str = format_evaluation_datetime(period['start_time'])
        end_str = format_evaluation_datetime(period['end_time'])
        end_t = int(period['end_time'].timestamp())
        
        embed = discord.Embed(title=f"⏳ {target.display_name} の評価期間", color=discord.Color.green())
        embed.add_field(name="開始時刻", value=start_str, inline=False)
        embed.add_field(name="終了予定", value=f"{end_str} (<t:{end_t}:R>)", inline=False)
        
        if is_evaluator:
            counts = await database.get_user_evaluation_counts(target.id)
            db_b010 = counts.get("b_010", 0)
            db_b011 = counts.get("b_011", 0)
            
            thread_b010, thread_b011 = await get_thread_reaction_counts(interaction, target)
            b_010_count = db_b010 + thread_b010
            b_011_count = db_b011 + thread_b011
            
            emoji_b010 = discord.utils.get(interaction.guild.emojis, name="b_010")
            b010_str = str(emoji_b010) if emoji_b010 else ":b_010:"
            emoji_b011 = discord.utils.get(interaction.guild.emojis, name="b_011")
            b011_str = str(emoji_b011) if emoji_b011 else ":b_011:"
            
            embed.add_field(name="📊 スレッド評価（合算）", value=f"{b010_str} {thread_b010} 個\n{b011_str} {thread_b011} 個", inline=False)
            if db_b010 > 0 or db_b011 > 0:
                embed.add_field(name="💾 過去の追加分（DB）", value=f"{b010_str} {db_b010} 個\n{b011_str} {db_b011} 個", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="延長", description="【運営・評価員専用】ユーザーの評価期間を延長します")
    @app_commands.describe(user="延長するユーザー", extra_days="延長する日数")
    async def extend_period(self, interaction: discord.Interaction, user: discord.Member, extra_days: int):
        if not has_evaluator_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        if extra_days <= 0:
            return await interaction.response.send_message("1以上の延長日数を指定してください。", ephemeral=True)
            
        success = await database.extend_evaluation_period(user.id, extra_days)
        if not success:
            return await interaction.response.send_message(f"{user.display_name} は評価期間中ではありません。", ephemeral=True)
            
        period = await database.get_evaluation_period(user.id)
        end_str = format_evaluation_datetime(period['end_time'])
        await interaction.response.send_message(f"✅ {user.mention} の評価期間を {extra_days} 日延長しました。\n新しい終了予定: {end_str}", ephemeral=True)

class EvaluatorSheetSelect(discord.ui.Select):
    def __init__(self, target_user: discord.Member, forum_channels: list, intro_link: str = None):
        self.target_user = target_user
        self.intro_link = intro_link
        options = []
        for ch in forum_channels:
            options.append(discord.SelectOption(label=f"📁 {ch.name}", value=str(ch.id)))
        
        super().__init__(
            placeholder="作成するフォーラムを選択 (複数可)...",
            min_values=1,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        created_links = []
        
        # 評価期間の取得
        period = await database.get_evaluation_period(self.target_user.id)
        if period:
            start_str = format_evaluation_datetime(period['start_time'])
            end_str = format_evaluation_datetime(period['end_time'])
            base_content = (
                f"**対象者:** {self.target_user.mention}\n"
                f"**評価期間:** {start_str} ～ {end_str}\n\n"
            )
        else:
            base_content = (
                f"**対象者:** {self.target_user.mention}\n"
                f"**評価期間:** データが見つかりませんでした。\n\n"
            )
            
        if self.intro_link:
            base_content += f"**自己紹介へのリンク:**\n{self.intro_link}"
        else:
            base_content += f"**自己紹介へのリンク:**\n手動作成 (自己紹介リンクなし)"
            
        thread_name = f"{self.target_user.display_name}_{self.target_user.name}"
        
        for val in self.values:
            ch_id = int(val)
            ch = interaction.guild.get_channel(ch_id)
            if not ch: continue
            
            try:
                if isinstance(ch, discord.ForumChannel):
                    thread_with_message = await ch.create_thread(
                        name=thread_name,
                        content=base_content
                    )
                    thread = thread_with_message.thread
                else:
                    thread = await ch.create_thread(
                        name=thread_name,
                        type=discord.ChannelType.public_thread
                    )
                    await thread.send(base_content)
                created_links.append(f"• [{ch.name}]({thread.jump_url})")
            except Exception as e:
                created_links.append(f"• エラー ({ch.name}): {e}")
                
        res = "\\n".join(created_links)
        await interaction.followup.send(f"以下の評価シートを作成しました:\\n{res}", ephemeral=True)

class EvaluatorSheetSelectView(discord.ui.View):
    def __init__(self, target_user: discord.Member, forum_channels: list, intro_link: str = None):
        super().__init__(timeout=180)
        self.add_item(EvaluatorSheetSelect(target_user, forum_channels, intro_link))

class EvaluatorSheetGroup(app_commands.Group):
    def __init__(self): super().__init__(name="評価員", description="評価員向けコマンド")

    @app_commands.command(name="help", description="評価員向けコマンドとスタンプ集計の仕様について説明します")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔰 評価員コマンド・スタンプ集計の仕様について",
            description="各種評価コマンドと、権限ランクに応じたスタンプ表示制限についての説明です。",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="1. /評価員 評価確認",
            value="対象ユーザーの現在の評価スタンプ数を確認します。\n実行者の権限ランク（見習い/中級/特級など）に応じて、**閲覧できるフォーラムのスタンプ範囲が自動的に制限**されます。",
            inline=False
        )
        embed.add_field(
            name="2. /評価期間 確認",
            value="対象ユーザーの評価期間を確認します。\n一般メンバーが自身を確認した場合は期間のみが表示され、**評価員が確認した場合はスタンプ数も合算して表示**されます（閲覧範囲は1と同じく権限に依存します）。",
            inline=False
        )
        embed.add_field(
            name="3. 【管理者向け】/管理 bot設定",
            value="評価員ロールと対象フォーラムを3段階のランク（見習い・初級、中級・上級、特級・統括）に分けて設定できます。これにより、ランクに応じたスタンプの表示制限が機能します。",
            inline=False
        )
        embed.set_footer(text="※過去にデータベースへ手動追加されたスタンプは、スレッドとは別に「過去の追加分」として表示されます。")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="評価シート作成", description="指定したユーザーの評価シート(スレッド)を作成します")
    @app_commands.describe(user="評価シートを作成するユーザー", intro_link="自己紹介のメッセージリンク等（任意）")
    async def create_sheet(self, interaction: discord.Interaction, user: discord.Member, intro_link: str = None):
        if not has_evaluator_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        cfg = interaction.client.get_evaluation_config(interaction.guild_id)
        forum_ids = cfg.get("forum_channel_ids", [])
        if not forum_ids:
            return await interaction.response.send_message("評価用フォーラムが設定されていません。", ephemeral=True)
            
        forum_channels = []
        for fid in forum_ids:
            ch = interaction.guild.get_channel(fid)
            if ch:
                forum_channels.append(ch)
                
        if not forum_channels:
            return await interaction.response.send_message("有効な評価用フォーラムが見つかりません。", ephemeral=True)
            
        view = EvaluatorSheetSelectView(user, forum_channels, intro_link)
        await interaction.response.send_message(f"{user.display_name} さんの評価シート作成先を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="評価確認", description="指定したユーザーの評価スタンプ数を確認します")
    @app_commands.describe(user="確認するユーザー")
    async def check_eval(self, interaction: discord.Interaction, user: discord.Member):
        if not has_evaluator_role(interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        counts = await database.get_user_evaluation_counts(user.id)
        db_b010 = counts.get("b_010", 0)
        db_b011 = counts.get("b_011", 0)
        
        thread_b010, thread_b011 = await get_thread_reaction_counts(interaction, user)
        b_010_count = db_b010 + thread_b010
        b_011_count = db_b011 + thread_b011
        
        emoji_b010 = discord.utils.get(interaction.guild.emojis, name="b_010")
        b010_str = str(emoji_b010) if emoji_b010 else ":b_010:"
        emoji_b011 = discord.utils.get(interaction.guild.emojis, name="b_011")
        b011_str = str(emoji_b011) if emoji_b011 else ":b_011:"

        embed = discord.Embed(title=f"📊 {user.display_name} さんの評価結果", color=discord.Color.blue())
        embed.add_field(name="📊 スレッド評価（合算）", value=f"{b010_str} {thread_b010} 個\n{b011_str} {thread_b011} 個", inline=False)
        if db_b010 > 0 or db_b011 > 0:
            embed.add_field(name="💾 過去の追加分（DB）", value=f"{b010_str} {db_b010} 個\n{b011_str} {db_b011} 個", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- 実行 ---
EVENTS_FILE = 'events.json'

def load_events():
    if not os.path.exists(EVENTS_FILE):
        return {}
    try:
        with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_events(data):
    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def parse_date(date_str):
    if not date_str or date_str == "未定":
        return datetime.datetime.max
    
    formats = [
        "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M",
        "%m/%d %H:%M", "%m-%d %H:%M",
        "%Y/%m/%d", "%Y-%m-%d",
        "%m/%d", "%m-%d",
        "%Y年%m月%d日 %H:%M", "%m月%d日 %H:%M",
        "%Y年%m月%d日", "%m月%d日"
    ]
    for fmt in formats:
        try:
            parsed = datetime.datetime.strptime(date_str, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.datetime.now().year)
            return parsed
        except ValueError:
            pass
            
    return datetime.datetime.max

class EventGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="イベント", description="イベントのスケジュール管理を行います")

    @app_commands.command(name="help", description="イベント管理機能の使い方を表示します")
    async def show_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📅 イベントスケジュール管理機能の使い方",
            description="イベントや予定を簡単に登録・共有できます！",
            color=discord.Color.blue()
        )
        embed.add_field(name="1. /イベント 登録", value="新しいイベントを作成します。企画書のURLも登録可能です。", inline=False)
        embed.add_field(name="2. /イベント 一覧", value="登録されているイベントを一覧で表示します。リンクもクリックできます。", inline=False)
        embed.add_field(name="3. /イベント 修正", value="イベントの内容を修正したり、後から企画書を追加したりできます。", inline=False)
        embed.add_field(name="4. /イベント 削除", value="イベントを一覧から削除します。", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="登録", description="新しいイベントをスケジュールに登録します")
    @app_commands.describe(name="イベント名", start_date="開始日 (例: 5/10 21:00)", end_date="終了日（任意）", detail="詳細（任意）", proposal_url="企画書のURL（任意）")
    async def add_event(self, interaction: discord.Interaction, name: str, start_date: str, end_date: str = "", detail: str = "", proposal_url: str = ""):
        events = load_events()
        new_id = 1
        existing_ids = set(int(k) for k in events.keys() if k.isdigit())
        while new_id in existing_ids:
            new_id += 1
        
        events[str(new_id)] = {
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "detail": detail,
            "proposal_url": proposal_url,
            "created_by": interaction.user.display_name
        }
        save_events(events)
        
        embed = discord.Embed(title="✅ イベントを登録しました", color=discord.Color.green())
        embed.add_field(name="ID", value=str(new_id), inline=False)
        embed.add_field(name="イベント名", value=name, inline=False)
        if end_date:
            embed.add_field(name="開始", value=start_date, inline=False)
            embed.add_field(name="終了", value=end_date, inline=False)
        else:
            embed.add_field(name="日時", value=f"{start_date}（1日のみ）", inline=False)
        if detail:
            embed.add_field(name="詳細", value=detail, inline=False)
        if proposal_url:
            embed.add_field(name="企画書", value=f"[リンク]({proposal_url})", inline=False)
            
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="一覧", description="登録されているイベントの一覧を表示します")
    async def list_events(self, interaction: discord.Interaction):
        events = load_events()
        if not events:
            await interaction.response.send_message("現在登録されているイベントはありません。")
            return
            
        embed = discord.Embed(title="📅 イベント一覧", color=discord.Color.blue())
        
        sorted_events = sorted(
            events.items(), 
            key=lambda item: parse_date(item[1].get("start_date", item[1].get("time", "未定")))
        )
        
        for event_id, info in sorted_events:
            name = info.get("name", "未定")
            start_date = info.get("start_date", info.get("time", "未定"))
            end_date = info.get("end_date", "")
            detail = info.get("detail", "")
            proposal_url = info.get("proposal_url", "")
            
            if end_date:
                value = f"**開始**: {start_date}\n**終了**: {end_date}"
            else:
                value = f"**日時**: {start_date}（1日のみ）"
            if detail:
                value += f"\n**詳細**: {detail}"
            if proposal_url:
                value += f"\n**企画書**: [リンク]({proposal_url})"
                
            embed.add_field(name=f"[ID: {event_id}] {name}", value=value, inline=False)
            
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="修正", description="登録済みのイベント内容を修正します")
    @app_commands.describe(event_id="修正するイベントのID", name="新しいイベント名（任意）", start_date="新しい開始日（任意）", end_date="新しい終了日（任意）", detail="新しい詳細（任意）", proposal_url="新しい企画書URL（任意）")
    async def edit_event(self, interaction: discord.Interaction, event_id: int, name: str = None, start_date: str = None, end_date: str = None, detail: str = None, proposal_url: str = None):
        if not has_event_manager_role(interaction.user):
            await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
            return
        events = load_events()
        eid_str = str(event_id)
        if eid_str not in events:
            await interaction.response.send_message(f"ID: {event_id} のイベントは見つかりませんでした。", ephemeral=True)
            return
            
        if name:
            events[eid_str]["name"] = name
        if start_date:
            events[eid_str]["start_date"] = start_date
        if end_date:
            events[eid_str]["end_date"] = end_date
        if detail:
            events[eid_str]["detail"] = detail
        if proposal_url:
            events[eid_str]["proposal_url"] = proposal_url
            
        save_events(events)
        await interaction.response.send_message(f"✅ ID: {event_id} のイベントを修正しました。")

    @app_commands.command(name="削除", description="登録済みのイベントを削除します")
    @app_commands.describe(event_id="削除するイベントのID")
    async def delete_event(self, interaction: discord.Interaction, event_id: int):
        if not has_event_manager_role(interaction.user):
            await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
            return
        events = load_events()
        eid_str = str(event_id)
        if eid_str not in events:
            await interaction.response.send_message(f"ID: {event_id} のイベントは見つかりませんでした。", ephemeral=True)
            return
            
        deleted_name = events[eid_str].get("name", "")
        del events[eid_str]
        save_events(events)
        
        await interaction.response.send_message(f"🗑️ イベント「{deleted_name}」(ID: {event_id}) を削除しました。")

# --- リアクションロール（任意ロール）関連UI ---
class CustomRolePanelSetupModal(discord.ui.Modal, title="任意ロールパネル設置"):
    panel_title = discord.ui.TextInput(label="パネルのタイトル", default="ロール付与パネル")
    panel_desc = discord.ui.TextInput(
        label="説明文 (例: 🎮:ゲーム)", 
        style=discord.TextStyle.paragraph, 
        default="以下のリアクションを押してロールを取得してください。"
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=self.panel_title.value, description=self.panel_desc.value, color=discord.Color.gold())
        msg = await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            "パネルを設置しました！続けて以下のメニューから、付与するロールと絵文字を紐付けてください。",
            view=ReactionRoleAdminView(msg),
            ephemeral=True
        )

class ReactionRoleAdminView(discord.ui.View):
    def __init__(self, target_message: discord.Message):
        super().__init__(timeout=None)
        self.target_message = target_message

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="付与するロールを選択してください...")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        selected_role = select.values[0]
        await interaction.response.send_message(
            f"🎯 ロール {selected_role.mention} を選択しました。\\n\\n"
            f"**対象のパネル（上のメッセージ）に、Discord標準の絵文字ピッカーを使って直接リアクションを付けてください！**\\n"
            f"（※スタンプ一覧からの検索機能がそのまま使えます。60秒以内にリアクションをお願いします）", 
            ephemeral=True
        )
        
        def check(payload: discord.RawReactionActionEvent):
            return payload.message_id == self.target_message.id and payload.user_id == interaction.user.id

        import asyncio
        try:
            payload = await interaction.client.wait_for('raw_reaction_add', timeout=60.0, check=check)
        except asyncio.TimeoutError:
            try:
                await interaction.followup.send("⏳ タイムアウトしました。もう一度メニューからロールを選び直してください。", ephemeral=True)
            except:
                pass
            return
            
        emoji_str = str(payload.emoji)
        
        # Bot自身がリアクションをつけ、運営のリアクションを消す（ユーザーが押しやすくするため）
        try:
            await self.target_message.remove_reaction(payload.emoji, interaction.user)
            await self.target_message.add_reaction(payload.emoji)
        except Exception:
            pass

        await database.add_reaction_role(self.target_message.id, emoji_str, selected_role.id)
        await interaction.followup.send(f"✅ 追加完了！\\n絵文字 {emoji_str} にロール {selected_role.mention} を紐付けました！\\n続けて別のロールを設定する場合は、上のメニューから再度選択してください。", ephemeral=True)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
        
    emoji_str = str(payload.emoji)
    role_id = await database.get_reaction_role(payload.message_id, emoji_str)
    if not role_id:
        return
        
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
        
    member = guild.get_member(payload.user_id)
    if not member:
        return
        
    role = guild.get_role(role_id)
    if role:
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            pass

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
        
    emoji_str = str(payload.emoji)
    role_id = await database.get_reaction_role(payload.message_id, emoji_str)
    if not role_id:
        return
        
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
        
    member = guild.get_member(payload.user_id)
    if not member:
        return
        
    role = guild.get_role(role_id)
    if role:
        try:
            await member.remove_roles(role)
        except discord.Forbidden:
            pass

if __name__ == "__main__":
    if TOKEN:
        discord.utils.setup_logging()
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN is not set in .env")
