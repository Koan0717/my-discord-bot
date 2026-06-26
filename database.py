import asyncpg
import datetime
import os
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
JST = datetime.timezone(datetime.timedelta(hours=9))

# 接続プールを保持する変数
pool = None

async def get_pool():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0, min_size=1, max_size=10)
    return pool

def get_now_naive():
    return datetime.datetime.now(JST).replace(tzinfo=None)

async def setup_db():
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                last_daily TIMESTAMP,
                chinchiro_count INTEGER DEFAULT 0,
                chinchiro_last_date TEXT,
                tc_xp INTEGER DEFAULT 0,
                tc_level INTEGER DEFAULT 1,
                vc_xp INTEGER DEFAULT 0,
                vc_level INTEGER DEFAULT 1,
                initial_issued BOOLEAN DEFAULT FALSE
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                channel_id BIGINT PRIMARY KEY,
                owner_id BIGINT,
                room_type TEXT,
                expire_at TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS evaluation_periods (
                user_id BIGINT PRIMARY KEY,
                start_time TIMESTAMP,
                end_time TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS auto_vc_triggers (
                channel_id BIGINT PRIMARY KEY
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS inquiry_panels (
                channel_id BIGINT PRIMARY KEY,
                mention_role_id BIGINT,
                mention_role_ids BIGINT[]
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS antigrief_settings (
                guild_id BIGINT PRIMARY KEY,
                target_category_ids BIGINT[],
                target_channel_ids BIGINT[],
                exempt_role_ids BIGINT[]
            )
        ''')
        try:
            await conn.execute('ALTER TABLE inquiry_panels ADD COLUMN IF NOT EXISTS mention_role_ids BIGINT[]')
        except Exception as e:
            print(f"[Migration] inquiry_panels migration warning: {e}")

        try:
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS initial_issued BOOLEAN DEFAULT FALSE')
        except Exception as e:
            print(f"[Migration] users initial_issued migration warning: {e}")

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS level_role_rewards (
                level_type VARCHAR(10),
                level INTEGER,
                role_id BIGINT,
                PRIMARY KEY (level_type, level, role_id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS room_prices (
                room_type VARCHAR(20),
                duration INTEGER,
                price INTEGER,
                PRIMARY KEY (room_type, duration)
            )
        ''')

        await conn.execute('''
            INSERT INTO room_prices (room_type, duration, price) VALUES
            ('宿', 12, 10000),
            ('宿', 24, 15000),
            ('高級宿', 12, 150000),
            ('高級宿', 24, 250000),
            ('カスタムVC', 24, 30000)
            ON CONFLICT (room_type, duration) DO NOTHING
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS anonymous_chats (
                panel_channel_id BIGINT PRIMARY KEY,
                dest_channel_id BIGINT
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS custom_ticket_panels (
                channel_id BIGINT PRIMARY KEY,
                panel_title TEXT NOT NULL,
                panel_description TEXT NOT NULL,
                button_label TEXT NOT NULL,
                button_emoji TEXT,
                mention_role_ids BIGINT[] NOT NULL,
                target_role_ids BIGINT[] NOT NULL,
                ticket_prefix TEXT NOT NULL
            )
        ''')
        try:
            await conn.execute("ALTER TABLE custom_ticket_panels ADD COLUMN IF NOT EXISTS button_label TEXT DEFAULT 'チケットを作成する'")
            await conn.execute("ALTER TABLE custom_ticket_panels ADD COLUMN IF NOT EXISTS button_emoji TEXT")
            await conn.execute("ALTER TABLE custom_ticket_panels ADD COLUMN IF NOT EXISTS target_role_ids BIGINT[] DEFAULT '{}'::BIGINT[]")
            await conn.execute("ALTER TABLE custom_ticket_panels ADD COLUMN IF NOT EXISTS ticket_prefix TEXT DEFAULT 'ticket'")
        except Exception as e:
            print(f"[Migration] custom_ticket_panels migration warning: {e}")

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS log_settings (
                guild_id BIGINT,
                log_type VARCHAR(50),
                channel_id BIGINT,
                PRIMARY KEY (guild_id, log_type)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS evaluation_settings (
                guild_id BIGINT PRIMARY KEY,
                forum_channel_ids BIGINT[],
                self_intro_channel_ids BIGINT[]
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS rank_settings (
                guild_id BIGINT PRIMARY KEY,
                whitelist_channel_ids BIGINT[] NOT NULL DEFAULT '{}',
                blacklist_channel_ids BIGINT[] NOT NULL DEFAULT '{}',
                whitelist_category_ids BIGINT[] NOT NULL DEFAULT '{}',
                blacklist_category_ids BIGINT[] NOT NULL DEFAULT '{}'
            )
        ''')
        try:
            await conn.execute('ALTER TABLE rank_settings ADD COLUMN IF NOT EXISTS whitelist_category_ids BIGINT[] NOT NULL DEFAULT \'{}\'')
        except Exception as e:
            print(f"[Migration] rank_settings migration warning: {e}")
        try:
            await conn.execute('ALTER TABLE rank_settings ADD COLUMN IF NOT EXISTS blacklist_category_ids BIGINT[] NOT NULL DEFAULT \'{}\'')
        except Exception as e:
            print(f"[Migration] rank_settings migration warning: {e}")
        try:
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS evaluation_vc_time INTEGER DEFAULT 0')
        except Exception as e:
            print(f"[Migration] users evaluation_vc_time migration warning: {e}")

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_evaluations (
                id SERIAL PRIMARY KEY,
                target_user_id BIGINT,
                evaluator_id BIGINT,
                result TEXT,
                created_at TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reaction_roles (
                message_id BIGINT,
                emoji TEXT,
                role_id BIGINT,
                PRIMARY KEY (message_id, emoji)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS interviewer_logs (
                interviewer_id BIGINT,
                target_user_id BIGINT,
                guild_id BIGINT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (interviewer_id, target_user_id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS sticky_templates (
                channel_id BIGINT PRIMARY KEY,
                title TEXT,
                content TEXT,
                last_message_id BIGINT
            )
        ''')
        try:
            await conn.execute('ALTER TABLE sticky_templates ADD COLUMN IF NOT EXISTS last_text_message_id BIGINT')
        except Exception as e:
            print(f"[Migration] sticky_templates migration warning: {e}")

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS shop_settings (
                guild_id BIGINT PRIMARY KEY,
                employee_role_id BIGINT,
                manager_role_id BIGINT
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                item_id SERIAL PRIMARY KEY,
                guild_id BIGINT,
                name TEXT,
                usage TEXT,
                target TEXT,
                price INTEGER DEFAULT 0
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_items (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                item_id INTEGER,
                purchased_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')


async def get_user(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT balance, chinchiro_count, chinchiro_last_date, tc_xp, tc_level, vc_xp, vc_level, evaluation_vc_time, initial_issued FROM users WHERE user_id = $1', user_id)
        if row:
            return {
                "balance": row['balance'], 
                "chinchiro_count": row['chinchiro_count'],
                "chinchiro_last_date": row['chinchiro_last_date'],
                "tc_xp": row['tc_xp'],
                "tc_level": row['tc_level'],
                "vc_xp": row['vc_xp'],
                "vc_level": row['vc_level'],
                "evaluation_vc_time": row['evaluation_vc_time'],
                "initial_issued": row['initial_issued']
            }
        else:
            await conn.execute('INSERT INTO users (user_id, balance, initial_issued) VALUES ($1, 0, FALSE) ON CONFLICT (user_id) DO NOTHING', user_id)
            return {"balance": 0, "chinchiro_count": 0, "chinchiro_last_date": None, "tc_xp": 0, "tc_level": 1, "vc_xp": 0, "vc_level": 1, "evaluation_vc_time": 0, "initial_issued": False}

async def get_balance(user_id: int) -> int:
    user = await get_user(user_id)
    return user["balance"]

async def add_balance(user_id: int, amount: int):
    await get_user(user_id)
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET balance = balance + $1 WHERE user_id = $2', amount, user_id)

async def remove_balance(user_id: int, amount: int) -> bool:
    current_balance = await get_balance(user_id)
    if current_balance < amount:
        return False
        
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET balance = balance - $1 WHERE user_id = $2', amount, user_id)
    return True

async def set_initial_issued(user_id: int):
    await get_user(user_id)
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET initial_issued = TRUE WHERE user_id = $1', user_id)

async def check_initial_issued(user_id: int) -> bool:
    user = await get_user(user_id)
    return user["initial_issued"]


async def reset_gambling_count(user_id: int, date_str: str):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET chinchiro_count = 0, chinchiro_last_date = $1 WHERE user_id = $2', date_str, user_id)

async def increment_gambling_count(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET chinchiro_count = chinchiro_count + 1 WHERE user_id = $1', user_id)

def get_next_level_xp(level: int) -> int:
    return int(100 * (level ** 1.2) + 100)

async def add_xp(user_id: int, amount: int, mode: str):
    await get_user(user_id)
    field_xp = "tc_xp" if mode == "tc" else "vc_xp"
    field_lv = "tc_level" if mode == "tc" else "vc_level"
    
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow(f'SELECT {field_xp}, {field_lv} FROM users WHERE user_id = $1', user_id)
        current_xp, current_lv = row[0], row[1]
        new_xp = current_xp + amount
        new_lv = current_lv
        leveled_up = False
        while True:
            needed = get_next_level_xp(new_lv)
            if new_xp >= needed:
                new_xp -= needed
                new_lv += 1
                leveled_up = True
            else:
                break
        await conn.execute(f'UPDATE users SET {field_xp} = $1, {field_lv} = $2 WHERE user_id = $3', new_xp, new_lv, user_id)
        return new_lv if leveled_up else None

async def add_room(channel_id: int, owner_id: int, room_type: str, expire_at: datetime.datetime):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('INSERT INTO rooms (channel_id, owner_id, room_type, expire_at) VALUES ($1, $2, $3, $4)', 
                         channel_id, owner_id, room_type, expire_at)

async def get_room(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT owner_id, room_type, expire_at FROM rooms WHERE channel_id = $1', channel_id)
        if row:
            return {"owner_id": row['owner_id'], "room_type": row['room_type'], "expire_at": row['expire_at']}
        return None

async def has_room_type(owner_id: int, room_types: list[str]) -> bool:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT 1 FROM rooms WHERE owner_id = $1 AND room_type = ANY($2) LIMIT 1', owner_id, room_types)
        return row is not None

async def remove_room(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM rooms WHERE channel_id = $1', channel_id)

async def extend_room(channel_id: int, new_expire_at: datetime.datetime):
    if new_expire_at.tzinfo:
        new_expire_at = new_expire_at.replace(tzinfo=None)
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE rooms SET expire_at = $1 WHERE channel_id = $2', new_expire_at, channel_id)

async def get_expired_rooms():
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT channel_id FROM rooms WHERE expire_at <= $1', get_now_naive())
        return [row['channel_id'] for row in rows]

# --- 管理用リセット関数 ---
async def get_top_users(mode: str, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    order_field = "tc_xp" if mode == "tc" else "vc_xp"
    level_field = "tc_level" if mode == "tc" else "vc_level"
    async with pool.acquire() as conn:
        rows = await conn.fetch(f'SELECT user_id, {order_field} as xp, {level_field} as level FROM users ORDER BY {level_field} DESC, {order_field} DESC LIMIT $1', limit)
        return [{"user_id": r["user_id"], "xp": r["xp"], "level": r["level"]} for r in rows]

async def reset_user_rank(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            UPDATE users 
            SET tc_xp = 0, tc_level = 1, vc_xp = 0, vc_level = 1, evaluation_vc_time = 0 
            WHERE user_id = $1
        ''', user_id)

async def reset_user_balance(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET balance = 0 WHERE user_id = $1', user_id)

# --- 評価期間管理用関数 ---
async def add_evaluation_period(user_id: int, start_time: datetime.datetime, end_time: datetime.datetime):
    if start_time.tzinfo:
        start_time = start_time.replace(tzinfo=None)
    if end_time.tzinfo:
        end_time = end_time.replace(tzinfo=None)
        
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO evaluation_periods (user_id, start_time, end_time) 
            VALUES ($1, $2, $3) 
            ON CONFLICT (user_id) DO NOTHING
        ''', user_id, start_time, end_time)

async def get_evaluation_period(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT start_time, end_time FROM evaluation_periods WHERE user_id = $1', user_id)
        if row:
            return {"start_time": row['start_time'], "end_time": row['end_time']}
        return None

async def get_all_evaluation_periods():
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT user_id, start_time, end_time FROM evaluation_periods ORDER BY end_time ASC')
        return [{"user_id": row['user_id'], "start_time": row['start_time'], "end_time": row['end_time']} for row in rows]

async def extend_evaluation_period(user_id: int, extra_days: int) -> bool:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT end_time FROM evaluation_periods WHERE user_id = $1', user_id)
        if not row:
            return False
            
        new_end_time = row['end_time'] + datetime.timedelta(days=extra_days)
        await conn.execute('UPDATE evaluation_periods SET end_time = $1 WHERE user_id = $2', new_end_time, user_id)
        return True

# --- VC作成トリガー管理用関数 ---
async def add_auto_vc_trigger(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('INSERT INTO auto_vc_triggers (channel_id) VALUES ($1) ON CONFLICT (channel_id) DO NOTHING', channel_id)

async def remove_auto_vc_trigger(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM auto_vc_triggers WHERE channel_id = $1', channel_id)

async def get_auto_vc_triggers() -> list[int]:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT channel_id FROM auto_vc_triggers')
        return [row['channel_id'] for row in rows]

# --- お問い合わせパネル管理用関数 ---
async def add_inquiry_panel(channel_id: int, mention_role_ids: list[int]):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO inquiry_panels (channel_id, mention_role_ids) 
            VALUES ($1, $2) 
            ON CONFLICT (channel_id) 
            DO UPDATE SET mention_role_ids = $2
        ''', channel_id, mention_role_ids)

async def get_inquiry_panel_roles(channel_id: int) -> list[int]:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT mention_role_ids, mention_role_id FROM inquiry_panels WHERE channel_id = $1', channel_id)
        if row:
            if row['mention_role_ids'] is not None:
                return row['mention_role_ids']
            elif row['mention_role_id'] is not None:
                return [row['mention_role_id']]
        return []

async def remove_inquiry_panel(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM inquiry_panels WHERE channel_id = $1', channel_id)

# --- Bot設定値管理用関数 ---
async def save_setting(key: str, value):
    p = await get_pool()
    val_json = json.dumps(value)
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO bot_settings (setting_key, setting_value)
            VALUES ($1, $2)
            ON CONFLICT (setting_key)
            DO UPDATE SET setting_value = $2
        ''', key, val_json)

async def load_settings() -> dict:
    p = await get_pool()
    settings = {}
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT setting_key, setting_value FROM bot_settings')
        for r in rows:
            try:
                settings[r['setting_key']] = json.loads(r['setting_value'])
            except Exception:
                pass
    return settings

# --- レベルロール報酬管理用関数 ---
async def add_level_role_reward(level_type: str, level: int, role_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO level_role_rewards (level_type, level, role_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (level_type, level, role_id) DO NOTHING
        ''', level_type, level, role_id)

async def get_level_role_rewards(level_type: str = None) -> list[dict]:
    p = await get_pool()
    async with p.acquire() as conn:
        if level_type:
            rows = await conn.fetch('''
                SELECT level_type, level, role_id 
                FROM level_role_rewards 
                WHERE level_type = $1 
                ORDER BY level ASC
            ''', level_type)
        else:
            rows = await conn.fetch('''
                SELECT level_type, level, role_id 
                FROM level_role_rewards 
                ORDER BY level_type ASC, level ASC
            ''')
        return [{"level_type": r["level_type"], "level": r["level"], "role_id": r["role_id"]} for r in rows]

async def remove_level_role_reward(level_type: str, level: int, role_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            DELETE FROM level_role_rewards 
            WHERE level_type = $1 AND level = $2 AND role_id = $3
        ''', level_type, level, role_id)

# --- 部屋価格管理用関数 ---
async def get_all_room_prices() -> list[dict]:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT room_type, duration, price FROM room_prices ORDER BY room_type ASC, duration ASC')
        return [{"room_type": r["room_type"], "duration": r["duration"], "price": r["price"]} for r in rows]

async def update_room_price(room_type: str, duration: int, price: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO room_prices (room_type, duration, price) 
            VALUES ($1, $2, $3)
            ON CONFLICT (room_type, duration) 
            DO UPDATE SET price = EXCLUDED.price
        ''', room_type, duration, price)

# --- 匿名チャット管理用関数 ---
async def add_anonymous_chat(panel_channel_id: int, dest_channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO anonymous_chats (panel_channel_id, dest_channel_id)
            VALUES ($1, $2)
            ON CONFLICT (panel_channel_id)
            DO UPDATE SET dest_channel_id = $2
        ''', panel_channel_id, dest_channel_id)

async def get_anonymous_chat(panel_channel_id: int) -> int:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT dest_channel_id FROM anonymous_chats WHERE panel_channel_id = $1', panel_channel_id)
        return row['dest_channel_id'] if row else None

async def remove_anonymous_chat(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM anonymous_chats WHERE panel_channel_id = $1 OR dest_channel_id = $1', channel_id)

# --- カスタムチケットパネル管理用関数 ---
async def add_custom_ticket_panel(
    channel_id: int,
    panel_title: str,
    panel_description: str,
    button_label: str,
    button_emoji: str,
    mention_role_ids: list[int],
    target_role_ids: list[int],
    ticket_prefix: str
):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO custom_ticket_panels (
                channel_id, panel_title, panel_description, button_label, button_emoji, mention_role_ids, target_role_ids, ticket_prefix
            ) 
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8) 
            ON CONFLICT (channel_id) 
            DO UPDATE SET 
                panel_title = $2,
                panel_description = $3,
                button_label = $4,
                button_emoji = $5,
                mention_role_ids = $6,
                target_role_ids = $7,
                ticket_prefix = $8
        ''', channel_id, panel_title, panel_description, button_label, button_emoji, mention_role_ids, target_role_ids, ticket_prefix)

async def get_custom_ticket_panel(channel_id: int) -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT panel_title, panel_description, button_label, button_emoji, mention_role_ids, target_role_ids, ticket_prefix 
            FROM custom_ticket_panels 
            WHERE channel_id = $1
        ''', channel_id)
        if row:
            return {
                "panel_title": row["panel_title"],
                "panel_description": row["panel_description"],
                "button_label": row["button_label"],
                "button_emoji": row["button_emoji"],
                "mention_role_ids": row["mention_role_ids"] or [],
                "target_role_ids": row["target_role_ids"] or [],
                "ticket_prefix": row["ticket_prefix"] or "ticket"
            }
        return None

async def remove_custom_ticket_panel(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM custom_ticket_panels WHERE channel_id = $1', channel_id)


async def set_log_channel(guild_id: int, log_type: str, channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO log_settings (guild_id, log_type, channel_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, log_type)
            DO UPDATE SET channel_id = $3
        ''', guild_id, log_type, channel_id)

async def get_log_channel(guild_id: int, log_type: str) -> int:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT channel_id FROM log_settings WHERE guild_id = $1 AND log_type = $2', guild_id, log_type)
        return row['channel_id'] if row else None

async def get_all_log_settings(guild_id: int) -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT log_type, channel_id FROM log_settings WHERE guild_id = $1', guild_id)
        return {row['log_type']: row['channel_id'] for row in rows}

async def remove_log_channel(guild_id: int, log_type: str):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM log_settings WHERE guild_id = $1 AND log_type = $2', guild_id, log_type)


# --- 自己紹介・評価設定管理用関数 ---
async def get_evaluation_settings(guild_id: int) -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT forum_channel_ids, self_intro_channel_ids FROM evaluation_settings WHERE guild_id = $1', guild_id)
        if row:
            return {
                "forum_channel_ids": row["forum_channel_ids"] or [],
                "self_intro_channel_ids": row["self_intro_channel_ids"] or []
            }
        return None

async def get_all_evaluation_settings() -> list[dict]:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT guild_id, forum_channel_ids, self_intro_channel_ids FROM evaluation_settings')
        return [{"guild_id": r["guild_id"], "forum_channel_ids": r["forum_channel_ids"] or [], "self_intro_channel_ids": r["self_intro_channel_ids"] or []} for r in rows]

async def set_evaluation_settings(guild_id: int, forum_channel_ids: list[int], self_intro_channel_ids: list[int]):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO evaluation_settings (guild_id, forum_channel_ids, self_intro_channel_ids)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id)
            DO UPDATE SET forum_channel_ids = $2, self_intro_channel_ids = $3
        ''', guild_id, forum_channel_ids, self_intro_channel_ids)


# --- ランク対象設定管理用関数 ---
async def get_rank_settings(guild_id: int) -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT whitelist_channel_ids, blacklist_channel_ids, whitelist_category_ids, blacklist_category_ids FROM rank_settings WHERE guild_id = $1', guild_id)
        if row:
            return {
                "whitelist": row["whitelist_channel_ids"] or [],
                "blacklist": row["blacklist_channel_ids"] or [],
                "whitelist_categories": row["whitelist_category_ids"] or [],
                "blacklist_categories": row["blacklist_category_ids"] or []
            }
        else:
            await conn.execute('INSERT INTO rank_settings (guild_id, whitelist_channel_ids, blacklist_channel_ids, whitelist_category_ids, blacklist_category_ids) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (guild_id) DO NOTHING', guild_id, [], [], [], [])
            return {"whitelist": [], "blacklist": [], "whitelist_categories": [], "blacklist_categories": []}

async def get_all_rank_settings() -> list[dict]:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT guild_id, whitelist_channel_ids, blacklist_channel_ids, whitelist_category_ids, blacklist_category_ids FROM rank_settings')
        return [
            {
                "guild_id": r["guild_id"],
                "whitelist": r["whitelist_channel_ids"] or [],
                "blacklist": r["blacklist_channel_ids"] or [],
                "whitelist_categories": r["whitelist_category_ids"] or [],
                "blacklist_categories": r["blacklist_category_ids"] or []
            }
            for r in rows
        ]

async def set_rank_settings(guild_id: int, whitelist_ids: list[int], blacklist_ids: list[int], whitelist_cat_ids: list[int], blacklist_cat_ids: list[int]):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO rank_settings (guild_id, whitelist_channel_ids, blacklist_channel_ids, whitelist_category_ids, blacklist_category_ids)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id)
            DO UPDATE SET whitelist_channel_ids = $2, blacklist_channel_ids = $3, whitelist_category_ids = $4, blacklist_category_ids = $5
        ''', guild_id, whitelist_ids, blacklist_ids, whitelist_cat_ids, blacklist_cat_ids)

async def add_evaluation_vc_time(user_id: int, seconds: int):
    await get_user(user_id)
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET evaluation_vc_time = evaluation_vc_time + $1 WHERE user_id = $2', seconds, user_id)

# --- ユーザー評価結果管理用関数 ---
async def add_user_evaluation(target_user_id: int, evaluator_id: int, result: str):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_evaluations (target_user_id, evaluator_id, result, created_at)
            VALUES ($1, $2, $3, $4)
        ''', target_user_id, evaluator_id, result, get_now_naive())

async def get_user_evaluation_counts(target_user_id: int) -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('''
            SELECT result, COUNT(*) as count
            FROM user_evaluations
            WHERE target_user_id = $1
            GROUP BY result
        ''', target_user_id)
        return {r['result']: r['count'] for r in rows}

async def add_reaction_role(message_id: int, emoji: str, role_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO reaction_roles (message_id, emoji, role_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (message_id, emoji) DO UPDATE SET role_id = EXCLUDED.role_id
        ''', message_id, emoji, role_id)

async def remove_reaction_role(message_id: int, emoji: str):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM reaction_roles WHERE message_id = $1 AND emoji = $2', message_id, emoji)

# --- 常設テンプレート(Sticky Template)管理用関数 ---
async def get_sticky_template(channel_id: int) -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT title, content, last_message_id, last_text_message_id FROM sticky_templates WHERE channel_id = $1', channel_id)
        if row:
            return {
                "title": row["title"],
                "content": row["content"],
                "last_message_id": row["last_message_id"],
                "last_text_message_id": row["last_text_message_id"] if "last_text_message_id" in row else None
            }
        return None

async def set_sticky_template(channel_id: int, title: str, content: str):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO sticky_templates (channel_id, title, content, last_message_id, last_text_message_id)
            VALUES ($1, $2, $3, NULL, NULL)
            ON CONFLICT (channel_id)
            DO UPDATE SET title = EXCLUDED.title, content = EXCLUDED.content, last_message_id = NULL, last_text_message_id = NULL
        ''', channel_id, title, content)

async def update_sticky_last_message(channel_id: int, message_id: int, text_message_id: int = None):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            UPDATE sticky_templates SET last_message_id = $2, last_text_message_id = $3 WHERE channel_id = $1
        ''', channel_id, message_id, text_message_id)

async def delete_sticky_template(channel_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM sticky_templates WHERE channel_id = $1', channel_id)


async def get_reaction_role(message_id: int, emoji: str):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT role_id FROM reaction_roles WHERE message_id = $1 AND emoji = $2', message_id, emoji)
        return row['role_id'] if row else None


async def add_interviewer_log(interviewer_id: int, target_user_id: int, guild_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO interviewer_logs (interviewer_id, target_user_id, guild_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (interviewer_id, target_user_id) DO NOTHING
        ''', interviewer_id, target_user_id, guild_id)

async def get_interviewer_count(interviewer_id: int) -> int:
    p = await get_pool()
    async with p.acquire() as conn:
        val = await conn.fetchval('SELECT COUNT(*) FROM interviewer_logs WHERE interviewer_id = $1', interviewer_id)
        return val or 0

# --- 荒らし対策設定管理用関数 ---
async def get_antigrief_settings(guild_id: int) -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT target_category_ids, target_channel_ids, exempt_role_ids FROM antigrief_settings WHERE guild_id = $1', guild_id)
        if row:
            return {
                "categories": row["target_category_ids"] or [],
                "channels": row["target_channel_ids"] or [],
                "exempt_roles": row["exempt_role_ids"] or []
            }
        else:
            await conn.execute('INSERT INTO antigrief_settings (guild_id, target_category_ids, target_channel_ids, exempt_role_ids) VALUES ($1, $2, $3, $4) ON CONFLICT (guild_id) DO NOTHING', guild_id, [], [], [])
            return {"categories": [], "channels": [], "exempt_roles": []}

async def get_all_antigrief_settings() -> list[dict]:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT guild_id, target_category_ids, target_channel_ids, exempt_role_ids FROM antigrief_settings')
        return [
            {
                "guild_id": r["guild_id"],
                "categories": r["target_category_ids"] or [],
                "channels": r["target_channel_ids"] or [],
                "exempt_roles": r["exempt_role_ids"] or []
            }
            for r in rows
        ]

async def set_antigrief_settings(guild_id: int, category_ids: list[int], channel_ids: list[int], exempt_role_ids: list[int]):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO antigrief_settings (guild_id, target_category_ids, target_channel_ids, exempt_role_ids)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id)
            DO UPDATE SET target_category_ids = $2, target_channel_ids = $3, exempt_role_ids = $4
        ''', guild_id, category_ids, channel_ids, exempt_role_ids)

async def update_antigrief_settings_list(guild_id: int, field_type: str, item_id: int, action: str):
    cfg = await get_antigrief_settings(guild_id)
    if field_type == "categories":
        target = cfg["categories"]
    elif field_type == "channels":
        target = cfg["channels"]
    elif field_type == "exempt_roles":
        target = cfg["exempt_roles"]
    else:
        return

    if action == "add":
        if item_id not in target:
            target.append(item_id)
    elif action == "remove":
        if item_id in target:
            target.remove(item_id)

    await set_antigrief_settings(guild_id, cfg["categories"], cfg["channels"], cfg["exempt_roles"])

async def clear_antigrief_settings_field(guild_id: int, field_name: str):
    cfg = await get_antigrief_settings(guild_id)
    if field_name == "target_category_ids":
        cfg["categories"] = []
    elif field_name == "target_channel_ids":
        cfg["channels"] = []
    elif field_name == "exempt_role_ids":
        cfg["exempt_roles"] = []
    else:
        return

    await set_antigrief_settings(guild_id, cfg["categories"], cfg["channels"], cfg["exempt_roles"])

# ショップ設定関連
async def get_shop_settings(guild_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT employee_role_id, manager_role_id FROM shop_settings WHERE guild_id = $1', guild_id)
        if row:
            return {"employee_role_id": row["employee_role_id"], "manager_role_id": row["manager_role_id"]}
        else:
            return {"employee_role_id": None, "manager_role_id": None}

async def set_shop_settings(guild_id: int, employee_role_id: int, manager_role_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO shop_settings (guild_id, employee_role_id, manager_role_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE SET
            employee_role_id = EXCLUDED.employee_role_id,
            manager_role_id = EXCLUDED.manager_role_id
        ''', guild_id, employee_role_id, manager_role_id)

# ショップ商品関連
async def get_shop_items(guild_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT item_id, name, usage, target, price FROM shop_items WHERE guild_id = $1 ORDER BY item_id ASC', guild_id)
        return [dict(r) for r in rows]

async def get_shop_item(item_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT item_id, guild_id, name, usage, target, price FROM shop_items WHERE item_id = $1', item_id)
        return dict(row) if row else None

async def add_shop_item(guild_id: int, name: str, usage: str, target: str, price: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO shop_items (guild_id, name, usage, target, price)
            VALUES ($1, $2, $3, $4, $5)
        ''', guild_id, name, usage, target, price)

async def update_shop_item(item_id: int, name: str, usage: str, target: str, price: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            UPDATE shop_items SET name = $1, usage = $2, target = $3, price = $4 WHERE item_id = $5
        ''', name, usage, target, price, item_id)

async def delete_shop_item(item_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM shop_items WHERE item_id = $1', item_id)

# ユーザー購入履歴関連
async def add_user_item(user_id: int, item_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO user_items (user_id, item_id, purchased_at)
            VALUES ($1, $2, CURRENT_TIMESTAMP)
        ''', user_id, item_id)

async def get_user_items(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('''
            SELECT u.id, u.item_id, s.name, u.purchased_at
            FROM user_items u
            JOIN shop_items s ON u.item_id = s.item_id
            WHERE u.user_id = $1
            ORDER BY u.purchased_at DESC
        ''', user_id)
        return [dict(r) for r in rows]
