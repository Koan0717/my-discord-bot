import discord
import datetime
import database

CURRENCY_NAME = "Rune"
JST = datetime.timezone(datetime.timedelta(hours=9))

# 獲得量の設定
MSG_COOLDOWN = 60     # メッセージ獲得のクールダウン（秒）

# 経験値の設定
TC_XP_REWARD = 10      # メッセージ1通あたりのXP
TC_XP_COOLDOWN = 10    # TC XP獲得のクールダウン（秒）
VC_XP_PER_MIN = 15     # VC滞在1分あたりのXP
LEVEL_UP_CHANNEL_ID = 123456789012345678
RANKING_CATEGORY_NAME = "【仮】ランク対象カテゴリ名"

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
    "EVALUATION_FORUM_CHANNEL_IDS": [],
    "GAMBLE_CHINCHIRO_EXPECTATION": 0.95,
    "GAMBLE_COINFLIP_EXPECTATION": 0.95,
    "GAMBLE_SLOT_EXPECTATION": 0.95,
    "GAMBLE_BLACKJACK_EXPECTATION": 0.95,
    "GAMBLE_ROULETTE_EXPECTATION": 0.95
}

def get_setting(bot, key: str):
    if hasattr(bot, 'bot_settings') and key in bot.bot_settings:
        return bot.bot_settings[key]
    if key == "EVAL_TIME_CATEGORY_ID" and hasattr(bot, 'bot_settings') and "RANKING_CATEGORY_ID" in bot.bot_settings:
        return bot.bot_settings["RANKING_CATEGORY_ID"]
    return DEFAULT_SETTINGS.get(key)

def get_role_by_setting(bot, guild, key, default_name):
    role_id = get_setting(bot, key)
    role = guild.get_role(role_id) if role_id else None
    if not role:
        role = discord.utils.get(guild.roles, name=default_name)
    return role

def get_role_by_id_or_name(guild, role_id, default_name):
    role = guild.get_role(role_id) if role_id else None
    if not role:
        role = discord.utils.get(guild.roles, name=default_name)
    return role

def has_event_manager_role(bot, user: discord.Member):
    event_manager_role_ids = get_setting(bot, "EVENT_MANAGER_ROLE_IDS")
    if not event_manager_role_ids:
        event_manager_role_ids = []
    user_role_ids = [role.id for role in user.roles]
    if any(rid in event_manager_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    return False

def has_admin_role(bot, user: discord.Member):
    admin_role_ids = get_setting(bot, "ADMIN_ROLE_IDS")
    user_role_ids = [role.id for role in user.roles]
    if any(rid in admin_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    user_role_names = [role.name for role in user.roles]
    if any(name in ADMIN_ROLE_NAMES for name in user_role_names):
        return True
    return False

def get_evaluator_tier(bot, user: discord.Member) -> int:
    if user.guild_permissions.administrator: return 3
    user_role_ids = [r.id for r in user.roles]
    
    admin_ids = get_setting(bot, "ADMIN_ROLE_IDS") or []
    if any(rid in admin_ids for rid in user_role_ids): return 3
    
    tier3_ids = get_setting(bot, "EVALUATOR_TIER3_ROLE_IDS") or []
    if any(rid in tier3_ids for rid in user_role_ids): return 3
    
    tier2_ids = get_setting(bot, "EVALUATOR_TIER2_ROLE_IDS") or []
    if any(rid in tier2_ids for rid in user_role_ids): return 2
    
    tier1_ids = get_setting(bot, "EVALUATOR_TIER1_ROLE_IDS") or []
    if any(rid in tier1_ids for rid in user_role_ids): return 1
    
    old_eval_ids = get_setting(bot, "EVALUATOR_ROLE_IDS") or []
    if any(rid in old_eval_ids for rid in user_role_ids): return 1
    
    user_role_names = [role.name for role in user.roles]
    if any(name in EVALUATOR_ROLE_NAMES or name in ADMIN_ROLE_NAMES for name in user_role_names):
        return 1
    
    return 0

def has_evaluator_role(bot, user: discord.Member) -> bool:
    return get_evaluator_tier(bot, user) > 0

def has_interviewer_role(bot, user: discord.Member):
    interviewer_role_ids = get_setting(bot, "INTERVIEWER_ROLE_IDS")
    user_role_ids = [r.id for r in user.roles]
    if any(rid in interviewer_role_ids for rid in user_role_ids):
        return True
    user_role_names = [r.name for r in user.roles]
    if any(name in INTERVIEWER_ROLE_NAMES for name in user_role_names):
        return True
    return False

def is_main_or_sub_member(bot, user: discord.Member):
    main_sub_role_ids = get_setting(bot, "MAIN_SUB_MEMBER_ROLE_IDS")
    user_role_ids = [r.id for r in user.roles]
    if any(rid in main_sub_role_ids for rid in user_role_ids):
        return True
    user_role_names = [r.name for r in user.roles]
    if any(name in MAIN_SUB_MEMBER_ROLE_NAMES for name in user_role_names):
        return True
    return False

def is_in_eval_time_category(bot, channel):
    if not channel or not channel.category:
        return False
    eval_cat_id = get_setting(bot, "EVAL_TIME_CATEGORY_ID")
    if channel.category.id == eval_cat_id:
        return True
    ranking_cat_name = get_setting(bot, "RANKING_CATEGORY_NAME")
    if ranking_cat_name and ranking_cat_name.lower() in channel.category.name.lower():
        return True
    return False

def is_xp_enabled(bot, channel):
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

def is_in_evaluation_category(bot, channel):
    if not channel or not channel.category:
        return False
    cfg = bot.get_rank_config(channel.guild.id)
    categories = cfg.get("categories", set())
    if categories:
        return channel.category.id in categories
    eval_cat_id = get_setting(bot, "EVAL_TIME_CATEGORY_ID")
    if channel.category.id == eval_cat_id:
        return True
    ranking_cat_name = get_setting(bot, "RANKING_CATEGORY_NAME")
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

async def check_and_assign_level_roles(bot, member: discord.Member, level_type: str, new_level: int):
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
            lv_channel_id = get_setting(bot, "LEVEL_UP_CHANNEL_ID")
            lv_channel = member.guild.get_channel(lv_channel_id)
            if lv_channel:
                await lv_channel.send(f"🎁 {member.mention} が {level_type.upper()} レベル {new_level} に達したため、以下のロールが付与されました！\n{role_mentions}")
    except Exception as e:
        print(f"[ERROR] check_and_assign_level_roles for {member.display_name}: {e}")

# ------------
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

async def send_gambling_log(guild: discord.Guild, user: discord.Member, game_name: str, bet: int, count: int):
    bal = await database.get_balance(user.id)
    rem = 10 - count
    await send_economy_log(
        guild, 
        f"🎲 カジノ ({game_name})", 
        f"{user.mention} が **{game_name}** に **{bet} {CURRENCY_NAME}** 賭けました。\n💰 残高: **{bal} {CURRENCY_NAME}**\n🔄 残り回数: **{rem}回**", 
        user=user
    )
