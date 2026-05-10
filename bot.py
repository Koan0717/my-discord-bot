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

# 獲得量の設定
MSG_REWARD = 5        # メッセージ1通あたりの獲得量
MSG_COOLDOWN = 60     # メッセージ獲得のクールダウン（秒）
VC_REWARD_PER_MIN = 10# VC滞在1分あたりの獲得量
DAILY_REWARD = 1000   # デイリーボーナスの獲得量

# 部屋作成の設定
ROOM_SETTINGS = {
    "宿": {"price": 500, "duration_hours": 12},
    "高級宿": {"price": 2000, "duration_hours": 24},
    "カスタムVC": {"price": 5000, "duration_hours": 24}
}

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
        self.add_view(RoomControlView())
        self.add_view(CustomRoomControlView())
        self.add_view(ChinchiroView())
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
        now = datetime.datetime.now()
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
    now = datetime.datetime.now()

    # メッセージ報酬のクールダウンチェック
    last_msg_time = bot.message_cooldowns.get(user_id)
    if not last_msg_time or (now - last_msg_time).total_seconds() > MSG_COOLDOWN:
        await database.add_balance(user_id, MSG_REWARD)
        bot.message_cooldowns[user_id] = now
    
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    user_id = member.id
    now = datetime.datetime.now()

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

# --- スラッシュコマンド ---

@bot.tree.command(name="balance", description="自分の所持金を確認します（管理者は他のユーザーも確認可能）")
async def balance(interaction: discord.Interaction, user: discord.Member = None):
    # 他人の残高を見る場合、管理者権限（または自分自身）が必要
    target_user = user or interaction.user
    
    if target_user != interaction.user and not interaction.user.guild_permissions.administrator:
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
@app_commands.default_permissions(administrator=True)
async def give(interaction: discord.Interaction, target: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
        return
    
    await database.add_balance(target.id, amount)
    await interaction.response.send_message(f"運営から {target.mention} に **{amount} {CURRENCY_NAME}** が付与されました！")

@bot.tree.command(name="remove", description="【管理者専用】ユーザーの通貨を没収します")
@app_commands.default_permissions(administrator=True)
async def remove_money(interaction: discord.Interaction, target: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
        return
    
    await database.remove_balance(target.id, amount)
    await interaction.response.send_message(f"運営が {target.mention} から **{amount} {CURRENCY_NAME}** を没収しました。")

@bot.tree.command(name="daily", description="1日1回もらえるログインボーナス")
async def daily(interaction: discord.Interaction):
    user_data = await database.get_user(interaction.user.id)
    last_daily_str = user_data["last_daily"]
    now = datetime.datetime.now()

    if last_daily_str:
        last_daily = datetime.datetime.fromisoformat(last_daily_str)
        # 日付が変わっているかチェック
        if last_daily.date() == now.date():
            await interaction.response.send_message("今日のボーナスは既に受け取っています！明日また来てください。", ephemeral=True)
            return

    await database.add_balance(interaction.user.id, DAILY_REWARD)
    await database.update_last_daily(interaction.user.id, now)
    await interaction.response.send_message(f"デイリーボーナスを受け取りました！ **+{DAILY_REWARD} {CURRENCY_NAME}**")

@bot.tree.command(name="coinflip", description="コインの表裏を当てて所持金を増やそう！（勝てば2倍）")
@app_commands.choices(choice=[
    app_commands.Choice(name="表", value="heads"),
    app_commands.Choice(name="裏", value="tails"),
])
async def coinflip(interaction: discord.Interaction, amount: int, choice: app_commands.Choice[str]):
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を賭けてください。", ephemeral=True)
        return

    success = await database.remove_balance(interaction.user.id, amount)
    if not success:
        await interaction.response.send_message("残高が不足しています。", ephemeral=True)
        return

    result = random.choice(["heads", "tails"])
    result_ja = "表" if result == "heads" else "裏"
    
    if choice.value == result:
        win_amount = amount * 2
        await database.add_balance(interaction.user.id, win_amount)
        await interaction.response.send_message(f"結果は「{result_ja}」！おめでとうございます！ **{win_amount} {CURRENCY_NAME}** を獲得しました！")
    else:
        await interaction.response.send_message(f"結果は「{result_ja}」… 残念！ **{amount} {CURRENCY_NAME}** を失いました。")

@bot.tree.command(name="slots", description="スロットを回して一攫千金！（参加費を賭けて倍率ドン！）")
async def slots(interaction: discord.Interaction, bet: int):
    if bet <= 0:
        await interaction.response.send_message("1以上の金額を賭けてください。", ephemeral=True)
        return

    success = await database.remove_balance(interaction.user.id, bet)
    if not success:
        await interaction.response.send_message("残高が不足しています。", ephemeral=True)
        return

    emojis = ["🍒", "🍋", "🍉", "🔔", "⭐", "7️⃣"]
    r1, r2, r3 = random.choice(emojis), random.choice(emojis), random.choice(emojis)

    # 倍率設定
    if r1 == r2 == r3:
        if r1 == "7️⃣":
            multiplier = 10
        elif r1 == "⭐":
            multiplier = 5
        else:
            multiplier = 3
    elif r1 == r2 or r2 == r3 or r1 == r3:
        multiplier = 1.5
    else:
        multiplier = 0

    win_amount = int(bet * multiplier)
    if win_amount > 0:
        await database.add_balance(interaction.user.id, win_amount)
        msg = f"🎰 スロット結果 🎰\n[ {r1} | {r2} | {r3} ]\n当たり！ **{win_amount} {CURRENCY_NAME}** を獲得しました！"
    else:
        msg = f"🎰 スロット結果 🎰\n[ {r1} | {r2} | {r3} ]\nハズレ… **{bet} {CURRENCY_NAME}** を失いました。"

    await interaction.response.send_message(msg)

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


class RoomControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="延長", style=discord.ButtonStyle.primary, emoji="⏱", custom_id="persistent_extend_btn")
    async def extend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_extend(interaction)

    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, emoji="🗑", custom_id="persistent_delete_btn")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_delete(interaction)


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

# --- VC購入システム ---
async def process_room_purchase(interaction: discord.Interaction, room_type: str, is_confirm_view: bool = False):
    async def reply(msg: str):
        if is_confirm_view:
            await interaction.response.edit_message(content=msg, view=None)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

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

    # 残高確認と引き落とし
    success = await database.remove_balance(interaction.user.id, price)
    if not success:
        await reply(f"残高が不足しています！(所持金が {price} {CURRENCY_NAME} 未満です)")
        return

    # VC作成処理
    guild = interaction.guild
    category = interaction.channel.category # コマンドを実行したカテゴリの下に作る
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=True),
        interaction.user: discord.PermissionOverwrite(manage_channels=True, move_members=True)
    }

    if room_type == "高級宿":
        overwrites[interaction.user].manage_permissions = True

    channel_name = f"{room_type}-{interaction.user.display_name}"
    new_vc = await guild.create_voice_channel(name=channel_name, category=category, overwrites=overwrites)

    # データベースに登録
    expire_at = datetime.datetime.now() + datetime.timedelta(hours=duration)
    await database.add_room(new_vc.id, interaction.user.id, room_type, expire_at)

    await reply(f"**{price} {CURRENCY_NAME}** を支払い、{new_vc.mention} を作成しました！")

    # VC内にコントロールパネルを送信
    view = CustomRoomControlView() if room_type == "カスタムVC" else RoomControlView()
    embed = discord.Embed(
        title=f"🏠 {room_type}",
        description=f"{interaction.user.mention} がこの部屋を作成しました。\n**終了予定時刻:** <t:{int(expire_at.timestamp())}:F>\n\n時間になるか「削除」を押すとこのチャンネルは自動で消滅します。\n時間を延ばしたい場合は「延長」を押してください。",
        color=discord.Color.blue()
    )
    await new_vc.send(content=f"{interaction.user.mention}", embed=embed, view=view)


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
            
            # 残高チェックと引き落とし
            success = await database.remove_balance(interaction.user.id, bet)
            if not success:
                await interaction.response.send_message("残高が不足しています。", ephemeral=True)
                return
            
            # ゲーム開始
            view = ChinchiroGameView(interaction.user, bet)
            await interaction.response.send_message(
                f"🎲 **チンチロリン開始！**\n賭け金: **{bet} {CURRENCY_NAME}**\n下のボタンを押してサイコロを振ってください（最大3回まで）。",
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
        self.rolls_left = 3
        self.history = []

    @discord.ui.button(label="🎲 サイコロを振る", style=discord.ButtonStyle.success)
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
            return

        self.rolls_left -= 1
        dice = [random.randint(1, 6) for _ in range(3)]
        dice.sort()
        
        result_text = f"回目: [ {dice[0]} | {dice[1]} | {dice[2]} ]"
        hand, multiplier = self.get_hand(dice)
        
        if hand:
            # 役が出た場合、終了
            win_amount = int(self.bet * multiplier)
            if win_amount > 0:
                await database.add_balance(self.user.id, win_amount)
                status = f"✅ **{hand}！** 配当 **{multiplier}倍** で **{win_amount} {CURRENCY_NAME}** 獲得！"
            else:
                status = f"💀 **{hand}…** 没収です。"
            
            self.history.append(f"{3 - self.rolls_left}{result_text} → {hand}")
            embed = self.create_embed(status, finished=True)
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()
        else:
            # 目なしの場合
            if self.rolls_left > 0:
                status = f"☁️ **目なし…** あと **{self.rolls_left}回** 振れます。"
                self.history.append(f"{3 - self.rolls_left}{result_text} → 目なし")
                embed = self.create_embed(status)
                button.label = f"🎲 サイコロを振る (残り{self.rolls_left}回)"
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                status = "💀 **3回とも目なし…** 没収です。"
                self.history.append(f"{3 - self.rolls_left}{result_text} → 目なし(終了)")
                embed = self.create_embed(status, finished=True)
                await interaction.response.edit_message(embed=embed, view=None)
                self.stop()

    def get_hand(self, dice):
        # ピンゾロ (1,1,1)
        if dice == [1, 1, 1]:
            return "ピンゾロ", 5.0
        # アラシ (ゾロ目)
        if dice[0] == dice[1] == dice[2]:
            return f"アラシ({dice[0]})", 3.0
        # シゴロ (4,5,6)
        if dice == [4, 5, 6]:
            return "シゴロ", 2.0
        # ヒフミ (1,2,3)
        if dice == [1, 2, 3]:
            return "ヒフミ", 0.0
        
        # 通常の出目 (2つが同じ)
        if dice[0] == dice[1]:
            score = dice[2]
        elif dice[1] == dice[2]:
            score = dice[0]
        elif dice[0] == dice[2]:
            score = dice[1]
        else:
            return None, 0 # 目なし

        if score == 6: return "出目6", 1.5
        if score in [4, 5]: return f"出目{score}", 1.2
        return f"出目{score}", 0.0 # 1,2,3はハズレ

    def create_embed(self, status, finished=False):
        embed = discord.Embed(
            title="🎲 チンチロリン",
            color=discord.Color.green() if not finished else (discord.Color.gold() if "獲得" in status else discord.Color.red())
        )
        history_text = "\n".join(self.history)
        embed.add_field(name="これまでの履歴", value=history_text if history_text else "まだ振っていません", inline=False)
        embed.add_field(name="現在の状況", value=status, inline=False)
        if finished:
            embed.set_footer(text="ゲーム終了")
        return embed

class ChinchiroView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎲 チンチロリンで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_chinchiro_btn")
    async def play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChinchiroBetModal())


@bot.tree.command(name="setup_chinchiro", description="【管理者専用】チンチロリンの設置パネルを送信します")
@app_commands.default_permissions(administrator=True)
async def setup_chinchiro(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎲 チンチロリン カジノ",
        description="サイコロを3つ振り、役が揃えば配当ゲット！\n最大3回まで振り直すことができます。\n\n**【配当表】**\n・ピンゾロ(1,1,1): **5倍**\n・アラシ(ゾロ目): **3倍**\n・シゴロ(4,5,6): **2倍**\n・出目6: **1.5倍**\n・出目4,5: **1.2倍**\n・ヒフミ(1,2,3) / 出目1,2,3: **没収**",
        color=discord.Color.dark_green()
    )
    await interaction.channel.send(embed=embed, view=ChinchiroView())
    await interaction.response.send_message("チンチロリンのパネルを設置しました。", ephemeral=True)


@bot.tree.command(name="setup_room_shop", description="【管理者専用】このチャンネルに「宿・高級宿」購入所のパネルを設置します")
@app_commands.default_permissions(administrator=True)
async def setup_room_shop(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏠 宿屋 購入所",
        description=f"下のボタンから購入したい部屋を選んでください。\n作成には **{CURRENCY_NAME}** が必要です。",
        color=discord.Color.gold()
    )
    await interaction.channel.send(embed=embed, view=RoomView())
    await interaction.response.send_message("宿の購入所を設置しました。", ephemeral=True)

@bot.tree.command(name="setup_custom_vc_shop", description="【管理者専用】このチャンネルに「カスタムVC」購入所のパネルを設置します")
@app_commands.default_permissions(administrator=True)
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
