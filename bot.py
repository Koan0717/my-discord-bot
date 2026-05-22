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
CURRENCY_NAME = "Rune"
JST = datetime.timezone(datetime.timedelta(hours=9))

# 獲得量の設定
MSG_COOLDOWN = 60     # メッセージ獲得のクールダウン（秒）


# 経験値の設定
TC_XP_REWARD = 10      # メッセージ1通あたりのXP
TC_XP_COOLDOWN = 10    # TC XP獲得のクールダウン（秒）
VC_XP_PER_MIN = 15     # VC滞在1分あたりのXP
LEVEL_UP_CHANNEL_ID = 1503480861105066024
RANKING_CATEGORY_NAME = "黄昏の森"  # ランク機能が有効なカテゴリー

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
INTERVIEWER_ROLE_NAMES = ["幽裁官", "最高幽裁官"]
FREE_INN_ROLE_NAMES = ["死者", "死神"]
EMBLEM_MANAGER_ROLE_NAME = "紋章師統括"
EMBLEM_MASTER_ROLE_NAME = "紋章師"
CONFESSION_PRIEST_ROLE_NAME = "告解司祭"
PRIEST_ROLE_NAME = "司祭"
INITIAL_COINS = 30000

# 自己紹介・評価設定
SELF_INTRO_CHANNEL_IDS = [1503022128759570682, 1503022167938433064]
EVALUATION_FORUM_CHANNEL_ID = 1503360808669806713

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
        self.add_view(BlackjackView())
        self.add_view(RouletteView())
        self.add_view(InterviewPanelView())
        self.add_view(EmblemRequestPanelView())
        self.add_view(ConfessionRequestPanelView())
        self.add_view(TicketControlView())
        self.add_view(VCRenamePanelView())
        self.add_view(PanelSetupView())
        
        # グループの登録
        self.tree.add_command(AdminGroup())
        self.tree.add_command(InterviewerGroup())
        self.tree.add_command(EvaluationGroup())
        
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
            # 全てのサーバーからユーザーを探す
            for guild in self.guilds:
                m = guild.get_member(user_id)
                if m and m.voice and m.voice.channel:
                    member = m
                    break
            
            if member:
                # カテゴリーのチェック (部分一致・大文字小文字無視)
                category_name = member.voice.channel.category.name if member.voice.channel and member.voice.channel.category else "なし"
                in_correct_category = RANKING_CATEGORY_NAME.lower() in category_name.lower()
                
                if not in_correct_category:
                    # 条件を満たしていない場合はセッションを終了
                    self.vc_sessions.pop(user_id, None)
                    continue

                elapsed_minutes = int((now - last_reward_time).total_seconds() / 60)
                if elapsed_minutes >= 1:
                    xp_reward = elapsed_minutes * VC_XP_PER_MIN
                    print(f"[DEBUG] VC XP Awarding: {member.display_name} in {category_name}")
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
    # 2. TC経験値の判定
    # カテゴリーのチェック (部分一致・大文字小文字無視)
    category_name = message.channel.category.name if message.channel.category else "なし"
    in_correct_category = RANKING_CATEGORY_NAME.lower() in category_name.lower()

    if in_correct_category:
        last_xp_time = bot.tc_xp_cooldowns.get(user_id)
        if not last_xp_time or (now - last_xp_time).total_seconds() > TC_XP_COOLDOWN:
            print(f"[DEBUG] TC XP Awarding: {message.author.display_name} in {category_name}")
            new_lv = await database.add_xp(user_id, TC_XP_REWARD, "tc")
            bot.tc_xp_cooldowns[user_id] = now
            if new_lv:
                lv_channel = bot.get_channel(LEVEL_UP_CHANNEL_ID)
                if lv_channel:
                    await lv_channel.send(f"🎊 {message.author.mention} が **TCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
    
    # 3. 自己紹介チャンネルでの発言検知（スレッド自動作成）
    if message.channel.id in SELF_INTRO_CHANNEL_IDS:
        human_role = discord.utils.get(message.guild.roles, name=NEW_MEMBER_ROLE_NAME)
        if human_role and human_role in message.author.roles:
            forum_channel = bot.get_channel(EVALUATION_FORUM_CHANNEL_ID)
            if isinstance(forum_channel, discord.ForumChannel):
                # 重複チェック: アクティブなスレッド名にユーザー名（アカウント名）が含まれているか
                duplicate = any(message.author.name in thread.name for thread in forum_channel.threads)
                
                if not duplicate:
                    period = await database.get_evaluation_period(user_id)
                    if period:
                        start_str = f"<t:{int(period['start_time'].timestamp())}:F>"
                        end_str = f"<t:{int(period['end_time'].timestamp())}:F>"
                        content = (
                            f"**対象者:** {message.author.mention}\n"
                            f"**評価期間:** {start_str} ～ {end_str}\n\n"
                            f"**自己紹介へのリンク:**\n{message.jump_url}"
                        )
                    else:
                        content = (
                            f"**対象者:** {message.author.mention}\n"
                            f"**評価期間:** データが見つかりませんでした。\n\n"
                            f"**自己紹介へのリンク:**\n{message.jump_url}"
                        )
                        
                    thread_name = f"{message.author.display_name}_{message.author.name}"
                    try:
                        await forum_channel.create_thread(
                            name=thread_name,
                            content=content,
                            reason=f"Auto created evaluation thread for {message.author.display_name}"
                        )
                        print(f"[Evaluation Thread] Created for {message.author.display_name}")
                    except Exception as e:
                        print(f"[ERROR] Failed to create forum thread: {e}")

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        if member.bot: return
        user_id = member.id
        now_naive = database.get_now_naive()
        now_aware = datetime.datetime.now(JST)

        if after.channel is not None:
            is_join = before.channel is None or before.channel.id != after.channel.id
            if is_join:
                # カテゴリーのチェックを満たす場合のみセッション開始
                category_name = after.channel.category.name if after.channel.category else ""
                in_correct_category = RANKING_CATEGORY_NAME in category_name
                
                if in_correct_category:
                    print(f"[VC XP] Started session for {member.display_name}")
                    bot.vc_sessions[user_id] = now_aware
            
            if after.channel.id == CREATE_VC_CHANNEL_ID:
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
                            if member.voice and member.voice.channel and member.voice.channel.id == CREATE_VC_CHANNEL_ID:
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
                                # DBに再登録を試みる
                                now_naive = database.get_now_naive()
                                far_future = now_naive + datetime.timedelta(days=36500)
                                await database.add_room(existing_ch.id, member.id, "一時部屋", far_future)
                                await asyncio.sleep(0.3)
                                if member.voice and member.voice.channel and member.voice.channel.id == CREATE_VC_CHANNEL_ID:
                                    await member.move_to(existing_ch)
                                return
                    new_channel = await guild.create_voice_channel(
                        name=channel_name,
                        category=category,
                        reason=f"Auto-VC for {member.display_name}"
                    )
                    
                    # 確実にDBに保存されるのを待つ (TIMESTAMP型に合わせてtimezone情報を抜く)
                    now_naive = database.get_now_naive()
                    far_future = now_naive + datetime.timedelta(days=36500)
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
                    print(f"[Auto-VC] Error: {e}")
            # ------------------------

            # カスタムVCへの入室であれば、無人タイマーを解除
            bot.empty_custom_vcs.pop(after.channel.id, None)
        
        # VCから退出・移動した時
        if before.channel is not None and (after.channel is None or before.channel != after.channel):
            join_time = bot.vc_sessions.pop(user_id, None)
            if join_time:
                duration_minutes = int((now_aware - join_time).total_seconds() / 60)
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
                        bot.empty_custom_vcs[before.channel.id] = now_aware
    except Exception as global_e:
        print(f"CRITICAL ERROR in on_voice_state_update: {global_e}")

@bot.event
async def on_guild_channel_delete(channel):
    # 手動でチャンネルが削除された場合、データベースからも消去する
    room_data = await database.get_room(channel.id)
    if room_data:
        await database.remove_room(channel.id)
        bot.empty_custom_vcs.pop(channel.id, None)

@bot.event
async def on_member_update(before, after):
    human_role = discord.utils.get(after.guild.roles, name=NEW_MEMBER_ROLE_NAME)
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

# --- 運営権限チェック ---
ADMIN_ROLE_NAMES = ["大魔王", "管理者"]
EVALUATOR_ROLE_NAMES = ["最高観測官", "深淵観測官"]

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

def has_evaluator_role(user: discord.Member):
    user_roles = [role.name for role in user.roles]
    return any(r in EVALUATOR_ROLE_NAMES or r in ADMIN_ROLE_NAMES for r in user_roles)

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

        # VCランク
        vc_value = (
            f"**Level:** `{vc_lv}`\n"
            f"**Next:** `{vc_xp}` / `{vc_next}` XP\n"
            f"{create_progress_bar(vc_xp, vc_next)}\n"
            f"┗ 次のレベルまであと **{vc_needed}** XP\n"
            f"┗ 目安: あと **約{vc_est_mins}分** の滞在"
        )
        embed.add_field(name="🎙️ ボイス活動 (VC)", value=vc_value, inline=False)

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
        priest1_role = discord.utils.get(guild.roles, name=CONFESSION_PRIEST_ROLE_NAME)
        priest2_role = discord.utils.get(guild.roles, name=PRIEST_ROLE_NAME)
        
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
    
    # 無料対象ロールによる無料化
    user_roles = [r.name for r in interaction.user.roles]
    if room_type == "宿" and any(r in FREE_INN_ROLE_NAMES for r in user_roles):
        price = 0

    if await database.get_balance(owner_id) < price:
        return await interaction.edit_original_response(content="残高が不足しています。")
    
    if price == 0 or await database.remove_balance(owner_id, price):
        try:
            overwrites = { interaction.guild.default_role: discord.PermissionOverwrite(connect=True),
                           interaction.user: discord.PermissionOverwrite(manage_channels=True, move_members=True) }
            if room_type == "高級宿": overwrites[interaction.user].manage_permissions = True
            channel = await interaction.guild.create_voice_channel(name=f"{room_type}-{interaction.user.display_name}", category=interaction.channel.category, overwrites=overwrites, user_limit=(2 if room_type=="宿" else 0))
            expire_at = database.get_now_naive() + datetime.timedelta(hours=duration)
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
        if any(r in FREE_INN_ROLE_NAMES for r in user_roles):
            msg = f"「宿」を作成しますか？\nあなたは対象ロールのため **無料** で作成可能です。"
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
            return "役なし", 0
        bd, pd = [random.randint(1,6) for _ in range(3)], [random.randint(1,6) for _ in range(3)]
        bh, br = get_rank(bd); ph, pr = get_rank(pd)
        if pr > br:
            mul = 9 if ph=="ピンゾロ" else (4 if "アラシ" in ph else (2 if ph=="シゴロ" else (1 if "出目" in ph else 0)))
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
            await database.add_balance(self.user.id, int(self.bet*2.0))
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
            if win > 0: await database.add_balance(it.user.id, win)
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
            discord.SelectOption(label="宿屋", description="宿・高級宿の購入パネルを設置します", emoji="🛖", value="inn"),
            discord.SelectOption(label="カスタムVC", description="カスタムVCの作成パネルを設置します", emoji="✨", value="custom_vc"),
            discord.SelectOption(label="スタンプ依頼", description="スタンプ制作依頼のパネルを設置します", emoji="🎨", value="stamp"),
            discord.SelectOption(label="告解・相談室", description="告解・相談依頼のパネルを設置します", emoji="⛪", value="confession"),
            discord.SelectOption(label="VC管理", description="VC名・人数制限変更のパネルを設置します", emoji="⚙️", value="vc_manage"),
            discord.SelectOption(label="入界手続き", description="新規メンバーの入界手続きパネルを設置します", emoji="📝", value="interview")
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
        elif val == "inn":
            embed = discord.Embed(
                title="🏠 宿屋", 
                description=f"部屋を借りる\n※ロール「{'」や「'.join(FREE_INN_ROLE_NAMES)}」をお持ちの方は「宿」が無料になります。", 
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=RoomView())
            await interaction.response.send_message("✅ 宿屋パネルを設置しました。", ephemeral=True)
        elif val == "custom_vc":
            embed = discord.Embed(title="✨ カスタムVC", description="自分だけの部屋を作成", color=discord.Color.purple())
            await channel.send(embed=embed, view=CustomRoomView())
            await interaction.response.send_message("✅ カスタムVCパネルを設置しました。", ephemeral=True)
        elif val == "stamp":
            embed = discord.Embed(
                title="スタンプ制作 依頼所",
                description=(
                    "こちらから紋章師の方々へスタンプの制作を依頼できます。\n\n"
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

class PanelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PanelSelect())

class AdminGroup(app_commands.Group):
    def __init__(self): super().__init__(name="管理者", description="【管理者専用】管理コマンド")

    @app_commands.command(name="パネル設置", description="【管理者専用】自分にしか見えないパネル設定画面を表示し、各種パネルを設置します")
    @is_admin()
    async def panel_setup(self, interaction: discord.Interaction):
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
        
        # 宿・カスタムVC
        inn_price = ROOM_SETTINGS['宿']['price']
        inn_hours = ROOM_SETTINGS['宿']['duration_hours']
        lux_price = ROOM_SETTINGS['高級宿']['price']
        lux_hours = ROOM_SETTINGS['高級宿']['duration_hours']
        cvc_price = ROOM_SETTINGS['カスタムVC']['price']
        cvc_hours = ROOM_SETTINGS['カスタムVC']['duration_hours']
        
        embed.add_field(
            name="🏨 部屋・宿設定",
            value=(
                f"🛖 **宿**: {inn_price} {CURRENCY_NAME} / {inn_hours}h (無料ロール: {', '.join(FREE_INN_ROLE_NAMES)})\n"
                f"🏰 **高級宿**: {lux_price} {CURRENCY_NAME} / {lux_hours}h\n"
                f"✨ **カスタムVC**: {cvc_price} {CURRENCY_NAME} / {cvc_hours}h"
            ),
            inline=False
        )
        
        # ロール・メンバーシップ
        embed.add_field(
            name="👥 ロール設定",
            value=(
                f"入界後ロール: **{NEW_MEMBER_ROLE_NAME}**\n"
                f"待機者ロール: **{PENDING_MEMBER_ROLE_NAME}**\n"
                f"面接官ロール: **{', '.join(INTERVIEWER_ROLE_NAMES)}**"
            ),
            inline=False
        )
        
        # 制作・告解
        embed.add_field(
            name="🎨 制作・告解設定",
            value=(
                f"紋章師ロール: **{EMBLEM_MANAGER_ROLE_NAME}**, **{EMBLEM_MASTER_ROLE_NAME}**\n"
                f"司祭ロール: **{CONFESSION_PRIEST_ROLE_NAME}**, **{PRIEST_ROLE_NAME}**"
            ),
            inline=False
        )
        
        view = PanelSetupView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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

    @app_commands.command(name="所持金リセット", description="所持金の初期化")
    @app_commands.checks.has_permissions(administrator=True)
    async def rbal(self, it, user: discord.Member):
        await database.reset_user_balance(user.id); await it.response.send_message("リセット完了", ephemeral=True)


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
    
    @app_commands.command(name="パネル設置_入界手続き", description="入界手続きパネルを送信")
    async def s_int(self, it):
        user_roles = [r.name for r in it.user.roles]
        is_interviewer = any(r in INTERVIEWER_ROLE_NAMES for r in user_roles)
        is_admin = any(r in ADMIN_ROLE_NAMES for r in user_roles)
        if not is_interviewer and not is_admin and not it.user.guild_permissions.administrator:
            return await it.response.send_message("権限がありません。", ephemeral=True)
        await it.channel.send(embed=discord.Embed(title="✨ 入界手続き", description="下のボタンから登録してください。", color=discord.Color.green()), view=InterviewPanelView())
        await it.response.send_message("設置完了", ephemeral=True)

    @app_commands.command(name="入界手続き実行", description="VCチャットの履歴から入界待機者の発言を取得し、入界手続きを一括実行します")
    async def execute_interview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        
        user_roles = [r.name for r in interaction.user.roles]
        is_interviewer = any(r in INTERVIEWER_ROLE_NAMES for r in user_roles)
        is_admin = any(r in ADMIN_ROLE_NAMES for r in user_roles)
        if not is_interviewer and not is_admin and not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("権限がありません。", ephemeral=True)
            
        pending_role = discord.utils.get(interaction.guild.roles, name=PENDING_MEMBER_ROLE_NAME)
        new_role = discord.utils.get(interaction.guild.roles, name=NEW_MEMBER_ROLE_NAME)
        
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
                results.append(f"✅ {member.mention} -> **{desired_name}**")
            except Exception as e:
                results.append(f"❌ {member.display_name} -> 権限エラー等")
                
        embed = discord.Embed(title="✨ 入界手続き一括実行結果", description="\n".join(results), color=discord.Color.green())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="チャット削除", description="現在のチャンネルのチャット履歴を削除します（最大100件）")
    async def clear_chat(self, interaction: discord.Interaction, amount: int = 100):
        user_roles = [r.name for r in interaction.user.roles]
        is_interviewer = any(r in INTERVIEWER_ROLE_NAMES for r in user_roles)
        is_admin = any(r in ADMIN_ROLE_NAMES for r in user_roles)
        if not is_interviewer and not is_admin and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"✅ {len(deleted)}件のメッセージを削除しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ メッセージを削除する権限（メッセージの管理）がBotにありません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

class EvaluationGroup(app_commands.Group):
    def __init__(self): super().__init__(name="評価期間", description="評価期間関連コマンド")

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
            end_t = int(p['end_time'].timestamp())
            embed.add_field(name=name, value=f"終了予定: <t:{end_t}:F> (<t:{end_t}:R>)", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="確認", description="ユーザーの評価期間を確認します")
    async def check_period(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        
        if target.id != interaction.user.id:
            if not has_evaluator_role(interaction.user) and not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("他人の評価期間を見る権限がありません。", ephemeral=True)
                
        period = await database.get_evaluation_period(target.id)
        if not period:
            return await interaction.response.send_message(f"{target.display_name} は評価期間中ではありません。", ephemeral=True)
            
        start_t = int(period['start_time'].timestamp())
        end_t = int(period['end_time'].timestamp())
        
        embed = discord.Embed(title=f"⏳ {target.display_name} の評価期間", color=discord.Color.green())
        embed.add_field(name="開始時刻", value=f"<t:{start_t}:F>", inline=False)
        embed.add_field(name="終了予定", value=f"<t:{end_t}:F> (<t:{end_t}:R>)", inline=False)
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
        end_t = int(period['end_time'].timestamp())
        await interaction.response.send_message(f"✅ {user.mention} の評価期間を {extra_days} 日延長しました。\n新しい終了予定: <t:{end_t}:F>", ephemeral=True)

# --- 実行 ---
if __name__ == "__main__":
    if TOKEN:
        discord.utils.setup_logging()
        keep_alive()
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN is not set in .env")
