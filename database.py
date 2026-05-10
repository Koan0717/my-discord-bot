import aiosqlite
import datetime

DB_NAME = "economy.db"

async def setup_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                last_daily TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                channel_id INTEGER PRIMARY KEY,
                owner_id INTEGER,
                room_type TEXT,
                expire_at TIMESTAMP
            )
        ''')
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT balance, last_daily FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"balance": row[0], "last_daily": row[1]}
            else:
                # ユーザーが存在しない場合は初期化
                await db.execute('INSERT INTO users (user_id, balance) VALUES (?, 0)', (user_id,))
                await db.commit()
                return {"balance": 0, "last_daily": None}

async def get_balance(user_id: int) -> int:
    user = await get_user(user_id)
    return user["balance"]

async def add_balance(user_id: int, amount: int):
    # まずユーザーを作成/取得
    await get_user(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
        await db.commit()

async def remove_balance(user_id: int, amount: int) -> bool:
    """残高を減らす。残高不足の場合はFalseを返す"""
    current_balance = await get_balance(user_id)
    if current_balance < amount:
        return False
        
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
        await db.commit()
    return True

async def update_last_daily(user_id: int, timestamp: datetime.datetime):
    await get_user(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET last_daily = ? WHERE user_id = ?', (timestamp.isoformat(), user_id))
        await db.commit()

# --- Room Management ---
async def add_room(channel_id: int, owner_id: int, room_type: str, expire_at: datetime.datetime):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT INTO rooms (channel_id, owner_id, room_type, expire_at) VALUES (?, ?, ?, ?)', 
                         (channel_id, owner_id, room_type, expire_at.isoformat()))
        await db.commit()

async def get_room(channel_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT owner_id, room_type, expire_at FROM rooms WHERE channel_id = ?', (channel_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"owner_id": row[0], "room_type": row[1], "expire_at": datetime.datetime.fromisoformat(row[2])}
            return None

async def has_room_type(owner_id: int, room_types: list[str]) -> bool:
    placeholders = ','.join('?' for _ in room_types)
    query = f'SELECT 1 FROM rooms WHERE owner_id = ? AND room_type IN ({placeholders}) LIMIT 1'
    params = [owner_id] + room_types
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(query, tuple(params)) as cursor:
            row = await cursor.fetchone()
            return row is not None

async def remove_room(channel_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM rooms WHERE channel_id = ?', (channel_id,))
        await db.commit()

async def extend_room(channel_id: int, new_expire_at: datetime.datetime):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE rooms SET expire_at = ? WHERE channel_id = ?', (new_expire_at.isoformat(), channel_id))
        await db.commit()

async def get_expired_rooms():
    now = datetime.datetime.now().isoformat()
    expired = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT channel_id FROM rooms WHERE expire_at <= ?', (now,)) as cursor:
            async for row in cursor:
                expired.append(row[0])
    return expired
