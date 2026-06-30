import datetime
import discord
from discord.ext import commands
from discord import app_commands
import database
import os
import json

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
FREE_INN_ROLE_NAMES = ["【仮】無料宿ロール名A", "【仮】無料宿ロール名B"]
MAIN_SUB_MEMBER_ROLE_NAMES = ["【仮】本メンバーロール名", "【仮】準メンバーロール名"]
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
    "EVALUATION_CATEGORY_ID": 123456789012345678,
    "NEW_MEMBER_ROLE_ID": 123456789012345678,
    "PENDING_MEMBER_ROLE_ID": 123456789012345678,
    "INTERVIEWER_ROLE_IDS": [],
    "FREE_INN_ROLE_IDS": [],
    "EMBLEM_MANAGER_ROLE_ID": 123456789012345678,
    "EMBLEM_MASTER_ROLE_ID": 123456789012345678,
    "CONFESSION_PRIEST_ROLE_ID": 123456789012345678,
    "PRIEST_ROLE_ID": 123456789012345678,
    "ADMIN_ROLE_IDS": [],
    "EVALUATOR_ROLE_IDS": [],
    "SELF_INTRO_CHANNEL_IDS": [],
    "EVALUATION_FORUM_CHANNEL_IDS": [],
    "CURRENCY_NAME": "コイン",
    "GAMBLE_EMPLOYEE_ROLE_IDS": [],
    "GAMBLE_MANAGER_ROLE_IDS": [],
    "GAMBLE_MAX_BET": 100000,
    "GAMBLE_MAX_PLAYS": 10,
    "GAMBLE_CHINCHIRO_EXPECTATION": 0.95,
    "GAMBLE_COINFLIP_EXPECTATION": 0.95,
    "GAMBLE_SLOT_EXPECTATION": 0.95,
    "GAMBLE_BLACKJACK_EXPECTATION": 0.95,
    "GAMBLE_ROULETTE_EXPECTATION": 0.95,
    "MAIN_SUB_MEMBER_ROLE_IDS": [],
    "DOWNGRADE_ROLE_ID": 123456789012345678,
    "ENABLE_TC_RANK": True,
    "VC_COINS_PER_MIN": 12,
    "MINUS_TARGET_ROLE_IDS": []
}

def get_setting(bot, key: str):
    if hasattr(bot, 'bot_settings') and key in bot.bot_settings:
        return bot.bot_settings[key]
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

def has_admin_role(bot, user: discord.Member):
    admin_role_ids = get_setting(bot, "ADMIN_ROLE_IDS") or []
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

def has_gamble_employee_role(bot, user: discord.Member):
    employee_role_ids = get_setting(bot, "GAMBLE_EMPLOYEE_ROLE_IDS") or []
    admin_role_ids = get_setting(bot, "ADMIN_ROLE_IDS") or []
    user_role_ids = [role.id for role in user.roles]
    if any(rid in employee_role_ids or rid in admin_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    return False

def has_gamble_manager_role(bot, user: discord.Member):
    manager_role_ids = get_setting(bot, "GAMBLE_MANAGER_ROLE_IDS") or []
    admin_role_ids = get_setting(bot, "ADMIN_ROLE_IDS") or []
    user_role_ids = [role.id for role in user.roles]
    if any(rid in manager_role_ids or rid in admin_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    return False

def has_interviewer_role(bot, user: discord.Member):
    interviewer_role_ids = get_setting(bot, "INTERVIEWER_ROLE_IDS") or []
    admin_role_ids = get_setting(bot, "ADMIN_ROLE_IDS") or []
    user_role_ids = [r.id for r in user.roles]
    if any(rid in interviewer_role_ids or rid in admin_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    user_role_names = [r.name for r in user.roles]
    if any(name in INTERVIEWER_ROLE_NAMES or name in ADMIN_ROLE_NAMES for name in user_role_names):
        return True
    return False

def has_event_manager_role(bot, user: discord.Member):
    event_manager_role_ids = get_setting(bot, "EVENT_MANAGER_ROLE_IDS")
    if not event_manager_role_ids:
        event_manager_role_ids = []
    user_role_ids = [role.id for role in user.roles]
    if any(rid in event_manager_role_ids for rid in user_role_ids) or user.guild_permissions.administrator:
        return True
    return False

def is_free_inn_member(bot, user: discord.Member):
    free_inn_role_ids = get_setting(bot, "FREE_INN_ROLE_IDS") or []
    user_role_ids = [r.id for r in user.roles]
    if any(rid in free_inn_role_ids for rid in user_role_ids):
        return True
    user_role_names = [r.name for r in user.roles]
    if any(name in FREE_INN_ROLE_NAMES for name in user_role_names):
        return True
    return False

def is_main_or_sub_member(bot, user: discord.Member) -> bool:
    main_sub_role_ids = get_setting(bot, "MAIN_SUB_MEMBER_ROLE_IDS") or []
    user_role_ids = [r.id for r in user.roles]
    if any(rid in main_sub_role_ids for rid in user_role_ids):
        return True
    user_role_names = [r.name for r in user.roles]
    if any(name in MAIN_SUB_MEMBER_ROLE_NAMES for name in user_role_names):
        return True
    return False

def is_downgrade_member(bot, user: discord.Member) -> bool:
    downgrade_role_id = get_setting(bot, "DOWNGRADE_ROLE_ID")
    if downgrade_role_id and any(r.id == downgrade_role_id for r in user.roles):
        return True
    return False

def is_new_member(bot, user: discord.Member) -> bool:
    new_member_role_id = get_setting(bot, "NEW_MEMBER_ROLE_ID")
    if new_member_role_id and any(r.id == new_member_role_id for r in user.roles):
        return True
    user_role_names = [r.name for r in user.roles]
    if NEW_MEMBER_ROLE_NAME in user_role_names:
        return True
    return False

def get_luxury_inn_price(bot, user: discord.Member, duration: int) -> int:
    base_price = ROOM_SETTINGS["高級宿"][duration]["price"]
    role_prices = getattr(bot, "role_room_prices", {})
    
    if is_downgrade_member(bot, user):
        custom_price = role_prices.get(("DOWNGRADE_ROLE", "高級宿", duration))
        if custom_price is not None:
            return custom_price
            
    if is_new_member(bot, user):
        custom_price = role_prices.get(("NEW_MEMBER_ROLE", "高級宿", duration))
        if custom_price is not None:
            return custom_price
            
    if has_admin_role(bot, user) or is_main_or_sub_member(bot, user):
        custom_price = role_prices.get(("MAIN_SUB_MEMBER_ROLE", "高級宿", duration))
        if custom_price is not None:
            return custom_price
            
    return base_price

def is_rank_eligible(bot, channel) -> bool:
    if not channel or not hasattr(channel, "guild") or not channel.guild:
        return False
    guild_id = channel.guild.id
    cfg = bot.get_rank_config(guild_id)
    whitelist_channels = cfg.get("whitelist", set())
    whitelist_categories = cfg.get("categories", set())
    blacklist_channels = cfg.get("blacklist", set())
    blacklist_categories = cfg.get("blacklist_categories", set())
    
    has_whitelist = len(whitelist_channels) > 0 or len(whitelist_categories) > 0
    has_blacklist = len(blacklist_channels) > 0 or len(blacklist_categories) > 0
    
    in_whitelist = (channel.id in whitelist_channels) or (channel.category and channel.category.id in whitelist_categories)
    in_blacklist = (channel.id in blacklist_channels) or (channel.category and channel.category.id in blacklist_categories)
    
    if not has_whitelist and not has_blacklist:
        return True
    elif not has_whitelist and has_blacklist:
        return not in_blacklist
    elif has_whitelist and not has_blacklist:
        return in_whitelist
    else:
        return in_whitelist and not in_blacklist

def is_vc_coins_eligible(bot, channel) -> bool:
    if not channel or not hasattr(channel, "guild") or not channel.guild:
        return False
    guild_id = channel.guild.id
    cfg = bot.get_vc_coins_config(guild_id)
    whitelist_channels = cfg.get("whitelist", set())
    whitelist_categories = cfg.get("categories", set())
    blacklist_channels = cfg.get("blacklist", set())
    blacklist_categories = cfg.get("blacklist_categories", set())
    
    has_whitelist = len(whitelist_channels) > 0 or len(whitelist_categories) > 0
    has_blacklist = len(blacklist_channels) > 0 or len(blacklist_categories) > 0
    
    in_whitelist = (channel.id in whitelist_channels) or (channel.category and channel.category.id in whitelist_categories)
    in_blacklist = (channel.id in blacklist_channels) or (channel.category and channel.category.id in blacklist_categories)
    
    if not has_whitelist and not has_blacklist:
        return True
    elif not has_whitelist and has_blacklist:
        return not in_blacklist
    elif has_whitelist and not has_blacklist:
        return in_whitelist
    else:
        return in_whitelist and not in_blacklist

def format_evaluation_datetime(dt: datetime.datetime) -> str:
    if not dt:
        return "データなし"
    if dt.tzinfo is not None:
        dt = dt.astimezone(JST)
    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
    return dt.strftime(f"%Y年%m月%d日({weekday_ja}) %H:%M")

async def check_and_assign_level_roles(bot, member: discord.Member, level_type: str, new_level: int):
    rewards = await database.get_level_role_rewards(level_type)
    roles_to_add = []
    for r in rewards:
        if r["level"] <= new_level:
            role = member.guild.get_role(r["role_id"])
            if role and role not in member.roles:
                roles_to_add.append(role)
    if roles_to_add:
        try:
            await member.add_roles(*roles_to_add, reason=f"{level_type.upper()}レベル到達報酬 (Lv.{new_level})")
            role_mentions = ", ".join([role.mention for role in roles_to_add])
            lv_channel_id = get_setting(bot, "LEVEL_UP_CHANNEL_ID")
            lv_channel = member.guild.get_channel(lv_channel_id)
            if lv_channel:
                await lv_channel.send(f"🎁 {member.mention} が {level_type.upper()} レベル {new_level} に達したため、以下のロールが付与されました！\n{role_mentions}")
        except Exception as e:
            print(f"[ERROR] check_and_assign_level_roles for {member.display_name}: {e}")

async def check_and_assign_level_coins(bot, member: discord.Member, level_type: str, new_level: int):
    rewards = await database.get_level_coin_rewards(level_type)
    coins_to_add = 0
    for r in rewards:
        if r["level"] == new_level:
            coins_to_add += r["coins"]
            
    if coins_to_add > 0:
        try:
            await database.add_balance(member.id, coins_to_add)
            currency_name = get_setting(bot, "CURRENCY_NAME") or "コイン"
            lv_channel_id = get_setting(bot, "LEVEL_UP_CHANNEL_ID")
            lv_channel = member.guild.get_channel(lv_channel_id)
            if lv_channel:
                await lv_channel.send(f"🪙 {member.mention} が {level_type.upper()} レベル {new_level} に達したため、報酬として **{coins_to_add:,} {currency_name}** が付与されました！")
        except Exception as e:
            print(f"[ERROR] check_and_assign_level_coins for {member.display_name}: {e}")

# --- ログ用ヘルパー ---
async def send_log(bot, guild: discord.Guild, log_type: str, embed: discord.Embed):
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

# --- 運営権限チェックデコレータ ---
def is_admin():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild:
            return False
        if has_admin_role(interaction.client, interaction.user):
            return True
        await interaction.response.send_message("このコマンドを実行する権限がありません（運営専用ロールが必要です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_gamble_employee():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild:
            return False
        if has_gamble_employee_role(interaction.client, interaction.user):
            return True
        await interaction.response.send_message("このコマンドを実行する権限がありません（賭博従業員または管理者専用です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_admin_or_interviewer():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild:
            return False
        if has_admin_role(interaction.client, interaction.user) or has_interviewer_role(interaction.client, interaction.user):
            return True
        await interaction.response.send_message("このコマンドを実行する権限がありません（運営または面接官専用です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)

# --- ギャンブル用ヘルパー ---


def create_blackjack_deck():
    suits = ["♠️", "♥️", "♦️", "♣️"]
    values = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    deck = [{"suit": suit, "value": val} for suit in suits for val in values]
    import random
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

def circled_to_int(s: str):
    circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    if s in circled:
        return circled.index(s) + 1
    return None

def get_circled_number(n: int) -> str:
    circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    if 1 <= n <= 20:
        return circled[n-1]
    return f"({n})"

# --- イベント用ヘルパー ---
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

def format_setting_status(bot, guild, key):
    val = get_setting(bot, key)
    is_unset = False
    if val is None:
        is_unset = True
    elif isinstance(val, list) and not val:
        is_unset = True
    elif isinstance(val, int) and (val == 123456789012345678 or val == 0):
        is_unset = True
    
    if is_unset:
        return "❌ 未設定"
        
    if isinstance(val, bool):
        return "🟢 有効" if val else "🔴 無効"
    if "ROLE" in key:
        if isinstance(val, list):
            roles = [guild.get_role(rid) for rid in val]
            mentions = [role.mention for role in roles if role]
            return ", ".join(mentions) if mentions else "❌ 未設定 (ロールが見つかりません)"
        else:
            role = guild.get_role(val)
            return role.mention if role else "❌ 未設定 (ロールが見つかりません)"
            
    if "CHANNEL" in key or "FORUM" in key:
        if isinstance(val, list):
            channels = [guild.get_channel(cid) for cid in val]
            mentions = [chan.mention for chan in channels if chan]
            return ", ".join(mentions) if mentions else "❌ 未設定 (チャンネルが見つかりません)"
        else:
            chan = guild.get_channel(val)
            return chan.mention if chan else "❌ 未設定 (チャンネルが見つかりません)"
            
    if "CATEGORY" in key:
        chan = guild.get_channel(val)
        return chan.name if chan else "❌ 未設定 (カテゴリーが見つかりません)"
        
    return str(val)

