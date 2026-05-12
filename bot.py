import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import random
import datetime
import asyncio
from dotenv import load_dotenv
import database
from keep_alive import keep_alive

# --- 設定 ---
CURRENCY_NAME = "コイン"
JST = datetime.timezone(datetime.timedelta(hours=9))

# 獲得量の設定
MSG_COOLDOWN = 60     # メッセージ獲得のクールダウン（秒）


# 経験値の設定
TC_XP_REWARD = 10      # メッセージ1通あたりのXP
TC_XP_COOLDOWN = 10    # TC XP獲得のクールダウン（秒）
VC_XP_PER_MIN = 15     # VC滞在1分あたりのXP
LEVEL_UP_CHANNEL_ID = 1503480861105066024

# 部屋作成の設定
ROOM_SETTINGS = {
    "宿": {"price": 10000, "duration_hours": 12},
    "高級宿": {"price": 30000, "duration_hours": 24},
    "カスタムVC": {"price": 30000, "duration_hours": 24}
}
CREATE_VC_CHANNEL_ID = 1503789689184714902

# 面接・入界設定
NEW_MEMBER_ROLE_NAME = "人間"
PENDING_MEMBER_ROLE_NAME = "入界待機者"
INTERVIEWER_ROLE_NAMES = ["最高亡魂導師", "亡魂導師"]
FREE_INN_ROLE_NAME = "死者"
EMBLEM_MANAGER_ROLE_NAME = "紋章師統括"
EMBLEM_MASTER_ROLE_NAME = "紋章師"
INITIAL_COINS = 30000

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
        self.empty_custom_vcs = {}  # {channel_id: empty_since_timestamp}

    async def setup_hook(self):
        await database.setup_db()
        self.add_view(RoomView())
        self.add_view(CustomRoomView())
        self.add_view(InnControlView())
        self.add_view(RoomControlView())
        self.add_view(CustomRoomControlView())
        self.add_view(ChinchiroView())
        self.add_view(CoinflipView())
        self.add_view(SlotView())
        self.add_view(InterviewPanelView())
        self.add_view(EmblemRequestPanelView())
        self.add_view(TicketControlView())
        
        # グループの登録
        self.tree.add_command(AdminGroup())
        self.tree.add_command(InterviewerGroup())
        
        await self.tree.sync()
        self.check_expired_rooms.start()
        self.vc_reward_loop.start()
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
            # 全てのサーバーからユーザーを探す（大規模でなければこれでOK）
            for guild in self.guilds:
                m = guild.get_member(user_id)
                if m and m.voice and m.voice.channel:
                    member = m
                    break
            
            if member:
                elapsed_minutes = int((now - last_reward_time).total_seconds() / 60)
                if elapsed_minutes >= 1:
                    xp_reward = elapsed_minutes * VC_XP_PER_MIN
                    
                    new_lv = await database.add_xp(user_id, xp_reward, "vc")
                    
                    # 更新
                    self.vc_sessions[user_id] = now
                    
                    if new_lv:
                        lv_channel = self.get_channel(LEVEL_UP_CHANNEL_ID)
                        if lv_channel:
                            await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
            else:
                # ユーザーがどのVCにもいない、またはオフライン
                self.vc_sessions.pop(user_id, None)

bot = EconomyBot()

# --- イベント ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    user_id = message.author.id
    now = datetime.datetime.now(JST)

    # 1. 通貨報酬の判定 (廃止済み)
    # 2. TC経験値の判定 (クールダウンを短く設定)
    last_xp_time = bot.tc_xp_cooldowns.get(user_id)
    if not last_xp_time or (now - last_xp_time).total_seconds() > TC_XP_COOLDOWN:
        new_lv = await database.add_xp(user_id, TC_XP_REWARD, "tc")
        bot.tc_xp_cooldowns[user_id] = now
        if new_lv:
            lv_channel = bot.get_channel(LEVEL_UP_CHANNEL_ID)
            if lv_channel:
                await lv_channel.send(f"🎊 {message.author.mention} が **TCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
    
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        if member.bot: return
        user_id = member.id
        now = datetime.datetime.now(JST)

        # VCに参加・移動した時
        if after.channel is not None:
            # 入室・移動を検知
            is_join = before.channel is None or before.channel.id != after.channel.id
            if is_join:
                bot.vc_sessions[user_id] = now
                print(f"[VC-Join] {member.display_name} joined {after.channel.name}")
            
            # --- 自動VC作成ロジック ---
            if after.channel.id == CREATE_VC_CHANNEL_ID:
                try:
                    print(f"[Auto-VC] Triggered for {member.display_name}")
                    pool = await database.get_pool()
                    async with pool.acquire() as conn:
                        existing_room = await conn.fetchrow('SELECT channel_id FROM rooms WHERE owner_id = $1 AND room_type = $2', member.id, "一時部屋")
                    
                    if existing_room:
                        existing_channel = bot.get_channel(existing_room["channel_id"])
                        if not existing_channel:
                            try: existing_channel = await bot.fetch_channel(existing_room["channel_id"])
                            except: pass
                        
                        if existing_channel:
                            print(f"[Auto-VC] Existing room found ({existing_channel.id}), moving user...")
                            await asyncio.sleep(1)
                            try:
                                await member.move_to(existing_channel)
                                print(f"[Auto-VC] Successfully moved {member.display_name} to existing room")
                            except Exception as e:
                                print(f"[Auto-VC] Move to existing failed: {e}")
                            return
                        else:
                            await database.remove_room(existing_room["channel_id"])

                    guild = member.guild
                    category = after.channel.category
                    
                    channel_name = f"🔊│{member.display_name}の部屋"
                    new_channel = await guild.create_voice_channel(
                        name=channel_name,
                        category=category,
                        reason=f"Auto-VC for {member.display_name}"
                    )
                    
                    # 確実にDBに保存されるのを待つ
                    far_future = now + datetime.timedelta(days=36500)
                    await database.add_room(new_channel.id, member.id, "一時部屋", far_future)
                    print(f"[Auto-VC] Created room {new_channel.id} and registered in DB")
                    
                    # ユーザーを移動 (複数回試行)
                    for i in range(3):
                        await asyncio.sleep(1.5)
                        if member.voice and member.voice.channel and member.voice.channel.id == CREATE_VC_CHANNEL_ID:
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
                    err_msg = f"❌ [Auto-VC作成エラー]\n作成者: {member.display_name}\nエラー内容: {e}"
                    print(err_msg)
                    try: await after.channel.send(err_msg)
                    except: pass
            # ------------------------

            # カスタムVCへの入室であれば、無人タイマーを解除
            bot.empty_custom_vcs.pop(after.channel.id, None)
        
        # VCから退出・移動した時
        if before.channel is not None and (after.channel is None or before.channel != after.channel):
            join_time = bot.vc_sessions.pop(user_id, None)
            if join_time:
                duration_minutes = int((now - join_time).total_seconds() / 60)
                if duration_minutes > 0:
                    xp_reward = duration_minutes * VC_XP_PER_MIN
                    new_lv = await database.add_xp(user_id, xp_reward, "vc")
                    if new_lv:
                        lv_channel = bot.get_channel(LEVEL_UP_CHANNEL_ID)
                        if lv_channel:
                            await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
            
            # 退出した部屋が無人になった場合
            if len(before.channel.members) == 0:
                room_data = await database.get_room(before.channel.id)
                if room_data:
                    if room_data["room_type"] == "一時部屋":
                        try:
                            print(f"[Auto-VC] Deleting empty room: {before.channel.name}")
                            await before.channel.delete()
                            await database.remove_room(before.channel.id)
                        except Exception as del_e:
                            print(f"[Auto-VC] Delete error: {del_e}")
                    elif room_data["room_type"] == "カスタムVC":
                        bot.empty_custom_vcs[before.channel.id] = now
    except Exception as global_e:
        print(f"CRITICAL ERROR in on_voice_state_update: {global_e}")

@bot.event
async def on_guild_channel_delete(channel):
    # 手動でチャンネルが削除された場合、データベースからも消去する
    room_data = await database.get_room(channel.id)
    if room_data:
        await database.remove_room(channel.id)
        bot.empty_custom_vcs.pop(channel.id, None)

# --- 運営権限チェック ---
ADMIN_ROLE_NAMES = ["大魔王", "黒棺秘書官", "機巧墓守"]

def is_admin():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild:
            return False
        user_role_names = [role.name for role in interaction.user.roles]
        if any(role_name in ADMIN_ROLE_NAMES for role_name in user_role_names):
            return True
        await interaction.response.send_message("このコマンドを実行する権限がありません（運営専用ロールが必要です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)

def has_admin_role(user: discord.Member):
    return any(role.name in ADMIN_ROLE_NAMES for role in user.roles)

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

@bot.tree.command(name="pay", description="他のユーザーに通貨を送ります")
async def pay(interaction: discord.Interaction, target: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
        return
    if target.id == interaction.user.id:
        await interaction.response.send_message("自分自身には送金できません。", ephemeral=True)
        return
    if target.bot:
        await interaction.response.send_message("Botには送金できません。", ephemeral=True)
        return
    success = await database.remove_balance(interaction.user.id, amount)
    if not success:
        await interaction.response.send_message("残高が不足しています。", ephemeral=True)
        return
    await database.add_balance(target.id, amount)
    await interaction.response.send_message(f"{target.mention} に **{amount} {CURRENCY_NAME}** を送金しました！")

@bot.tree.command(name="rank", description="自分または他ユーザーのランク（レベル）を表示します")
async def rank(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    user_data = await database.get_user(target_user.id)
    tc_xp, tc_lv = user_data["tc_xp"], user_data["tc_level"]
    vc_xp, vc_lv = user_data["vc_xp"], user_data["vc_level"]
    tc_next = database.get_next_level_xp(tc_lv)
    vc_next = database.get_next_level_xp(vc_lv)
    def create_progress_bar(current, total):
        pct = min(current / total, 1.0)
        filled = int(pct * 10)
        return "■" * filled + "□" * (10 - filled) + f" ({int(pct*100)}%)"
    embed = discord.Embed(title=f"📊 {target_user.display_name} のランク情報", color=discord.Color.blue())
    if target_user.avatar: embed.set_thumbnail(url=target_user.avatar.url)
    embed.add_field(name=f"💬 TCランク (Lv.{tc_lv})", value=f"XP: {tc_xp} / {tc_next} (あと {tc_next - tc_xp} XP)\n`{create_progress_bar(tc_xp, tc_next)}`", inline=False)
    embed.add_field(name=f"🎙️ VCランク (Lv.{vc_lv})", value=f"XP: {vc_xp} / {vc_next} (あと {vc_next - vc_xp} XP)\n`{create_progress_bar(vc_xp, vc_next)}`", inline=False)
    await interaction.response.send_message(embed=embed)

# --- VCコントロールパネル系 ---

async def handle_extend(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    room_data = await database.get_room(channel_id)
    if not room_data:
        await interaction.response.send_message("この部屋のデータが見つかりません。", ephemeral=True)
        return
    if interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("延長は作成者または管理者のみ可能です。", ephemeral=True)
        return
    settings = ROOM_SETTINGS.get(room_data["room_type"])
    price, duration = settings["price"], settings["duration_hours"]
    success = await database.remove_balance(interaction.user.id, price)
    if not success:
        await interaction.response.send_message(f"残高が不足しています！(必要: {price} {CURRENCY_NAME})", ephemeral=True)
        return
    new_expire = room_data["expire_at"] + datetime.timedelta(hours=duration)
    await database.extend_room(channel_id, new_expire)
    await interaction.response.send_message(f"**{price} {CURRENCY_NAME}** を支払い、時間を {duration} 時間延長しました！\n新しい終了予定時刻: <t:{int(new_expire.timestamp())}:F>")

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
        new_role = discord.utils.get(interaction.guild.roles, name=NEW_MEMBER_ROLE_NAME)
        pending_role = discord.utils.get(interaction.guild.roles, name=PENDING_MEMBER_ROLE_NAME)
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
            await interaction.followup.send(f"✅ 完了！名前を「{self.name_input.value}」にし、{INITIAL_COINS} {CURRENCY_NAME} を発行しました。", ephemeral=True)
        except: await interaction.followup.send("エラー: 権限不足です。Botのロール順位を確認してください。", ephemeral=True)

class InterviewPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="入界手続きを開始", style=discord.ButtonStyle.success, emoji="📝", custom_id="persistent_interview_btn")
    async def start_button(self, interaction, button): await interaction.response.send_modal(InterviewNicknameModal())

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
        
        # 管理・紋章師系ロールにも権限を付与
        for role_name in ADMIN_ROLE_NAMES + [EMBLEM_MANAGER_ROLE_NAME, EMBLEM_MASTER_ROLE_NAME]:
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
            
            # 管理・統括・紋章師をメンション（通知用）
            mentions = []
            for role_name in ADMIN_ROLE_NAMES + [EMBLEM_MANAGER_ROLE_NAME, EMBLEM_MASTER_ROLE_NAME]:
                role = discord.utils.get(guild.roles, name=role_name)
                if role: mentions.append(role.mention)
            
            mention_str = " ".join(mentions)
            await ticket_channel.send(content=f"{interaction.user.mention} {self.target_member.mention} {mention_str}", embed=embed, view=TicketControlView())
            
            await interaction.followup.send(f"✅ チケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class EmblemSelectView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=60)
        # 「紋章師」と「紋章師統括」ロールを持つメンバーを取得
        master_role = discord.utils.get(guild.roles, name=EMBLEM_MASTER_ROLE_NAME)
        manager_role = discord.utils.get(guild.roles, name=EMBLEM_MANAGER_ROLE_NAME)
        
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
            self.add_item(discord.ui.Button(label="現在、依頼可能な紋章師がいません", disabled=True))
        else:
            select = discord.ui.Select(
                placeholder="担当する紋章師を選択してください...",
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

async def process_room_purchase(interaction: discord.Interaction, room_type: str, is_confirm_view: bool = False):
    await interaction.response.defer(ephemeral=True)
    owner_id = interaction.user.id
    if room_type in ["宿", "高級宿"] and await database.has_room_type(owner_id, ["宿", "高級宿"]):
        return await interaction.edit_original_response(content="既に「宿」を持っています！(1人1つまで)")
    if room_type == "カスタムVC" and await database.has_room_type(owner_id, ["カスタムVC"]):
        return await interaction.edit_original_response(content="既に「カスタムVC」を持っています！")
    
    settings = ROOM_SETTINGS[room_type]
    price, duration = settings["price"], settings["duration_hours"]
    
    # 死者ロールによる無料化
    user_roles = [r.name for r in interaction.user.roles]
    if room_type == "宿" and FREE_INN_ROLE_NAME in user_roles:
        price = 0

    if await database.get_balance(owner_id) < price:
        return await interaction.edit_original_response(content="残高が不足しています。")
    
    if price == 0 or await database.remove_balance(owner_id, price):
        try:
            overwrites = { interaction.guild.default_role: discord.PermissionOverwrite(connect=True),
                           interaction.user: discord.PermissionOverwrite(manage_channels=True, move_members=True) }
            if room_type == "高級宿": overwrites[interaction.user].manage_permissions = True
            channel = await interaction.guild.create_voice_channel(name=f"{room_type}-{interaction.user.display_name}", category=interaction.channel.category, overwrites=overwrites, user_limit=(2 if room_type=="宿" else 0))
            expire_at = datetime.datetime.now(JST) + datetime.timedelta(hours=duration)
            await database.add_room(channel.id, owner_id, room_type, expire_at)
            await interaction.edit_original_response(content=f"✅ {channel.mention} を作成しました！", view=None)
            view = CustomRoomControlView() if room_type=="カスタムVC" else (RoomControlView() if room_type=="高級宿" else InnControlView())
            embed = discord.Embed(title=f"🏠 {room_type}", description=f"作成者: {interaction.user.mention}\n終了予定: <t:{int(expire_at.timestamp())}:F>", color=discord.Color.blue())
            await channel.send(content=f"{interaction.user.mention}", embed=embed, view=view)
        except Exception as e:
            await database.add_balance(owner_id, price)
            await interaction.edit_original_response(content=f"エラー: {e}")

class RoomConfirmView(discord.ui.View):
    def __init__(self, room_type): super().__init__(timeout=60); self.room_type = room_type
    @discord.ui.button(label="確定", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction, button): await process_room_purchase(interaction, self.room_type, True)
    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction, button): await interaction.response.edit_message(content="キャンセルしました。", view=None)

class RoomView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="宿", style=discord.ButtonStyle.primary, emoji="🛖", custom_id="persistent_inn_btn")
    async def inn(self, it, btn):
        user_roles = [r.name for r in it.user.roles]
        price = ROOM_SETTINGS['宿']['price']
        if FREE_INN_ROLE_NAME in user_roles:
            msg = f"「宿」を作成しますか？\nあなたは「{FREE_INN_ROLE_NAME}」のため **無料** で作成可能です。"
        else:
            msg = f"「宿」を購入しますか？ ({price} {CURRENCY_NAME})"
        await it.response.send_message(msg, view=RoomConfirmView("宿"), ephemeral=True)
    @discord.ui.button(label="高級宿", style=discord.ButtonStyle.primary, emoji="🏰", custom_id="persistent_luxury_inn_btn")
    async def luxury(self, it, btn): await it.response.send_message(f"「高級宿」を購入しますか？ ({ROOM_SETTINGS['高級宿']['price']} {CURRENCY_NAME})", view=RoomConfirmView("高級宿"), ephemeral=True)

class CustomRoomView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="カスタムVCを作成", style=discord.ButtonStyle.primary, emoji="✨", custom_id="persistent_custom_room_btn")
    async def custom(self, it, btn): await it.response.send_message(f"「カスタムVC」を購入しますか？ ({ROOM_SETTINGS['カスタムVC']['price']} {CURRENCY_NAME})", view=RoomConfirmView("カスタムVC"), ephemeral=True)

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
            return "役なし", sum(d)
        bd, pd = [random.randint(1,6) for _ in range(3)], [random.randint(1,6) for _ in range(3)]
        bh, br = get_rank(bd); ph, pr = get_rank(pd)
        if pr > br:
            mul = 10 if ph=="ピンゾロ" else (5 if "アラシ" in ph else (3 if ph=="シゴロ" else (2 if "出目" in ph else 1)))
            await database.add_balance(self.user.id, int(self.bet*(1+mul)))
            res, color = f"🏆 勝ち！ {int(self.bet*mul)} {CURRENCY_NAME} 獲得", discord.Color.gold()
        elif pr < br: res, color = "💀 負け…", discord.Color.red()
        else: await database.add_balance(self.user.id, self.bet); res, color = "🤝 引き分け", discord.Color.light_grey()
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
            await database.add_balance(self.user.id, self.bet*2)
            msg, color = f"🏆 当たり！ {self.bet*2} {CURRENCY_NAME} 獲得", discord.Color.gold()
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
            emo = ["🍒", "🍋", "🍉", "🔔", "⭐", "7️⃣"]
            r = [random.choice(emo) for _ in range(3)]
            mul = 10 if r[0]==r[1]==r[2]=="7️⃣" else (5 if r[0]==r[1]==r[2]=="⭐" else (3 if r[0]==r[1]==r[2] else (1.5 if len(set(r))<3 else 0)))
            win = int(bet * mul)
            if win > 0: await database.add_balance(it.user.id, win)
            embed = discord.Embed(title="🎰 スロット結果", description=f"{r}\n{'🏆 当たり！' if win>0 else '💀 ハズレ'} {win} 獲得", color=discord.Color.gold() if win>0 else discord.Color.red())
            await it.followup.send(embed=embed, ephemeral=True)
        except: await it.response.send_message("エラー", ephemeral=True)

class SlotView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎰 スロットで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_slot_btn")
    async def play(self, it, btn): await it.response.send_modal(SlotBetModal())

# --- コマンドグループ ---

class AdminGroup(app_commands.Group):
    def __init__(self): super().__init__(name="管理者", description="【管理者専用】管理コマンド")
    
    @app_commands.command(name="通貨付与", description="指定ユーザーに通貨を付与")
    @is_admin()
    async def give(self, it, target: discord.Member, amount: int):
        await database.add_balance(target.id, amount)
        await it.response.send_message(f"✅ {target.mention} に {amount} {CURRENCY_NAME} 付与しました。")

    @app_commands.command(name="通貨没収", description="指定ユーザーから通貨を没収")
    @is_admin()
    async def remove(self, it, target: discord.Member, amount: int):
        await database.remove_balance(target.id, amount)
        await it.response.send_message(f"✅ {target.mention} から {amount} {CURRENCY_NAME} 没収しました。")

    @app_commands.command(name="ランク点リセット", description="ランク情報の初期化")
    @app_commands.checks.has_permissions(administrator=True)
    async def rrank(self, it, user: discord.Member):
        await database.reset_user_rank(user.id); await it.response.send_message("リセット完了", ephemeral=True)

    @app_commands.command(name="所持金リセット", description="所持金の初期化")
    @app_commands.checks.has_permissions(administrator=True)
    async def rbal(self, it, user: discord.Member):
        await database.reset_user_balance(user.id); await it.response.send_message("リセット完了", ephemeral=True)

    @app_commands.command(name="パネル設置_チンチロ", description="チンチロパネルを送信")
    @is_admin()
    async def s_chin(self, it): await it.channel.send(embed=discord.Embed(title="🎲 チンチロリン", description="カジノへようこそ！", color=discord.Color.dark_green()), view=ChinchiroView()); await it.response.send_message("設置完了", ephemeral=True)

    @app_commands.command(name="パネル設置_コイントス", description="コイントスパネルを送信")
    @is_admin()
    async def s_coin(self, it): await it.channel.send(embed=discord.Embed(title="🪙 コイントス", description="表か裏か！", color=discord.Color.blue()), view=CoinflipView()); await it.response.send_message("設置完了", ephemeral=True)

    @app_commands.command(name="パネル設置_スロット", description="スロットパネルを送信")
    @is_admin()
    async def s_slot(self, it): await it.channel.send(embed=discord.Embed(title="🎰 スロット", description="絵柄を揃えろ！", color=discord.Color.orange()), view=SlotView()); await it.response.send_message("設置完了", ephemeral=True)

    @app_commands.command(name="パネル設置_宿屋", description="宿屋パネルを送信")
    @is_admin()
    async def s_inn(self, it):
        embed = discord.Embed(
            title="🏠 宿屋", 
            description=f"部屋を借りる\n※ロール「{FREE_INN_ROLE_NAME}」をお持ちの方は「宿」が無料になります。", 
            color=discord.Color.gold()
        )
        await it.channel.send(embed=embed, view=RoomView())
        await it.response.send_message("設置完了", ephemeral=True)

    @app_commands.command(name="パネル設置_カスタムvc", description="カスタムVCパネルを送信")
    @is_admin()
    async def s_cvc(self, it): await it.channel.send(embed=discord.Embed(title="✨ カスタムVC", description="自分だけの部屋を作成", color=discord.Color.purple()), view=CustomRoomView()); await it.response.send_message("設置完了", ephemeral=True)

    @app_commands.command(name="パネル設置_スタンプ依頼", description="スタンプ依頼パネルを送信")
    async def s_emblem(self, it):
        user_roles = [r.name for r in it.user.roles]
        is_manager = EMBLEM_MANAGER_ROLE_NAME in user_roles
        if not is_manager and not has_admin_role(it.user) and not it.user.guild_permissions.administrator:
            return await it.response.send_message("権限がありません（統括または運営専用です）。", ephemeral=True)
        
        embed = discord.Embed(
            title="🎨 スタンプ制作 依頼所",
            description=(
                "こちらから紋章師の方々へスタンプの制作を依頼できます！\n\n"
                "**【依頼方法】**\n"
                "1. 下の「スタンプを依頼する」ボタンを押す\n"
                "2. 制作を依頼したい担当者を選択する\n"
                "3. 依頼内容の詳細を記入して送信\n\n"
                "※依頼送信後、担当者から連絡があるまでお待ちください。"
            ),
            color=discord.Color.blue()
        )
        await it.channel.send(embed=embed, view=EmblemRequestPanelView())
        await it.response.send_message("設置完了", ephemeral=True)

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

    @app_commands.command(name="sql_実行", description="【管理者専用】SQLを直接実行します（デバッグ用）")
    @is_admin()
    async def sql_exec(self, it, query: str):
        try:
            pool = await database.get_pool()
            async with pool.acquire() as conn:
                if query.strip().lower().startswith("select"):
                    rows = await conn.fetch(query)
                    if not rows: return await it.response.send_message("結果は空です。", ephemeral=True)
                    txt = "【実行結果】\n" + "\n".join([str(dict(r)) for r in rows])
                    await it.response.send_message(txt[:2000], ephemeral=True)
                else:
                    res = await conn.execute(query)
                    await it.response.send_message(f"実行完了: {res}", ephemeral=True)
        except Exception as e:
            await it.response.send_message(f"SQLエラー: {e}", ephemeral=True)

class InterviewerGroup(app_commands.Group):
    def __init__(self): super().__init__(name="面接官", description="【面接官専用】手続きコマンド")
    
    @app_commands.command(name="パネル設置_入界手続き", description="入界手続きパネルを送信")
    async def s_int(self, it):
        user_roles = [r.name for r in it.user.roles]
        is_interviewer = any(r in INTERVIEWER_ROLE_NAMES for r in user_roles)
        is_admin = any(r in ADMIN_ROLE_NAMES for r in user_roles)
        if not is_interviewer and not is_admin and not it.user.guild_permissions.administrator:
            return await it.response.send_message("権限がありません。", ephemeral=True)
        await it.channel.send(embed=discord.Embed(title="✨ 入界手続き", description="下のボタンから登録してください。", color=discord.Color.green()), view=InterviewPanelView())
        await it.response.send_message("設置完了", ephemeral=True)

# --- 実行 ---
if __name__ == "__main__":
    if TOKEN:
        discord.utils.setup_logging()
        keep_alive()
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN is not set in .env")
