import asyncpg
import datetime
import os
import asyncio
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
                vc_level INTEGER DEFAULT 1
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
        try:
            await conn.execute('ALTER TABLE inquiry_panels ADD COLUMN IF NOT EXISTS mention_role_ids BIGINT[]')
        except Exception as e:
            print(f"[Migration] inquiry_panels migration warning: {e}")

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


async def get_user(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT balance, chinchiro_count, chinchiro_last_date, tc_xp, tc_level, vc_xp, vc_level FROM users WHERE user_id = $1', user_id)
        if row:
            return {
                "balance": row['balance'], 
                "chinchiro_count": row['chinchiro_count'],
                "chinchiro_last_date": row['chinchiro_last_date'],
                "tc_xp": row['tc_xp'],
                "tc_level": row['tc_level'],
                "vc_xp": row['vc_xp'],
                "vc_level": row['vc_level']
            }
        else:
            await conn.execute('INSERT INTO users (user_id, balance) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING', user_id)
            return {"balance": 0, "chinchiro_count": 0, "chinchiro_last_date": None, "tc_xp": 0, "tc_level": 1, "vc_xp": 0, "vc_level": 1}

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
async def reset_user_rank(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            UPDATE users 
            SET tc_xp = 0, tc_level = 1, vc_xp = 0, vc_level = 1 
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


