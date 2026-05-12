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
        # pgbouncer (Pooler) を使っているため、statement_cache_size=0 を設定
        pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0, min_size=1, max_size=10)
    return pool

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
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE rooms SET expire_at = $1 WHERE channel_id = $2', new_expire_at, channel_id)

async def get_expired_rooms():
    now = datetime.datetime.now(JST)
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch('SELECT channel_id FROM rooms WHERE expire_at <= $1', now)
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
