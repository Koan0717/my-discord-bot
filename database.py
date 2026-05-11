import aiosqlite
import datetime

DB_NAME = "economy.db"

async def setup_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
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
        async with db.execute('SELECT balance, last_daily, chinchiro_count, chinchiro_last_date, tc_xp, tc_level, vc_xp, vc_level FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "balance": row[0], 
                    "last_daily": row[1],
                    "chinchiro_count": row[2],
                    "chinchiro_last_date": row[3],
                    "tc_xp": row[4],
                    "tc_level": row[5],
                    "vc_xp": row[6],
                    "vc_level": row[7]
                }
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

async def reset_gambling_count(user_id: int, date_str: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET chinchiro_count = 0, chinchiro_last_date = ? WHERE user_id = ?', (date_str, user_id))
        await db.commit()

async def increment_gambling_count(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET chinchiro_count = chinchiro_count + 1 WHERE user_id = ?', (user_id,))
        await db.commit()

# --- Rank System ---

def get_next_level_xp(level: int) -> int:
    """次のレベルに必要な累計ではなく、そのレベル単体で必要なXPを返す"""
    return int(100 * (level ** 1.2) + 100)

async def add_xp(user_id: int, amount: int, mode: str):
    """XPを加算し、レベルアップした場合は新しいレベルを返す。それ以外はNone"""
    await get_user(user_id) # ユーザー作成確認
    
    field_xp = "tc_xp" if mode == "tc" else "vc_xp"
    field_lv = "tc_level" if mode == "tc" else "vc_level"
    
    async with aiosqlite.connect(DB_NAME) as db:
        # 現在のXPとレベルを取得
        async with db.execute(f'SELECT {field_xp}, {field_lv} FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            current_xp, current_lv = row
            
        new_xp = current_xp + amount
        new_lv = current_lv
        leveled_up = False
        
        # レベルアップ判定（複数レベル上がる可能性も考慮）
        while True:
            needed = get_next_level_xp(new_lv)
            if new_xp >= needed:
                new_xp -= needed
                new_lv += 1
                leveled_up = True
            else:
                break
        
        await db.execute(f'UPDATE users SET {field_xp} = ?, {field_lv} = ? WHERE user_id = ?', (new_xp, new_lv, user_id))
        await db.commit()
        
        return new_lv if leveled_up else None

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
