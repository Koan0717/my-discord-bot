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
MSG_REWARD = 5        # メッセージ1通あたりの獲得量
MSG_COOLDOWN = 60     # メッセージ獲得のクールダウン（秒）
VC_REWARD_PER_MIN = 10# VC滞在1分あたりの獲得量


# 経験値の設定
TC_XP_REWARD = 10      # メッセージ1通あたりのXP
VC_XP_PER_MIN = 15     # VC滞在1分あたりのXP
LEVEL_UP_CHANNEL_ID = 1503480861105066024

# 部屋作成の設定
ROOM_SETTINGS = {
    "宿": {"price": 10000, "duration_hours": 12},
    "高級宿": {"price": 30000, "duration_hours": 24},
    "カスタムVC": {"price": 30000, "duration_hours": 24}
}

# 面接・入界設定
NEW_MEMBER_ROLE_NAME = "人間"
PENDING_MEMBER_ROLE_NAME = "入界待機者"
INTERVIEWER_ROLE_NAMES = ["面接官", "大魔王", "黒棺秘書官", "機巧墓守"]
INITIAL_COINS = 30000

# ------------

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

class EconomyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.message_cooldowns = {} # {user_id: timestamp}
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
        await self.tree.sync()
        self.check_expired_rooms.start()
        print(f"✅ Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        print("✅ Slash commands and persistent views are synced.")

    @tasks.loop(minutes=1)
    async def check_expired_rooms(self):
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 部屋の定期チェック（期限切れ・無人状態）を実行しています...")
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

bot = EconomyBot()

# --- イベント ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    user_id = message.author.id
    now = datetime.datetime.now(JST)

    # メッセージ報酬のクールダウンチェック
    last_msg_time = bot.message_cooldowns.get(user_id)
    if not last_msg_time or (now - last_msg_time).total_seconds() > MSG_COOLDOWN:
        await database.add_balance(user_id, MSG_REWARD)
        bot.message_cooldowns[user_id] = now
        
        # TC経験値の加算
        new_lv = await database.add_xp(user_id, TC_XP_REWARD, "tc")
        if new_lv:
            lv_channel = bot.get_channel(LEVEL_UP_CHANNEL_ID)
            if lv_channel:
                await lv_channel.send(f"🎊 {message.author.mention} が **TCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
    
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    user_id = member.id
    now = datetime.datetime.now(JST)

    # VCに参加・移動した時
    if after.channel is not None:
        if before.channel is None or before.channel != after.channel:
            bot.vc_sessions[user_id] = now
        # カスタムVCへの入室であれば、無人タイマーを解除
        bot.empty_custom_vcs.pop(after.channel.id, None)
    
    # VCから退出・移動した時
    if before.channel is not None and (after.channel is None or before.channel != after.channel):
        join_time = bot.vc_sessions.pop(user_id, None)
        if join_time:
            duration_minutes = int((now - join_time).total_seconds() / 60)
            if duration_minutes > 0:
                reward = duration_minutes * VC_REWARD_PER_MIN
                await database.add_balance(user_id, reward)
                
                # VC経験値の加算
                xp_reward = duration_minutes * VC_XP_PER_MIN
                new_lv = await database.add_xp(user_id, xp_reward, "vc")
                if new_lv:
                    lv_channel = bot.get_channel(LEVEL_UP_CHANNEL_ID)
                    if lv_channel:
                        await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
        
        # 退出した部屋が無人になった場合、それがカスタムVCならタイマーを開始
        if len(before.channel.members) == 0:
            room_data = await database.get_room(before.channel.id)
            if room_data and room_data["room_type"] == "カスタムVC":
                bot.empty_custom_vcs[before.channel.id] = now

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
        
        # ロール名でチェック
        user_role_names = [role.name for role in interaction.user.roles]
        if any(role_name in ADMIN_ROLE_NAMES for role_name in user_role_names):
            return True
            
        await interaction.response.send_message("このコマンドを実行する権限がありません（運営専用ロールが必要です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)

def has_admin_role(user: discord.Member):
    """一般ロジック内での権限チェック用"""
    return any(role.name in ADMIN_ROLE_NAMES for role in user.roles)

# --- スラッシュコマンド ---

@bot.tree.command(name="balance", description="自分の所持金を確認します（管理者は他のユーザーも確認可能）")
async def balance(interaction: discord.Interaction, user: discord.Member = None):
    # 他人の残高を見る場合、管理者権限（または自分自身）が必要
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

@bot.tree.command(name="give", description="【管理者専用】ユーザーに通貨を付与します")
@is_admin()
async def give(interaction: discord.Interaction, target: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
        return
    
    await database.add_balance(target.id, amount)
    await interaction.response.send_message(f"運営から {target.mention} に **{amount} {CURRENCY_NAME}** が付与されました！")

@bot.tree.command(name="remove", description="【管理者専用】ユーザーの通貨を没収します")
@is_admin()
async def remove_money(interaction: discord.Interaction, target: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
        return
    
    await database.remove_balance(target.id, amount)
    await interaction.response.send_message(f"運営が {target.mention} から **{amount} {CURRENCY_NAME}** を没収しました。")

@bot.tree.command(name="rank", description="自分または他ユーザーのランク（レベル）を表示します")
async def rank(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    user_data = await database.get_user(target_user.id)
    
    tc_xp = user_data["tc_xp"]
    tc_lv = user_data["tc_level"]
    vc_xp = user_data["vc_xp"]
    vc_lv = user_data["vc_level"]
    
    tc_next = database.get_next_level_xp(tc_lv)
    vc_next = database.get_next_level_xp(vc_lv)
    
    def create_progress_bar(current, total):
        pct = min(current / total, 1.0)
        filled = int(pct * 10)
        return "■" * filled + "□" * (10 - filled) + f" ({int(pct*100)}%)"

    embed = discord.Embed(title=f"📊 {target_user.display_name} のランク情報", color=discord.Color.blue())
    if target_user.avatar:
        embed.set_thumbnail(url=target_user.avatar.url)
        
    embed.add_field(
        name=f"💬 TCランク (Lv.{tc_lv})", 
        value=f"XP: {tc_xp} / {tc_next}\n`{create_progress_bar(tc_xp, tc_next)}`", 
        inline=False
    )
    embed.add_field(
        name=f"🎙️ VCランク (Lv.{vc_lv})", 
        value=f"XP: {vc_xp} / {vc_next}\n`{create_progress_bar(vc_xp, vc_next)}`", 
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)





# --- VCコントロールパネル ---
async def handle_extend(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    room_data = await database.get_room(channel_id)
    if not room_data:
        await interaction.response.send_message("この部屋のデータが見つかりません（既に期限切れか、手動作成された可能性があります）。", ephemeral=True)
        return
    
    owner_id = room_data["owner_id"]
    if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("この部屋の延長は、作成者または管理者のみが可能です。", ephemeral=True)
        return

    room_type = room_data["room_type"]
    settings = ROOM_SETTINGS.get(room_type)
    if not settings:
        await interaction.response.send_message("この部屋の延長設定が見つかりません。", ephemeral=True)
        return

    price = settings["price"]
    duration = settings["duration_hours"]

    success = await database.remove_balance(interaction.user.id, price)
    if not success:
        await interaction.response.send_message(f"残高が不足しています！延長には {price} {CURRENCY_NAME} 必要です。", ephemeral=True)
        return

    new_expire = room_data["expire_at"] + datetime.timedelta(hours=duration)
    await database.extend_room(channel_id, new_expire)
    
    await interaction.response.send_message(f"**{price} {CURRENCY_NAME}** を支払い、時間を {duration} 時間延長しました！\n新しい終了予定時刻: <t:{int(new_expire.timestamp())}:F>")

async def handle_delete(interaction: discord.Interaction):
    room_data = await database.get_room(interaction.channel_id)
    if room_data:
        owner_id = room_data["owner_id"]
        if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("この部屋の削除は、作成者または管理者のみが可能です。", ephemeral=True)
            return
    
    await interaction.response.send_message("部屋を削除します...")
    await asyncio.sleep(2)
    try:
        await interaction.channel.delete()
    except discord.NotFound:
        pass
    if room_data:
        await database.remove_room(interaction.channel_id)


class InnControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="延長", style=discord.ButtonStyle.primary, emoji="⏱", custom_id="inn_extend_btn")
    async def extend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_extend(interaction)

    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, emoji="🗑", custom_id="inn_delete_btn")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_delete(interaction)

    @discord.ui.button(label="名前変更", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="inn_rename_btn", row=1)
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        room_data = await database.get_room(interaction.channel_id)
        if room_data and interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("設定変更は作成者または管理者のみ可能です。", ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal())

class RoomControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="延長", style=discord.ButtonStyle.primary, emoji="⏱", custom_id="persistent_extend_btn")
    async def extend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_extend(interaction)

    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, emoji="🗑", custom_id="persistent_delete_btn")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_delete(interaction)

    @discord.ui.button(label="名前変更", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="persistent_rename_btn", row=1)
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        room_data = await database.get_room(interaction.channel_id)
        if room_data and interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("設定変更は作成者または管理者のみ可能です。", ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal())

    @discord.ui.button(label="人数制限", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="persistent_limit_btn", row=1)
    async def limit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        room_data = await database.get_room(interaction.channel_id)
        if room_data and interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("設定変更は作成者または管理者のみ可能です。", ephemeral=True)
            return
        await interaction.response.send_modal(LimitModal())


# --- カスタムVC設定用モーダルとパネル ---
class RenameModal(discord.ui.Modal, title='チャンネル名の変更'):
    name_input = discord.ui.TextInput(
        label='新しいチャンネル名',
        style=discord.TextStyle.short,
        placeholder='例: 雑談部屋',
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.channel.edit(name=self.name_input.value)
            await interaction.response.send_message(f"チャンネル名を「{self.name_input.value}」に変更しました！", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("名前の変更に失敗しました。", ephemeral=True)

class LimitModal(discord.ui.Modal, title='人数制限の設定'):
    limit_input = discord.ui.TextInput(
        label='人数 (0 で無制限)',
        style=discord.TextStyle.short,
        placeholder='例: 5',
        required=True,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.limit_input.value)
            if limit < 0 or limit > 99:
                await interaction.response.send_message("0 から 99 の間で入力してください。", ephemeral=True)
                return
            await interaction.channel.edit(user_limit=limit)
            if limit == 0:
                await interaction.response.send_message("人数制限を無制限に変更しました！", ephemeral=True)
            else:
                await interaction.response.send_message(f"人数制限を {limit} 人に変更しました！", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("正しい数字を入力してください。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("制限の変更に失敗しました。", ephemeral=True)

# --- 面接・入界システム ---
class InterviewNicknameModal(discord.ui.Modal, title='入界手続き：名前の設定'):
    name_input = discord.ui.TextInput(
        label='サーバーでの名前（ニックネーム）',
        style=discord.TextStyle.short,
        placeholder='例: ヤマダ太郎',
        required=True,
        max_length=32
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        
        # ロール取得
        new_role = discord.utils.get(guild.roles, name=NEW_MEMBER_ROLE_NAME)
        pending_role = discord.utils.get(guild.roles, name=PENDING_MEMBER_ROLE_NAME)
        
        if not new_role:
            await interaction.followup.send(f"エラー: ロール「{NEW_MEMBER_ROLE_NAME}」が見つかりません。", ephemeral=True)
            return

        # 二重付与チェック
        if new_role in member.roles:
            await interaction.followup.send("既に手続きは完了しています。", ephemeral=True)
            return

        try:
            # 1. ニックネーム変更
            await member.edit(nick=self.name_input.value)
            
            # 2. ロール付与・削除
            roles_to_add = [new_role]
            roles_to_remove = []
            if pending_role and pending_role in member.roles:
                roles_to_remove.append(pending_role)
            
            await member.add_roles(*roles_to_add)
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)
            
            # 3. 初期コイン付与
            await database.add_balance(member.id, INITIAL_COINS)
            
            await interaction.followup.send(
                f"✅ 手続きが完了しました！\n"
                f"・名前を「{self.name_input.value}」に変更しました。\n"
                f"・ロール「{NEW_MEMBER_ROLE_NAME}」を付与しました。\n"
                f"・初期費用として **{INITIAL_COINS} {CURRENCY_NAME}** を発行しました！\n\n"
                f"ようこそ！存分に楽しんでください。",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("エラー: 権限不足によりニックネームやロールの変更ができませんでした。Botのロール順位を確認してください。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class InterviewPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="入界手続きを開始", style=discord.ButtonStyle.success, emoji="📝", custom_id="persistent_interview_btn")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(InterviewNicknameModal())

@bot.tree.command(name="setup_interview", description="【面接官専用】入界手続き用のパネルを設置します")
async def setup_interview(interaction: discord.Interaction):
    # 権限チェック
    user_role_names = [role.name for role in interaction.user.roles]
    if not any(role_name in INTERVIEWER_ROLE_NAMES for role_name in user_role_names) and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return

    embed = discord.Embed(
        title="✨ 入界手続き（新規メンバー登録）",
        description=(
            "面接お疲れ様でした！\n"
            "下のボタンを押して、サーバー内での名前（ニックネーム）を設定してください。\n\n"
            "**手続き内容:**\n"
            "1. ニックネームの自動変更\n"
            "2. ロールの付与・整理\n"
            "3. 初期所持金 **30,000 コイン** の発行"
        ),
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=embed, view=InterviewPanelView())
    await interaction.response.send_message("手続きパネルを設置しました。", ephemeral=True)

class CustomRoomControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="延長", style=discord.ButtonStyle.primary, emoji="⏱", custom_id="custom_extend_btn")
    async def extend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_extend(interaction)

    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, emoji="🗑", custom_id="custom_delete_btn")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_delete(interaction)

    @discord.ui.button(label="名前変更", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="custom_rename_btn", row=1)
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        room_data = await database.get_room(interaction.channel_id)
        if room_data and interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("設定変更は作成者または管理者のみ可能です。", ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal())

    @discord.ui.button(label="人数制限", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="custom_limit_btn", row=1)
    async def limit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        room_data = await database.get_room(interaction.channel_id)
        if room_data and interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("設定変更は作成者または管理者のみ可能です。", ephemeral=True)
            return
        await interaction.response.send_modal(LimitModal())

# --- 管理者専用コマンド ---
@bot.tree.command(name="reset_user_rank", description="【管理者専用】指定したユーザーのランクレベルとXPをリセットします")
@app_commands.checks.has_permissions(administrator=True)
async def reset_user_rank_cmd(interaction: discord.Interaction, user: discord.Member):
    await database.reset_user_rank(user.id)
    await interaction.response.send_message(f"✅ {user.mention} のランクレベルとXPをリセットしました。", ephemeral=True)

@bot.tree.command(name="reset_user_balance", description="【管理者専用】指定したユーザーの所持金を0にリセットします")
@app_commands.checks.has_permissions(administrator=True)
async def reset_user_balance_cmd(interaction: discord.Interaction, user: discord.Member):
    await database.reset_user_balance(user.id)
    await interaction.response.send_message(f"✅ {user.mention} の所持金を 0 にリセットしました。", ephemeral=True)

@reset_user_rank_cmd.error
@reset_user_balance_cmd.error
async def admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません（管理者のみ可能です）。", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ エラーが発生しました: {error}", ephemeral=True)

# --- VC購入システム ---
async def process_room_purchase(interaction: discord.Interaction, room_type: str, is_confirm_view: bool = False):
    # タイムアウト対策（少し時間がかかる処理の前に宣言）
    if is_confirm_view:
        # すでに応答中の場合は defer_update
        await interaction.response.defer(ephemeral=True)
    else:
        await interaction.response.defer(ephemeral=True)

    async def reply(msg: str):
        # defer した後は edit_original_response または followup を使う
        await interaction.edit_original_response(content=msg, embed=None, view=None)

    # 購入数の制限チェック
    owner_id = interaction.user.id
    if room_type in ["宿", "高級宿"]:
        has_inn = await database.has_room_type(owner_id, ["宿", "高級宿"])
        if has_inn:
            await reply("既に「宿」または「高級宿」を持っています！(1人1つまで)")
            return
    elif room_type == "カスタムVC":
        has_custom = await database.has_room_type(owner_id, ["カスタムVC"])
        if has_custom:
            await reply("既に「カスタムVC」を持っています！(1人1つまで)")
            return

    settings = ROOM_SETTINGS[room_type]
    price = settings["price"]
    duration = settings["duration_hours"]

    # 残高確認
    current_bal = await database.get_balance(owner_id)
    if current_bal < price:
        await reply(f"残高が不足しています！(所持金が {price} {CURRENCY_NAME} 未満です)")
        return

    # 引き落とし
    success = await database.remove_balance(interaction.user.id, price)
    if not success:
        await reply("残高不足またはエラーが発生しました。")
        return

    # VC作成処理
    try:
        guild = interaction.guild
        category = interaction.channel.category
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            interaction.user: discord.PermissionOverwrite(manage_channels=True, move_members=True)
        }

        if room_type == "高級宿":
            overwrites[interaction.user].manage_permissions = True

        channel_name = f"{room_type}-{interaction.user.display_name}"
        user_limit = 2 if room_type == "宿" else 0
        new_vc = await guild.create_voice_channel(name=channel_name, category=category, overwrites=overwrites, user_limit=user_limit)

        # データベースに登録
        expire_at = datetime.datetime.now(JST) + datetime.timedelta(hours=duration)
        await database.add_room(new_vc.id, interaction.user.id, room_type, expire_at)

        await reply(f"✅ **{price} {CURRENCY_NAME}** を支払い、{new_vc.mention} を作成しました！")

        # VC内にコントロールパネルを送信
        if room_type == "カスタムVC":
            view = CustomRoomControlView()
        elif room_type == "高級宿":
            view = RoomControlView()
        else: # 普通の宿
            view = InnControlView()
        embed = discord.Embed(
            title=f"🏠 {room_type}",
            description=f"{interaction.user.mention} がこの部屋を作成しました。\n**終了予定時刻:** <t:{int(expire_at.timestamp())}:F>\n\n時間になるか「削除」を押すとこのチャンネルは自動で消滅します。\n時間を延ばしたい場合は「延長」を押してください。",
            color=discord.Color.blue()
        )
        await new_vc.send(content=f"{interaction.user.mention}", embed=embed, view=view)
    except Exception as e:
        # 失敗した場合は返金
        await database.add_balance(owner_id, price)
        await reply(f"エラーが発生しました: {e}")


class RoomConfirmView(discord.ui.View):
    def __init__(self, room_type: str):
        super().__init__(timeout=60) # 60秒でタイムアウト
        self.room_type = room_type

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, self.room_type, is_confirm_view=True)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="購入をキャンセルしました。", view=None)


class RoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="宿", style=discord.ButtonStyle.primary, emoji="🛖", custom_id="persistent_inn_btn")
    async def inn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        room_type = "宿"
        price = ROOM_SETTINGS[room_type]['price']
        await interaction.response.send_message(
            f"【{room_type}】を作成しますか？\nかかる料金: **{price} {CURRENCY_NAME}**",
            view=RoomConfirmView(room_type),
            ephemeral=True
        )

    @discord.ui.button(label="高級宿", style=discord.ButtonStyle.primary, emoji="🏰", custom_id="persistent_luxury_inn_btn")
    async def luxury_inn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        room_type = "高級宿"
        price = ROOM_SETTINGS[room_type]['price']
        await interaction.response.send_message(
            f"【{room_type}】を作成しますか？\nかかる料金: **{price} {CURRENCY_NAME}**",
            view=RoomConfirmView(room_type),
            ephemeral=True
        )

class CustomRoomButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="カスタムVCを作成", style=discord.ButtonStyle.primary, emoji="✨", custom_id="persistent_custom_room_btn")

    async def callback(self, interaction: discord.Interaction):
        room_type = "カスタムVC"
        price = ROOM_SETTINGS[room_type]['price']
        await interaction.response.send_message(
            f"【{room_type}】を作成しますか？\nかかる料金: **{price} {CURRENCY_NAME}**",
            view=RoomConfirmView(room_type),
            ephemeral=True
        )


class CustomRoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CustomRoomButton())


# --- チンチロリン システム ---

class ChinchiroBetModal(discord.ui.Modal, title='チンチロリン：賭け金入力'):
    bet_input = discord.ui.TextInput(
        label='賭ける金額を入力してください',
        style=discord.TextStyle.short,
        placeholder='例: 1000',
        required=True,
        min_length=1,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0:
                await interaction.response.send_message("1以上の金額を入力してください。", ephemeral=True)
                return
            if bet > 100000:
                await interaction.response.send_message("ギャンブルの賭け金上限は 100,000 コインです。", ephemeral=True)
                return
            
            # 処理に時間がかかる可能性があるので defer
            await interaction.response.defer(ephemeral=True)

            # 共通回数制限チェック
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(JST)
            today_str = now.strftime("%Y-%m-%d")
            
            count = user_data.get("chinchiro_count", 0)
            last_date = user_data.get("chinchiro_last_date")
            
            if last_date != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str)
                count = 0
            
            if count >= 10:
                await interaction.followup.send("ギャンブルは全種類合計で1日10回までです。また明日挑戦してください！", ephemeral=True)
                return

            # 残高チェックと引き落とし
            success = await database.remove_balance(interaction.user.id, bet)
            if not success:
                await interaction.followup.send("残高が不足しています。", ephemeral=True)
                return
            
            await database.increment_gambling_count(interaction.user.id)
            
            # ゲーム開始
            view = ChinchiroGameView(interaction.user, bet)
            await interaction.followup.send(
                f"🎲 **チンチロリン対戦開始！** (本日 {count + 1}/10 回目)\n賭け金: **{bet} {CURRENCY_NAME}**\nBot（親）と勝負します！下のボタンを押してサイコロを振ってください。",
                view=view,
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("数字を正しく入力してください。", ephemeral=True)

class ChinchiroGameView(discord.ui.View):
    def __init__(self, user, bet):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet

    @discord.ui.button(label="🎲 サイコロを振る！", style=discord.ButtonStyle.success)
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
            return

        # Botのロール
        bot_dice = [random.randint(1, 6) for _ in range(3)]
        bot_hand, bot_rank = self.get_hand_rank(bot_dice)
        
        # プレイヤーのロール
        player_dice = [random.randint(1, 6) for _ in range(3)]
        player_hand, player_rank = self.get_hand_rank(player_dice)
        
        # 判定
        result_msg = ""
        win_multiplier = 0
        
        if player_rank > bot_rank:
            # プレイヤーの勝利
            if player_hand == "ピンゾロ": win_multiplier = 10
            elif "アラシ" in player_hand: win_multiplier = 5
            elif player_hand == "シゴロ": win_multiplier = 3
            elif "出目" in player_hand: win_multiplier = 2
            else: win_multiplier = 1 # 通常勝ち
            
            win_amount = int(self.bet * (1 + win_multiplier)) # 賭け金返却 + 利益
            await database.add_balance(self.user.id, win_amount)
            result_msg = f"🏆 **あなたの勝ち！**\n役: {player_hand} (配当: {win_multiplier}倍)\n**{int(self.bet * win_multiplier)} {CURRENCY_NAME}** を獲得しました！"
            color = discord.Color.gold()
        elif player_rank < bot_rank:
            # プレイヤーの敗北
            result_msg = f"💀 **あなたの負け…**\nBotの役: {bot_hand}\n**{self.bet} {CURRENCY_NAME}** を失いました。"
            color = discord.Color.red()
        else:
            # 引き分け
            await database.add_balance(self.user.id, self.bet) # 賭け金を返却
            result_msg = "🤝 **引き分け！**\n賭け金が払い戻されました。"
            color = discord.Color.light_grey()

        embed = discord.Embed(title="🎲 チンチロリン対戦結果", color=color)
        embed.add_field(name="🤖 Bot（親）", value=f"[ {bot_dice[0]} | {bot_dice[1]} | {bot_dice[2]} ]\n役: {bot_hand}", inline=True)
        embed.add_field(name=f"👤 {self.user.display_name}（子）", value=f"[ {player_dice[0]} | {player_dice[1]} | {player_dice[2]} ]\n役: {player_hand}", inline=True)
        embed.add_field(name="結果", value=result_msg, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    def get_hand_rank(self, dice):
        dice.sort()
        # ピンゾロ
        if dice == [1, 1, 1]: return "ピンゾロ", 1000
        # アラシ
        if dice[0] == dice[1] == dice[2]: return f"アラシ({dice[0]})", 900 + dice[0]
        # シゴロ
        if dice == [4, 5, 6]: return "シゴロ", 800
        # ヒフミ
        if dice == [1, 2, 3]: return "ヒフミ", -100
        
        # 出目
        if dice[0] == dice[1]: score = dice[2]
        elif dice[1] == dice[2]: score = dice[0]
        elif dice[0] == dice[2]: score = dice[1]
        else: return "役なし", sum(dice) # 役なしの場合は合計値をランクにする
        
        return f"出目{score}", 100 + score

class ChinchiroView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎲 チンチロリンで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_chinchiro_btn")
    async def play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChinchiroBetModal())


@bot.tree.command(name="setup_chinchiro", description="【管理者専用】チンチロリンの設置パネルを送信します")
@is_admin()
async def setup_chinchiro(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎲 チンチロリン カジノ (対戦型)",
        description=(
            "Bot（親）とダイスで勝負！より強い役を出せば勝利です。\n"
            "**1日10回まで、上限10万コイン**まで賭けられます。\n\n"
            "**【配当倍率】**\n"
            "👑 ピンゾロ (1-1-1): **10倍**\n"
            "🌪 嵐（ゾロ目）: **5倍**\n"
            "✨ シゴロ (4-5-6): **3倍**\n"
            "🎯 出目あり (2つ揃い): **2倍**\n"
            "🗡️ 通常勝ち: **1倍**\n"
            "💀 ヒフミ (1-2-3): **没収**\n\n"
            "※引き分けは賭け金が戻ります。"
        ),
        color=discord.Color.dark_green()
    )
    await interaction.channel.send(embed=embed, view=ChinchiroView())
    await interaction.response.send_message("チンチロリンのパネルを設置しました。", ephemeral=True)


# --- コイントス システム ---

class CoinflipBetModal(discord.ui.Modal, title='コイントス：賭け金入力'):
    bet_input = discord.ui.TextInput(
        label='賭ける金額を入力してください',
        style=discord.TextStyle.short,
        placeholder='例: 1000',
        required=True,
        min_length=1,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0:
                await interaction.response.send_message("1以上の金額を入力してください。", ephemeral=True)
                return
            if bet > 100000:
                await interaction.response.send_message("ギャンブルの賭け金上限は 100,000 コインです。", ephemeral=True)
                return
            
            # 処理に時間がかかる可能性があるので defer
            await interaction.response.defer(ephemeral=True)

            # 共通回数制限チェック
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(JST)
            today_str = now.strftime("%Y-%m-%d")
            
            count = user_data.get("chinchiro_count", 0)
            last_date = user_data.get("chinchiro_last_date")
            
            if last_date != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str)
                count = 0
            
            if count >= 10:
                await interaction.followup.send("ギャンブルは全種類合計で1日10回までです。また明日挑戦してください！", ephemeral=True)
                return

            # 残高チェック
            bal = await database.get_balance(interaction.user.id)
            if bal < bet:
                await interaction.followup.send("残高が不足しています。", ephemeral=True)
                return
            
            # 表裏選択ビューを表示
            view = CoinflipGameView(interaction.user, bet, count)
            await interaction.followup.send(
                f"🪙 **コイントス勝負！** (本日 {count + 1}/10 回目)\n賭け金: **{bet} {CURRENCY_NAME}**\n「表」か「裏」か選んでください！",
                view=view,
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("数字を正しく入力してください。", ephemeral=True)

class CoinflipGameView(discord.ui.View):
    def __init__(self, user, bet, count):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet
        self.count = count

    @discord.ui.button(label="表", style=discord.ButtonStyle.primary, emoji="⚪")
    async def heads_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_flip(interaction, "heads")

    @discord.ui.button(label="裏", style=discord.ButtonStyle.secondary, emoji="⚫")
    async def tails_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_flip(interaction, "tails")

    async def process_flip(self, interaction, choice):
        if interaction.user != self.user:
            await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
            return

        # 残高不足チェック（引き落としはここで行う）
        success = await database.remove_balance(self.user.id, self.bet)
        if not success:
            await interaction.response.edit_message(content="残高が不足しています。", view=None)
            return
        
        await database.increment_gambling_count(self.user.id)

        result = random.choice(["heads", "tails"])
        result_ja = "表" if result == "heads" else "裏"
        
        if choice == result:
            win_amount = self.bet * 2
            await database.add_balance(self.user.id, win_amount)
            msg = f"🪙 結果は…「**{result_ja}**」！ (本日 {self.count + 1}/10 回目)\nおめでとうございます！ **{win_amount} {CURRENCY_NAME}** を獲得しました！"
            color = discord.Color.gold()
        else:
            msg = f"🪙 結果は…「**{result_ja}**」… (本日 {self.count + 1}/10 回目)\n残念！ **{self.bet} {CURRENCY_NAME}** を失いました。"
            color = discord.Color.red()

        embed = discord.Embed(title="🪙 コイントス結果", description=msg, color=color)
        await interaction.response.edit_message(content=None, embed=embed, view=None)
        self.stop()

class CoinflipView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🪙 コイントスで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_coinflip_btn")
    async def play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CoinflipBetModal())


@bot.tree.command(name="setup_coinflip", description="【管理者専用】コイントスの設置パネルを送信します")
@is_admin()
async def setup_coinflip(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🪙 コイントス・カジノ",
        description=(
            "コインの表か裏かを当てるシンプルなゲームです！\n"
            "当てれば賭け金が **2倍** になります。\n\n"
            "下のボタンを押して勝負を開始しましょう。"
        ),
        color=discord.Color.blue()
    )
    await interaction.channel.send(embed=embed, view=CoinflipView())
    await interaction.response.send_message("コイントスのパネルを設置しました。", ephemeral=True)


# --- スロット システム ---

class SlotBetModal(discord.ui.Modal, title='スロット：賭け金入力'):
    bet_input = discord.ui.TextInput(
        label='賭ける金額を入力してください',
        style=discord.TextStyle.short,
        placeholder='例: 1000',
        required=True,
        min_length=1,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0:
                await interaction.response.send_message("1以上の金額を入力してください。", ephemeral=True)
                return
            if bet > 100000:
                await interaction.response.send_message("ギャンブルの賭け金上限は 100,000 コインです。", ephemeral=True)
                return

            # 処理に時間がかかる可能性があるので defer
            await interaction.response.defer(ephemeral=True)

            # 共通回数制限チェック
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(JST)
            today_str = now.strftime("%Y-%m-%d")
            
            count = user_data.get("chinchiro_count", 0)
            last_date = user_data.get("chinchiro_last_date")
            
            if last_date != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str)
                count = 0
            
            if count >= 10:
                await interaction.followup.send("ギャンブルは全種類合計で1日10回までです。また明日挑戦してください！", ephemeral=True)
                return

            # 残高チェックと引き落とし
            success = await database.remove_balance(interaction.user.id, bet)
            if not success:
                await interaction.followup.send("残高が不足しています。", ephemeral=True)
                return
            
            await database.increment_gambling_count(interaction.user.id)

            # スロット実行
            emojis = ["🍒", "🍋", "🍉", "🔔", "⭐", "7️⃣"]
            r1, r2, r3 = random.choice(emojis), random.choice(emojis), random.choice(emojis)

            if r1 == r2 == r3:
                if r1 == "7️⃣": multiplier = 10
                elif r1 == "⭐": multiplier = 5
                else: multiplier = 3
            elif r1 == r2 or r2 == r3 or r1 == r3:
                multiplier = 1.5
            else:
                multiplier = 0

            win_amount = int(bet * multiplier)
            if win_amount > 0:
                await database.add_balance(interaction.user.id, win_amount)
                msg = f"🏆 **当たり！** (本日 {count + 1}/10 回目)\n[ {r1} | {r2} | {r3} ]\n**{win_amount} {CURRENCY_NAME}** を獲得しました！"
                color = discord.Color.gold()
            else:
                msg = f"💀 **ハズレ…** (本日 {count + 1}/10 回目)\n[ {r1} | {r2} | {r3} ]\n**{bet} {CURRENCY_NAME}** を失いました。"
                color = discord.Color.red()

            embed = discord.Embed(title="🎰 スロット結果", description=msg, color=color)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except ValueError:
            await interaction.response.send_message("数字を正しく入力してください。", ephemeral=True)

class SlotView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎰 スロットで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_slot_btn")
    async def play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SlotBetModal())

@bot.tree.command(name="setup_slots", description="【管理者専用】スロットの設置パネルを送信します")
@is_admin()
async def setup_slots(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎰 スロットマシン",
        description=(
            "絵柄を揃えて一攫千金を目指しましょう！\n\n"
            "**【配当倍率】**\n"
            "7️⃣7️⃣7️⃣ : **10倍**\n"
            "⭐⭐⭐ : **5倍**\n"
            "🔔🔔🔔 (他揃い) : **3倍**\n"
            "🍒🍒 (2つ揃い) : **1.5倍**\n\n"
            "下のボタンを押して挑戦！"
        ),
        color=discord.Color.orange()
    )
    await interaction.channel.send(embed=embed, view=SlotView())
    await interaction.response.send_message("スロットのパネルを設置しました。", ephemeral=True)


@bot.tree.command(name="setup_room_shop", description="【管理者専用】このチャンネルに「宿・高級宿」購入所のパネルを設置します")
@is_admin()
async def setup_room_shop(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏠 宿屋 購入所",
        description=f"下のボタンから購入したい部屋を選んでください。\n作成には **{CURRENCY_NAME}** が必要です。",
        color=discord.Color.gold()
    )
    await interaction.channel.send(embed=embed, view=RoomView())
    await interaction.response.send_message("宿の購入所を設置しました。", ephemeral=True)

@bot.tree.command(name="setup_custom_vc_shop", description="【管理者専用】このチャンネルに「カスタムVC」購入所のパネルを設置します")
@is_admin()
async def setup_custom_vc_shop(interaction: discord.Interaction):
    price = ROOM_SETTINGS['カスタムVC']['price']
    embed = discord.Embed(
        title="✨ カスタムVC 購入所",
        description=f"カスタムVCを立てますか？\nかかる料金: **{price} {CURRENCY_NAME}**",
        color=discord.Color.purple()
    )
    await interaction.channel.send(embed=embed, view=CustomRoomView())
    await interaction.response.send_message("カスタムVCの購入所を設置しました。", ephemeral=True)

if __name__ == "__main__":
    if TOKEN:
        discord.utils.setup_logging()
        keep_alive()
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN is not set in .env")
