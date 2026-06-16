import discord
from discord.ext import commands
from discord import app_commands
import database
import config
import datetime
import os

# 他の Cog / View のインポート
from cogs.reaction_roles import CustomRolePanelSetupModal
from cogs.tickets import InquiryRequestPanelView, EmblemRequestPanelView, ConfessionRequestPanelView, CustomTicketSetupModal, InquirySetupView
from cogs.rooms import MainInnPanelView, TempInnPanelView, LuxuryInnPanelView, CustomRoomView, VCRenamePanelView
from cogs.gambling import ChinchiroView, CoinflipView, SlotView, BlackjackView, RouletteView

# --- 運営権限チェック ---
def is_admin():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild:
            return False
        if config.has_admin_role(interaction.client, interaction.user):
            return True
        await interaction.response.send_message("このコマンドを実行する権限がありません（運営専用ロールが必要です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    AdminGroup = app_commands.Group(name="管理者", description="【管理者専用】管理コマンド")

    @AdminGroup.command(name="bot初期設定", description="【管理者専用】Discord内でBotのロールやチャンネルを設定できる管理画面を表示します")
    @is_admin()
    async def bot_setup(self, interaction: discord.Interaction):
        view = BotSetupMainView(interaction.user)
        embed = view.build_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @AdminGroup.command(name="パネル設置", description="【管理者専用】自分にしか見えないパネル設定画面を表示し、各種パネルを設置します")
    @is_admin()
    async def panel_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await update_main_admin_panel(interaction, self.bot)

    @AdminGroup.command(name="ランクリセット", description="ランクを初期化します")
    @is_admin()
    @app_commands.describe(user="リセットする特定のユーザー", all_players="サーバー全員をリセットする場合は『はい』を選択")
    async def rank_reset(self, interaction: discord.Interaction, user: discord.Member = None, all_players: bool = False):
        await interaction.response.defer(ephemeral=True)
        
        if all_players:
            p = await database.get_pool()
            async with p.acquire() as conn:
                await conn.execute('UPDATE users SET tc_xp = 0, tc_level = 1, vc_xp = 0, vc_level = 1')
            await interaction.followup.send("✅ 全ユーザーのランクをリセットしました。", ephemeral=True)
        elif user:
            await database.reset_user_rank(user.id)
            await interaction.followup.send(f"✅ {user.mention} のランクをリセットしました。", ephemeral=True)
        else:
            await interaction.followup.send("❌ エラー: ユーザーを指定するか、『全プレイヤー』に『はい』を選択してください。", ephemeral=True)

    @AdminGroup.command(name="通貨付与", description="指定ユーザーに通貨を付与（最大10人まで）")
    @app_commands.describe(
        target1="付与先1",
        amount="1人あたりの金額",
        target2="付与先2（任意）",
        target3="付与先3（任意）",
        target4="付与先4（任意）",
        target5="付与先5（任意）",
        target6="付与先6（任意）",
        target7="付与先7（任意）",
        target8="付与先8（任意）",
        target9="付与先9（任意）",
        target10="付与先10（任意）"
    )
    @is_admin()
    async def give(
        self, 
        it: discord.Interaction, 
        target1: discord.Member, 
        amount: int,
        target2: discord.Member = None,
        target3: discord.Member = None,
        target4: discord.Member = None,
        target5: discord.Member = None,
        target6: discord.Member = None,
        target7: discord.Member = None,
        target8: discord.Member = None,
        target9: discord.Member = None,
        target10: discord.Member = None
    ):
        targets = [t for t in [target1, target2, target3, target4, target5, target6, target7, target8, target9, target10] if t is not None]
        valid_targets = []
        for t in targets:
            if t not in valid_targets:
                valid_targets.append(t)
                
        await it.response.defer()
        
        for t in valid_targets:
            await database.add_balance(t.id, amount)
            await it.followup.send(f"✅ {t.mention} に {amount} {config.CURRENCY_NAME} 付与しました。")
            await config.send_economy_log(
                it.guild,
                "💰 通貨付与",
                f"管理者の {it.user.mention} が {t.mention} に **{amount} {config.CURRENCY_NAME}** を付与しました。",
                user=it.user
            )

    @AdminGroup.command(name="通貨没収", description="指定ユーザーから通貨を没収")
    @is_admin()
    async def remove(self, it, target: discord.Member, amount: int):
        await database.remove_balance(target.id, amount)
        await it.response.send_message(f"✅ {target.mention} から {amount} {config.CURRENCY_NAME} 没収しました。")
        await config.send_economy_log(
            it.guild,
            "📉 通貨没収",
            f"管理者の {it.user.mention} が {target.mention} から **{amount} {config.CURRENCY_NAME}** を没収しました。",
            user=it.user,
            color=discord.Color.red()
        )

    @AdminGroup.command(name="所持金リセット", description="所持金の初期化")
    @app_commands.checks.has_permissions(administrator=True)
    async def rbal(self, it, user: discord.Member):
        await database.reset_user_balance(user.id); await it.response.send_message("リセット完了", ephemeral=True)
        await config.send_economy_log(
            it.guild,
            "🔄 所持金リセット",
            f"管理者の {it.user.mention} が {user.mention} の所持金をリセットしました。",
            user=it.user,
            color=discord.Color.red()
        )

    @AdminGroup.command(name="デバッグ_vc", description="【管理者用】一時部屋のDB登録状況を確認します")
    @is_admin()
    async def debug_vc(self, it):
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM rooms WHERE room_type = $1', "一時部屋")
        
        if not rows:
            return await it.response.send_message("現在、DBに登録されている一時部屋はありません。", ephemeral=True)
        
        txt = "【DB登録済みの一時部屋】\n"
        for r in rows:
            ch = self.bot.get_channel(r['channel_id'])
            status = f"✅ 存在 ({ch.name})" if ch else "❌ チャンネル消失"
            txt += f"- CH ID: {r['channel_id']} | 所有者ID: {r['owner_id']} | {status}\n"
        
        await it.response.send_message(txt[:2000], ephemeral=True)

    @AdminGroup.command(name="テンプレ作成", description="【管理者専用】現在のチャンネルに常設するテンプレートを作成します")
    @is_admin()
    async def sticky_template_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StickyTemplateModal())

    @AdminGroup.command(name="テンプレ削除", description="【管理者専用】現在のチャンネルの常設テンプレートを削除します")
    @is_admin()
    async def sticky_template_delete(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = interaction.channel_id
        data = await database.get_sticky_template(channel_id)
        if not data:
            return await interaction.followup.send("❌ このチャンネルには常設テンプレートが設定されていません。", ephemeral=True)
        
        await database.delete_sticky_template(channel_id)
        
        if data["last_message_id"]:
            try:
                msg = await interaction.channel.fetch_message(data["last_message_id"])
                await msg.delete()
            except:
                pass
        
        if data.get("last_text_message_id"):
            try:
                text_msg = await interaction.channel.fetch_message(data["last_text_message_id"])
                await text_msg.delete()
            except:
                pass
        await interaction.followup.send("✅ 常設テンプレートを削除しました。", ephemeral=True)

async def setup(bot):
    cog = AdminCog(bot)
    await bot.add_cog(cog)

# --- ヘルパーと設定用ビュー ---

def format_setting_status(guild, key):
    val = config.get_setting(None, key) # デフォルト値取得用
    is_unset = False
    if val is None:
        is_unset = True
    elif isinstance(val, list) and not val:
        is_unset = True
    elif isinstance(val, int) and (val == 123456789012345678 or val == 0):
        is_unset = True
    
    if is_unset:
        return "❌ 未設定"
        
    if "ROLE" in key:
        if isinstance(val, list):
            roles = [guild.get_role(rid) for rid in val]
            mentions = [role.mention for role in roles if role]
            return ", ".join(mentions) if mentions else "❌ 未設定 (ロールが見つかりません)"
        else:
            role = guild.get_role(val)
            return role.mention if role else "❌ 未設定 (ロールが見つかりません)"
    elif "CHANNEL" in key or "FORUM" in key:
        if isinstance(val, list):
            channels = [guild.get_channel(cid) for cid in val]
            mentions = [ch.mention for ch in channels if ch]
            return ", ".join(mentions) if mentions else "❌ 未設定 (チャンネルが見つかりません)"
        else:
            ch = guild.get_channel(val)
            return ch.mention if ch else "❌ 未設定 (チャンネルが見つかりません)"
    elif "CATEGORY" in key:
        cat = guild.get_channel(val)
        return f"📁 {cat.name}" if cat else "❌ 未設定 (カテゴリーが見つかりません)"
    return str(val)

# --- VC作成トリガー管理パネル用UI ---

async def update_config_view(interaction: discord.Interaction, bot):
    view = VCTriggersConfigView(bot)
    
    embed = discord.Embed(
        title="🎙️ VC作成トリガー設定パネル",
        description=(
            "ユーザーが参加した際に一時部屋を自動作成するチャンネルを設定できます。\n\n"
            "**【追加】** 下のドロップダウンからボイスチャンネルを選択してください。\n"
            "**【削除】** 登録済みのチャンネルを削除するには、削除用ドロップダウンを使用してください。"
        ),
        color=discord.Color.blue()
    )
    
    triggers_str = ""
    for tid in bot.auto_vc_triggers:
        ch = bot.get_channel(tid)
        if ch:
            triggers_str += f"• {ch.mention} (ID: `{tid}`)\n"
        else:
            triggers_str += f"• ⚠️ 不明なチャンネル (ID: `{tid}`)\n"
    if not triggers_str:
        triggers_str = "登録されているトリガーチャンネルはありません。"
    embed.add_field(name="現在の登録チャンネル", value=triggers_str, inline=False)
    
    await interaction.response.edit_message(embed=embed, view=view)

class AddVCTriggerSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="追加するボイスチャンネルを選択...",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel = self.values[0]
        
        if channel.id in bot.auto_vc_triggers:
            return await interaction.response.send_message(f"❌ {channel.mention} は既に登録されています。", ephemeral=True)
            
        await database.add_auto_vc_trigger(channel.id)
        bot.auto_vc_triggers.add(channel.id)
        
        await update_config_view(interaction, bot)

class RemoveVCTriggerSelect(discord.ui.Select):
    def __init__(self, bot):
        options = []
        for tid in bot.auto_vc_triggers:
            ch = bot.get_channel(tid)
            name = ch.name if ch else f"不明なチャンネル ({tid})"
            options.append(discord.SelectOption(
                label=name,
                value=str(tid),
                description=f"ID: {tid}"
            ))
        super().__init__(
            placeholder="削除するトリガーチャンネルを選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel_id = int(self.values[0])
        
        if channel_id not in bot.auto_vc_triggers:
            return await interaction.response.send_message(f"❌ そのチャンネルは登録されていません。", ephemeral=True)
            
        await database.remove_auto_vc_trigger(channel_id)
        bot.auto_vc_triggers.discard(channel_id)
        
        await update_config_view(interaction, bot)

class VCTriggersConfigView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.add_item(AddVCTriggerSelect())
        if bot.auto_vc_triggers:
            self.add_item(RemoveVCTriggerSelect(bot))

class ManageVCTriggersButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="VC作成トリガーを設定",
            style=discord.ButtonStyle.secondary,
            emoji="🎙️",
            custom_id="persistent_admin_manage_vc_triggers_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        bot = interaction.client
        view = VCTriggersConfigView(bot)
        
        embed = discord.Embed(
            title="🎙️ VC作成トリガー設定パネル",
            description=(
                "ユーザーが参加した際に一時部屋を自動作成するチャンネルを設定できます。\n\n"
                "**【追加】** 下のドロップダウンからボイスチャンネルを選択してください。\n"
                "**【削除】** 登録済みのチャンネルを削除するには、削除用ドロップダウンを使用してください。"
            ),
            color=discord.Color.blue()
        )
        
        triggers_str = ""
        for tid in bot.auto_vc_triggers:
            ch = bot.get_channel(tid)
            if ch:
                triggers_str += f"• {ch.mention} (ID: `{tid}`)\n"
            else:
                triggers_str += f"• ⚠️ 不明なチャンネル (ID: `{tid}`)\n"
        if not triggers_str:
            triggers_str = "登録されているトリガーチャンネルはありません。"
        embed.add_field(name="現在の登録チャンネル", value=triggers_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --- レベルロール設定用UI ---

class LevelTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="💬 テキスト活動 (TC)", value="tc", description="TCレベルに基づく報酬"),
            discord.SelectOption(label="🎙️ ボイス活動 (VC)", value="vc", description="VCレベルに基づく報酬")
        ]
        super().__init__(placeholder="レベルタイプ（TC/VC）を選択...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_level_type = self.values[0]
        await interaction.response.defer()

class LevelRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="付与するロールを選択...", min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_role = self.values[0]
        await interaction.response.defer()

class LevelInputModal(discord.ui.Modal, title='レベルロール設定：レベル入力'):
    level_input = discord.ui.TextInput(label='目標レベル', placeholder='例: 10', max_length=5, required=True)

    def __init__(self, level_type: str, role: discord.Role, parent_view):
        super().__init__()
        self.level_type = level_type
        self.role = role
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(self.level_input.value)
            if level <= 0:
                return await interaction.response.send_message("❌ 1以上のレベルを指定してください。", ephemeral=True)
            
            await database.add_level_role_reward(self.level_type, level, self.role.id)
            
            self.parent_view.selected_role = None
            self.parent_view.selected_level_type = None
            
            await update_level_roles_config_view(interaction)
        except ValueError:
            await interaction.response.send_message("❌ レベルは半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] LevelInputModal: {e}")
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True)

class AddLevelRoleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="レベルを指定して追加", style=discord.ButtonStyle.success, emoji="➕", row=2)

    async def callback(self, interaction: discord.Interaction):
        if not getattr(self.view, "selected_level_type", None):
            return await interaction.response.send_message("❌ 先にレベルタイプ（TC/VC）を選択してください。", ephemeral=True)
        if not getattr(self.view, "selected_role", None):
            return await interaction.response.send_message("❌ 先に付与するロールを選択してください。", ephemeral=True)

        modal = LevelInputModal(self.view.selected_level_type, self.view.selected_role, self.view)
        await interaction.response.send_modal(modal)

class RemoveLevelRoleSelect(discord.ui.Select):
    def __init__(self, rewards, guild: discord.Guild):
        options = []
        for r in rewards:
            ltype = "TC" if r["level_type"] == "tc" else "VC"
            role = guild.get_role(r["role_id"])
            role_name = role.name if role else f"不明なロール (ID: {r['role_id']})"
            options.append(discord.SelectOption(
                label=f"[{ltype}] Lv.{r['level']} ➔ {role_name}",
                value=f"{r['level_type']}:{r['level']}:{r['role_id']}",
                description=f"ロールID: {r['role_id']}"
            ))
        super().__init__(
            placeholder="削除するレベルロール報酬を選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        level_type, level_str, role_id_str = val.split(":")
        level = int(level_str)
        role_id = int(role_id_str)
        
        await database.remove_level_role_reward(level_type, level, role_id)
        
        await update_level_roles_config_view(interaction)

class LevelRolesConfigView(discord.ui.View):
    def __init__(self, rewards, guild: discord.Guild):
        super().__init__(timeout=180)
        self.selected_level_type = None
        self.selected_role = None
        
        self.add_item(LevelTypeSelect())
        self.add_item(LevelRoleSelect())
        self.add_item(AddLevelRoleButton())
        if rewards:
            self.add_item(RemoveLevelRoleSelect(rewards, guild))

async def update_level_roles_config_view(interaction: discord.Interaction):
    rewards = await database.get_level_role_rewards()
    view = LevelRolesConfigView(rewards, interaction.guild)
    
    embed = discord.Embed(
        title="🎁 レベルロール設定パネル",
        description=(
            "レベルに応じて付与されるロールを設定します。\n\n"
            "**【設定手順】**\n"
            "1. **レベルタイプ**（TC/VC）を選択します。\n"
            "2. **付与するロール**を選択します。\n"
            "3. **「レベルを指定して追加」**ボタンを押し、目標レベルを入力します。\n\n"
            "**【削除手順】**\n"
            "一番下の削除用ドロップダウンから、削除したい報酬設定を選択します。"
        ),
        color=discord.Color.blue()
    )
    
    rewards_str = ""
    for r in rewards:
        ltype = "💬 TC" if r["level_type"] == "tc" else "🎙️ VC"
        role = interaction.guild.get_role(r["role_id"])
        role_mention = role.mention if role else f"⚠️ 不明なロール (ID: `{r['role_id']}`)"
        rewards_str += f"• **{ltype}** Lv.{r['level']} ➔ {role_mention}\n"
        
    if not rewards_str:
        rewards_str = "登録されているレベルロール報酬はありません。"
        
    embed.add_field(name="現在の設定一覧", value=rewards_str, inline=False)
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class ManageLevelRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="レベルロールを設定",
            style=discord.ButtonStyle.secondary,
            emoji="🎁",
            custom_id="persistent_admin_manage_level_roles_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        rewards = await database.get_level_role_rewards()
        view = LevelRolesConfigView(rewards, interaction.guild)
        
        embed = discord.Embed(
            title="🎁 レベルロール設定パネル",
            description=(
                "レベルに応じて付与されるロールを設定します。\n\n"
                "**【設定手順】**\n"
                "1. **レベルタイプ**（TC/VC）を選択します。\n"
                "2. **付与するロール**を選択します。\n"
                "3. **「レベルを指定して追加」**ボタンを押し、目標レベルを入力します。\n\n"
                "**【削除手順】**\n"
                "一番下の削除用ドロップダウンから、削除したい報酬設定を選択します。"
            ),
            color=discord.Color.blue()
        )
        
        rewards_str = ""
        for r in rewards:
            ltype = "💬 TC" if r["level_type"] == "tc" else "🎙️ VC"
            role = interaction.guild.get_role(r["role_id"])
            role_mention = role.mention if role else f"⚠️ 不明なロール (ID: `{r['role_id']}`)"
            rewards_str += f"• **{ltype}** Lv.{r['level']} ➔ {role_mention}\n"
            
        if not rewards_str:
            rewards_str = "登録されているレベルロール報酬はありません。"
            
        embed.add_field(name="現在の設定一覧", value=rewards_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --- 部屋価格設定用UI ---

class RoomPriceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="一般宿 - 12時間", value="宿:12", emoji="🛖"),
            discord.SelectOption(label="一般宿 - 24時間", value="宿:24", emoji="🛖"),
            discord.SelectOption(label="高級宿 - 12時間", value="高級宿:12", emoji="🏰"),
            discord.SelectOption(label="高級宿 - 24時間", value="高級宿:24", emoji="🏰"),
            discord.SelectOption(label="カスタムVC - 24時間", value="カスタムVC:24", emoji="✨")
        ]
        super().__init__(placeholder="価格を変更する部屋タイプを選択...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        rtype, dur_str = self.values[0].split(":")
        duration = int(dur_str)
        
        modal = PriceInputModal(rtype, duration)
        await interaction.response.send_modal(modal)

class PriceInputModal(discord.ui.Modal, title='部屋価格の設定'):
    price_input = discord.ui.TextInput(label='新しい価格', placeholder='例: 12000', max_length=10, required=True)

    def __init__(self, room_type: str, duration: int):
        super().__init__()
        self.room_type = room_type
        self.duration = duration
        self.price_input.label = f"新しい価格 ({config.CURRENCY_NAME})"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price_input.value)
            if price < 0:
                return await interaction.response.send_message("❌ 0以上の価格を入力してください。", ephemeral=True)
            
            await database.update_room_price(self.room_type, self.duration, price)
            config.ROOM_SETTINGS[self.room_type][self.duration]["price"] = price
            
            await update_room_prices_config_view(interaction)
        except ValueError:
            await interaction.response.send_message("❌ 半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] PriceInputModal: {e}")
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True)

class RoomPricesConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(RoomPriceSelect())

async def update_room_prices_config_view(interaction: discord.Interaction):
    view = RoomPricesConfigView()
    embed = discord.Embed(
        title="🏨 部屋の価格設定",
        description=(
            "一般宿・高級宿・カスタムVCの作成/延長時の価格を変更します。\n\n"
            "**【変更手順】**\n"
            "下のドロップダウンメニューから、価格を変更したい部屋と時間を選択し、開いたモーダルで新しい価格を入力してください。"
        ),
        color=discord.Color.blue()
    )
    
    prices_str = ""
    for rtype, dur_map in config.ROOM_SETTINGS.items():
        emoji = "🛖" if rtype == "宿" else ("🏰" if rtype == "高級宿" else "✨")
        display_name = "一般宿" if rtype == "宿" else rtype
        for dur, settings in dur_map.items():
            prices_str += f"{emoji} **{display_name} ({dur}時間)**: {settings['price']:,} {config.CURRENCY_NAME}\n"
            
    embed.add_field(name="現在の価格設定", value=prices_str, inline=False)
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class ManageRoomPricesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="部屋価格を設定",
            style=discord.ButtonStyle.secondary,
            emoji="💰",
            custom_id="persistent_admin_manage_room_prices_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        view = RoomPricesConfigView()
        embed = discord.Embed(
            title="🏨 部屋の価格設定",
            description=(
                "一般宿・高級宿・カスタムVCの作成/延長時の価格を変更します。\n\n"
                "**【変更手順】**\n"
                "下のドロップダウンメニューから、価格を変更したい部屋と時間を選択し、開いたモーダルで新しい価格を入力してください。"
            ),
            color=discord.Color.blue()
        )
        
        prices_str = ""
        for rtype, dur_map in config.ROOM_SETTINGS.items():
            emoji = "🛖" if rtype == "宿" else ("🏰" if rtype == "高級宿" else "✨")
            display_name = "一般宿" if rtype == "宿" else rtype
            for dur, settings in dur_map.items():
                prices_str += f"{emoji} **{display_name} ({dur}時間)**: {settings['price']:,} {config.CURRENCY_NAME}\n"
                
        embed.add_field(name="現在の価格設定", value=prices_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --- ログ設定用UI ---

class LogTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="📝 メッセージ編集", value="message_edit", description="メッセージ編集ログ"),
            discord.SelectOption(label="🗑️ メッセージ削除", value="message_delete", description="メッセージ削除ログ"),
            discord.SelectOption(label="🎙️ VC参加・退出", value="vc_join_leave", description="VC参加・移動・退出ログ"),
            discord.SelectOption(label="👥 メンバー入退", value="member_join_leave", description="サーバー参加・退出ログ"),
            discord.SelectOption(label="💰 通貨・経済", value="economy", description="通貨の付与・送金・お渡し等のログ")
        ]
        super().__init__(placeholder="設定するログの種類を選択...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_log_type = self.values[0]
        await interaction.response.defer()

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="送信先テキストチャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_channel = self.values[0]
        await interaction.response.defer()

class SaveLogSettingButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="ログ設定を保存", style=discord.ButtonStyle.success, emoji="💾", row=2)

    async def callback(self, interaction: discord.Interaction):
        log_type = getattr(self.view, "selected_log_type", None)
        channel = getattr(self.view, "selected_channel", None)
        
        if not log_type:
            return await interaction.response.send_message("❌ 先にログの種類を選択してください。", ephemeral=True)
        if not channel:
            return await interaction.response.send_message("❌ 先に送信先チャンネルを選択してください。", ephemeral=True)

        try:
            await database.set_log_channel(interaction.guild_id, log_type, channel.id)
            self.view.selected_log_type = None
            self.view.selected_channel = None
            await update_log_settings_config_view(interaction)
        except Exception as e:
            print(f"[ERROR] SaveLogSettingButton: {e}")
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True)

class RemoveLogSettingSelect(discord.ui.Select):
    def __init__(self, settings, guild: discord.Guild):
        options = []
        log_types = {
            "message_edit": "メッセージ編集",
            "message_delete": "メッセージ削除",
            "vc_join_leave": "VC参加・退出",
            "member_join_leave": "メンバー入退",
            "economy": "通貨・経済"
        }
        for l_type, ch_id in settings.items():
            ch = guild.get_channel(ch_id)
            ch_name = f"#{ch.name}" if ch else f"不明なチャンネル (ID: {ch_id})"
            options.append(discord.SelectOption(
                label=f"{log_types.get(l_type, l_type)} ➔ {ch_name}",
                value=l_type,
                description=f"ログ設定を解除します"
            ))
        super().__init__(
            placeholder="解除するログ設定を選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        log_type = self.values[0]
        await database.remove_log_channel(interaction.guild_id, log_type)
        await update_log_settings_config_view(interaction)

class LogSettingsConfigView(discord.ui.View):
    def __init__(self, settings, guild: discord.Guild):
        super().__init__(timeout=180)
        self.selected_log_type = None
        self.selected_channel = None
        
        self.add_item(LogTypeSelect())
        self.add_item(LogChannelSelect())
        self.add_item(SaveLogSettingButton())
        if settings:
            self.add_item(RemoveLogSettingSelect(settings, guild))

async def update_log_settings_config_view(interaction: discord.Interaction):
    settings = await database.get_all_log_settings(interaction.guild_id)
    view = LogSettingsConfigView(settings, interaction.guild)
    
    embed = discord.Embed(
        title="📋 サーバーログ設定パネル",
        description=(
            "サーバー内で発生する各種イベントのログ送信先を設定します。\n\n"
            "**【設定手順】**\n"
            "1. **ログの種類**を選択します。\n"
            "2. **送信先テキストチャンネル**を選択します。\n"
            "3. **「ログ設定を保存」**ボタンを押します。\n\n"
            "**【解除手順】**\n"
            "一番下の解除用ドロップダウンから、解除したい設定を選択します。"
        ),
        color=discord.Color.blue()
    )
    
    log_types = {
        "message_edit": "📝 メッセージ編集",
        "message_delete": "🗑️ メッセージ削除",
        "vc_join_leave": "🎙️ VC参加・退出",
        "member_join_leave": "👥 メンバー入退",
        "economy": "💰 通貨・経済"
    }
    
    settings_str = ""
    for l_type, display_name in log_types.items():
        ch_id = settings.get(l_type)
        if ch_id:
            channel = interaction.guild.get_channel(ch_id)
            ch_mention = channel.mention if channel else f"⚠️ 不明なチャンネル (ID: `{ch_id}`)"
        else:
            ch_mention = "未設定"
        settings_str += f"• **{display_name}**: {ch_mention}\n"
        
    embed.add_field(name="現在の設定一覧", value=settings_str, inline=False)
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class ManageLogSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="ログを設定",
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            custom_id="persistent_admin_manage_log_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        settings = await database.get_all_log_settings(interaction.guild_id)
        view = LogSettingsConfigView(settings, interaction.guild)
        
        embed = discord.Embed(
            title="📋 サーバーログ設定パネル",
            description=(
                "サーバー内で発生する各種イベントのログ送信先を設定します。\n\n"
                "**【設定手順】**\n"
                "1. **ログの種類**を選択します。\n"
                "2. **送信先テキストチャンネル**を選択します。\n"
                "3. **「ログ設定を保存」**ボタンを押します。\n\n"
                "**【解除手順】**\n"
                "一番下の解除用ドロップダウンから、解除したい設定を選択します。"
            ),
            color=discord.Color.blue()
        )
        
        log_types = {
            "message_edit": "📝 メッセージ編集",
            "message_delete": "🗑️ メッセージ削除",
            "vc_join_leave": "🎙️ VC参加・退出",
            "member_join_leave": "👥 メンバー入退",
            "economy": "💰 通貨・経済"
        }
        
        settings_str = ""
        for l_type, display_name in log_types.items():
            ch_id = settings.get(l_type)
            if ch_id:
                channel = interaction.guild.get_channel(ch_id)
                ch_mention = channel.mention if channel else f"⚠️ 不明なチャンネル (ID: `{ch_id}`)"
            else:
                ch_mention = "未設定"
            settings_str += f"• **{display_name}**: {ch_mention}\n"
            
        embed.add_field(name="現在の設定一覧", value=settings_str, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --- 自己紹介・評価設定用UI ---

async def update_evaluation_settings_config_view(interaction: discord.Interaction, bot):
    cfg = bot.get_evaluation_config(interaction.guild_id)
    view = EvaluationSettingsConfigView(bot, interaction.guild_id)
    
    embed = discord.Embed(
        title="📋 自己紹介・評価設定パネル",
        description=(
            "自己紹介チャンネルと評価用フォーラムの設定を行います。\n\n"
            "**【設定方法】**\n"
            "1. **評価用フォーラムを追加**から、評価用スレッドを作成したいフォーラムを選択して追加します（複数選択可）。\n"
            "2. **削除する評価用フォーラムを選択**から、登録を解除できます。\n"
            "3. **追加する自己紹介チャンネルを選択**から、発言検知（スレッド自動作成）の対象となるテキストチャンネルを追加します（複数選択可）。\n"
            "4. **削除する自己紹介チャンネルを選択**から、登録を解除できます。"
        ),
        color=discord.Color.blue()
    )
    
    forum_strs = []
    for fid in cfg["forum_channel_ids"]:
        ch = interaction.guild.get_channel(fid)
        if ch:
            forum_strs.append(ch.mention)
        else:
            forum_strs.append(f"⚠️ 不明なフォーラム (ID: `{fid}`)")
    forum_ch_str = ", ".join(forum_strs) if forum_strs else "登録されている評価用フォーラムはありません。"
    
    self_intro_strs = []
    for cid in cfg["self_intro_channel_ids"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            self_intro_strs.append(ch.mention)
        else:
            self_intro_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    self_intro_ch_str = ", ".join(self_intro_strs) if self_intro_strs else "登録されている自己紹介チャンネルはありません。"
    
    embed.add_field(name="現在の設定一覧", value=f"• **評価用フォーラム**: {forum_ch_str}\n• **自己紹介チャンネル**: {self_intro_ch_str}", inline=False)
    
    rank_cfg = bot.get_rank_config(interaction.guild_id)
    eval_categories = rank_cfg.get("categories", set()) or rank_cfg.get("whitelist_categories", set())
    if not eval_categories:
        fallback_cat_id = config.get_setting(bot, "EVAL_TIME_CATEGORY_ID")
        if fallback_cat_id and fallback_cat_id != 123456789012345678:
            eval_categories = {fallback_cat_id}

    if eval_categories:
        now_aware = datetime.datetime.now(config.JST)
        staying_strs = []
        guild = interaction.guild
        for member in guild.members:
            if member.bot:
                continue
            if not (member.voice and member.voice.channel):
                continue
            vc = member.voice.channel
            if not vc.category:
                continue
            if vc.category.id not in eval_categories:
                continue
            join_time = bot.vc_sessions.get(member.id)
            if join_time:
                delta_sec = (now_aware - join_time).total_seconds()
                hours = int(delta_sec // 3600)
                mins = int((delta_sec % 3600) // 60)
                if hours > 0:
                    dur_str = f"{hours}時間{mins}分"
                else:
                    dur_str = f"{mins}分"
            else:
                dur_str = "0分"
            staying_strs.append(f"• {member.mention} — {vc.mention} — **{dur_str}**")
        
        cat_names = []
        for cid in eval_categories:
            cat = guild.get_channel(cid)
            cat_names.append(f"📁 {cat.name}" if cat else f"ID: {cid}")
        cat_label = ", ".join(cat_names)
        
        if staying_strs:
            staying_value = "\n".join(staying_strs[:20])
            if len(staying_strs) > 20:
                staying_value += f"\n… 他 {len(staying_strs) - 20} 人"
        else:
            staying_value = "現在滞在しているメンバーはいません。"
        
        embed.add_field(
            name=f"🟢 評価対象カテゴリー滞在状況 ({cat_label})",
            value=staying_value,
            inline=False
        )
    
    if interaction.is_expired() or interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class AddEvaluationForumSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="評価用フォーラムを追加...",
            channel_types=[discord.ChannelType.forum],
            min_values=1,
            max_values=10,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        added_count = 0
        for channel in self.values:
            if channel.id not in cfg["forum_channel_ids"]:
                cfg["forum_channel_ids"].add(channel.id)
                added_count += 1
                
        if added_count > 0:
            await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        else:
            return await interaction.response.send_message("❌ 選択されたフォーラムは全て既に登録されています。", ephemeral=True)
            
        await update_evaluation_settings_config_view(interaction, bot)

class RemoveEvaluationForumSelect(discord.ui.Select):
    def __init__(self, bot, guild_id):
        cfg = bot.get_evaluation_config(guild_id)
        options = []
        guild = bot.get_guild(guild_id)
        for fid in cfg["forum_channel_ids"]:
            ch = guild.get_channel(fid) if guild else None
            name = ch.name if ch else f"不明なフォーラム ({fid})"
            options.append(discord.SelectOption(
                label=name,
                value=str(fid),
                description=f"ID: {fid}"
            ))
        super().__init__(
            placeholder="削除する評価用フォーラムを選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel_id = int(self.values[0])
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        if channel_id not in cfg["forum_channel_ids"]:
            return await interaction.response.send_message(f"❌ そのチャンネルは登録されていません。", ephemeral=True)
            
        cfg["forum_channel_ids"].discard(channel_id)
        await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        
        await update_evaluation_settings_config_view(interaction, bot)

class AddSelfIntroChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="追加する自己紹介チャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=10,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        added_count = 0
        for channel in self.values:
            if channel.id not in cfg["self_intro_channel_ids"]:
                cfg["self_intro_channel_ids"].add(channel.id)
                added_count += 1
                
        if added_count > 0:
            await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        else:
            return await interaction.response.send_message("❌ 選択されたチャンネルは全て既に登録されています。", ephemeral=True)
            
        await update_evaluation_settings_config_view(interaction, bot)

class RemoveSelfIntroChannelSelect(discord.ui.Select):
    def __init__(self, bot, guild_id):
        cfg = bot.get_evaluation_config(guild_id)
        options = []
        guild = bot.get_guild(guild_id)
        for cid in cfg["self_intro_channel_ids"]:
            ch = guild.get_channel(cid) if guild else None
            name = ch.name if ch else f"不明なチャンネル ({cid})"
            options.append(discord.SelectOption(
                label=name,
                value=str(cid),
                description=f"ID: {cid}"
            ))
        super().__init__(
            placeholder="削除する自己紹介チャンネルを選択...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        channel_id = int(self.values[0])
        cfg = bot.get_evaluation_config(interaction.guild_id)
        
        if channel_id not in cfg["self_intro_channel_ids"]:
            return await interaction.response.send_message(f"❌ そのチャンネルは登録されていません。", ephemeral=True)
            
        cfg["self_intro_channel_ids"].discard(channel_id)
        await database.set_evaluation_settings(interaction.guild_id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        
        await update_evaluation_settings_config_view(interaction, bot)

class EvaluationSettingsConfigView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=180)
        self.add_item(AddEvaluationForumSelect())
        cfg = bot.get_evaluation_config(guild_id)
        if cfg["forum_channel_ids"]:
            self.add_item(RemoveEvaluationForumSelect(bot, guild_id))
        self.add_item(AddSelfIntroChannelSelect())
        if cfg["self_intro_channel_ids"]:
            self.add_item(RemoveSelfIntroChannelSelect(bot, guild_id))

class ManageEvaluationSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="自己紹介・評価を設定",
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            custom_id="persistent_admin_manage_evaluation_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        bot = interaction.client
        await update_evaluation_settings_config_view(interaction, bot)

# --- ランク対象設定 (TC/VC XP) ---

async def update_rank_settings_config_view(interaction: discord.Interaction, bot):
    cfg = bot.get_rank_config(interaction.guild_id)
    view = RankSettingsConfigView(bot, interaction.guild_id)
    
    embed = discord.Embed(
        title="📊 ランク対象設定 (TC/VC XP)",
        description=(
            "テキスト（TC）およびボイス（VC）の経験値が貯まるチャンネル・カテゴリーを設定します。\n"
            "チャンネル単位でもカテゴリー単位でもまとめて指定できます。\n\n"
            "**【判定ルール】**\n"
            "1. **有効の指定がない場合**: 無効に指定したチャンネル・カテゴリー**以外**すべてが対象になります。\n"
            "2. **無効の指定がない場合**: 有効に指定したチャンネル・カテゴリー**のみ**が対象になります。\n"
            "3. **両方指定されている場合**: 有効リストに含まれ、かつ無効リストに含まれないチャンネルが対象になります。\n"
            "4. **どちらも指定がない場合**: すべてのチャンネルが対象になります。\n\n"
            "**【設定手順】**\n"
            "- チャンネル単位: 上2つのドロップダウンから有効/無効チャンネルを選択します（各最大25個）。\n"
            "- カテゴリー単位: 下2つのドロップダウンからカテゴリーを選択するとそのカテゴリー内全チャンネルに適用されます。\n"
            "- 各「クリア」ボタンで設定を初期化できます。"
        ),
        color=discord.Color.blue()
    )
    
    whitelist_strs = []
    for cid in cfg.get("whitelist", set()):
        ch = interaction.guild.get_channel(cid)
        if ch:
            whitelist_strs.append(ch.mention)
        else:
            whitelist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    whitelist_ch_str = ", ".join(whitelist_strs) if whitelist_strs else "未設定 (無効チャンネル以外が対象)"

    blacklist_strs = []
    for cid in cfg.get("blacklist", set()):
        ch = interaction.guild.get_channel(cid)
        if ch:
            blacklist_strs.append(ch.mention)
        else:
            blacklist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    blacklist_ch_str = ", ".join(blacklist_strs) if blacklist_strs else "未設定 (制限なし)"

    wl_cat_strs = []
    for cid in cfg.get("whitelist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        if cat:
            wl_cat_strs.append(f"📁 {cat.name}")
        else:
            wl_cat_strs.append(f"⚠️ 不明なカテゴリー (ID: `{cid}`)") 
    wl_cat_str = ", ".join(wl_cat_strs) if wl_cat_strs else "未設定"

    bl_cat_strs = []
    for cid in cfg.get("blacklist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        if cat:
            bl_cat_strs.append(f"📁 {cat.name}")
        else:
            bl_cat_strs.append(f"⚠️ 不明なカテゴリー (ID: `{cid}`)")
    bl_cat_str = ", ".join(bl_cat_strs) if bl_cat_strs else "未設定"

    embed.add_field(
        name="現在の設定",
        value=(
            f"• **対応チャンネル (有効)**: {whitelist_ch_str}\n"
            f"• **非対応チャンネル (無効)**: {blacklist_ch_str}\n"
            f"• **対応カテゴリー (有効)**: {wl_cat_str}\n"
            f"• **非対応カテゴリー (無効)**: {bl_cat_str}"
        ),
        inline=False
    )
    
    if interaction.response.is_done():
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class WhitelistChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="対応チャンネル (有効) を選択/変更...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.news,
                discord.ChannelType.forum,
                discord.ChannelType.stage_voice
            ],
            min_values=1,
            max_values=25,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist"] = {ch.id for ch in self.values}
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class BlacklistChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="非対応チャンネル (無効) を選択/変更...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.news,
                discord.ChannelType.forum,
                discord.ChannelType.stage_voice
            ],
            min_values=1,
            max_values=25,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist"] = {ch.id for ch in self.values}
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class WhitelistCategorySelect(discord.ui.ChannelSelect):
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="対応カテゴリー (有効) を選択/変更...",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=25,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist_categories"] = {ch.id for ch in self.values}
        cfg["categories"] = cfg["whitelist_categories"]
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg["whitelist_categories"]), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class BlacklistCategorySelect(discord.ui.ChannelSelect):
    def __init__(self, bot, guild_id):
        super().__init__(
            placeholder="非対応カテゴリー (無効) を選択/変更...",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=25,
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist_categories"] = {ch.id for ch in self.values}
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg["blacklist_categories"])
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearWhitelistButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="対応CHをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearBlacklistButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="非対応CHをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearWlCategoriesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="対応CATをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["whitelist_categories"] = set()
        cfg["categories"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg["whitelist_categories"]), list(cfg.get("blacklist_categories", []))
        )
        await update_rank_settings_config_view(interaction, bot)

class ClearBlCategoriesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="非対応CATをクリア",
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        cfg = bot.get_rank_config(interaction.guild_id)
        cfg["blacklist_categories"] = set()
        await database.set_rank_settings(
            interaction.guild_id,
            list(cfg["whitelist"]), list(cfg["blacklist"]),
            list(cfg.get("whitelist_categories", [])), list(cfg["blacklist_categories"])
        )
        await update_rank_settings_config_view(interaction, bot)

class BackToAdminPanelButton(discord.ui.Button):
    def __init__(self, row=4):
        super().__init__(
            label="戻る",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client
        await update_main_admin_panel(interaction, bot)

class ManageRankSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="ランク対象を設定",
            style=discord.ButtonStyle.secondary,
            emoji="📊",
            custom_id="persistent_admin_manage_rank_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)
        bot = interaction.client
        await update_rank_settings_config_view(interaction, bot)

class RankSettingsConfigView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=180)
        self.add_item(WhitelistChannelSelect(bot, guild_id))
        self.add_item(BlacklistChannelSelect(bot, guild_id))
        self.add_item(WhitelistCategorySelect(bot, guild_id))
        self.add_item(BlacklistCategorySelect(bot, guild_id))
        self.add_item(ClearWhitelistButton())
        self.add_item(ClearBlacklistButton())
        self.add_item(ClearWlCategoriesButton())
        self.add_item(ClearBlCategoriesButton())
        self.add_item(BackToAdminPanelButton(row=4))

# --- パネル設置メインパネル ---

async def update_main_admin_panel(interaction: discord.Interaction, bot):
    embed = discord.Embed(
        title="⚙️ サーバー設定・パネル設置",
        description="下のメニューから設置したいパネルを選択してください。現在の設定情報は以下の通りです。",
        color=0x2f3136
    )

    embed.add_field(
        name="💰 経済設定",
        value=f"通貨名: **{config.CURRENCY_NAME}**\n初期所持金: **{config.INITIAL_COINS} {config.CURRENCY_NAME}**",
        inline=False
    )

    main_sub_roles_str = format_setting_status(interaction.guild, 'MAIN_SUB_MEMBER_ROLE_IDS')
    if "❌" in main_sub_roles_str: main_sub_roles_str = "名前一致: " + ", ".join(config.MAIN_SUB_MEMBER_ROLE_NAMES)
    
    admin_str = format_setting_status(interaction.guild, 'ADMIN_ROLE_IDS')
    if "❌" in admin_str: admin_str = "名前一致: " + ", ".join(config.ADMIN_ROLE_NAMES)
    evaluator_str = format_setting_status(interaction.guild, 'EVALUATOR_ROLE_IDS')
    if "❌" in evaluator_str: evaluator_str = "名前一致: " + ", ".join(config.EVALUATOR_ROLE_NAMES)
    new_member_str = format_setting_status(interaction.guild, 'NEW_MEMBER_ROLE_ID')
    if "❌" in new_member_str: new_member_str = "名前一致: " + config.NEW_MEMBER_ROLE_NAME
    pending_member_str = format_setting_status(interaction.guild, 'PENDING_MEMBER_ROLE_ID')
    if "❌" in pending_member_str: pending_member_str = "名前一致: " + config.PENDING_MEMBER_ROLE_NAME
    interviewer_str = format_setting_status(interaction.guild, 'INTERVIEWER_ROLE_IDS')
    if "❌" in interviewer_str: interviewer_str = "名前一致: " + ", ".join(config.INTERVIEWER_ROLE_NAMES)
    emblem_manager_str = format_setting_status(interaction.guild, 'EMBLEM_MANAGER_ROLE_ID')
    if "❌" in emblem_manager_str: emblem_manager_str = "名前一致: " + config.EMBLEM_MANAGER_ROLE_NAME
    emblem_master_str = format_setting_status(interaction.guild, 'EMBLEM_MASTER_ROLE_ID')
    if "❌" in emblem_master_str: emblem_master_str = "名前一致: " + config.EMBLEM_MASTER_ROLE_NAME
    confession_priest_str = format_setting_status(interaction.guild, 'CONFESSION_PRIEST_ROLE_ID')
    if "❌" in confession_priest_str: confession_priest_str = "名前一致: " + config.CONFESSION_PRIEST_ROLE_ID
    priest_str = format_setting_status(interaction.guild, 'PRIEST_ROLE_ID')
    if "❌" in priest_str: priest_str = "名前一致: " + config.PRIEST_ROLE_NAME

    embed.add_field(
        name="🏨 部屋・宿設定",
        value=(
            f"🛖 **一般宿** (対象: {main_sub_roles_str}):\n"
            f"  ┗ 12時間: {config.ROOM_SETTINGS['宿'][12]['price']:,} {config.CURRENCY_NAME}\n"
            f"  ┗ 24時間: {config.ROOM_SETTINGS['宿'][24]['price']:,} {config.CURRENCY_NAME}\n"
            f"🏰 **高級宿**:\n"
            f"  ┗ 12時間: {config.ROOM_SETTINGS['高級宿'][12]['price']:,} {config.CURRENCY_NAME}\n"
            f"  ┗ 24時間: {config.ROOM_SETTINGS['高級宿'][24]['price']:,} {config.CURRENCY_NAME}\n"
            f"✨ **カスタムVC**:\n"
            f"  ┗ 24時間: {config.ROOM_SETTINGS['カスタムVC'][24]['price']:,} {config.CURRENCY_NAME}"
        ),
        inline=False
    )

    embed.add_field(
        name="👥 ロール設定",
        value=(
            f"管理者ロール: {admin_str}\n"
            f"評価員ロール: {evaluator_str}\n"
            f"入界後ロール: {new_member_str}\n"
            f"待機者ロール: {pending_member_str}\n"
            f"面接官ロール: {interviewer_str}"
        ),
        inline=False
    )

    embed.add_field(
        name="🎨 制作・告解設定",
        value=(
            f"紋章師: {emblem_manager_str}, {emblem_master_str}\n"
            f"司祭: {confession_priest_str}, {priest_str}"
        ),
        inline=False
    )

    triggers_str = ""
    for tid in bot.auto_vc_triggers:
        ch = bot.get_channel(tid)
        if ch:
            triggers_str += f"• {ch.mention} (ID: `{tid}`)\n"
        else:
            triggers_str += f"• ⚠️ 不明なチャンネル (ID: `{tid}`)\n"
    if not triggers_str:
        triggers_str = "登録されているトリガーチャンネルはありません。"
    embed.add_field(
        name="🎙️ VC作成トリガー設定",
        value=triggers_str,
        inline=False
    )

    rewards = await database.get_level_role_rewards()
    rewards_str = ""
    for r in rewards:
        ltype = "💬 TC" if r["level_type"] == "tc" else "🎙️ VC"
        role = interaction.guild.get_role(r["role_id"])
        role_name = role.mention if role else f"不明なロール (ID: {r['role_id']})"
        rewards_str += f"• **{ltype}** Lv.{r['level']} ➔ {role_name}\n"
    if not rewards_str:
        rewards_str = "登録されているレベルロール報酬はありません。"
    embed.add_field(
        name="🎁 レベルロール設定",
        value=rewards_str,
        inline=False
    )

    cfg = bot.get_evaluation_config(interaction.guild_id)
    forum_strs = []
    for fid in cfg["forum_channel_ids"]:
        ch = interaction.guild.get_channel(fid)
        if ch:
            forum_strs.append(ch.mention)
        else:
            forum_strs.append(f"⚠️ 不明なフォーラム (ID: `{fid}`)")
    forum_ch_str = ", ".join(forum_strs) if forum_strs else "未設定"

    self_intro_strs = []
    for cid in cfg["self_intro_channel_ids"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            self_intro_strs.append(ch.mention)
        else:
            self_intro_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    self_intro_ch_str = ", ".join(self_intro_strs) if self_intro_strs else "未設定"

    embed.add_field(
        name="📋 自己紹介・評価設定",
        value=(
            f"評価用フォーラム: {forum_ch_str}\n"
            f"自己紹介チャンネル: {self_intro_ch_str}"
        ),
        inline=False
    )

    rank_cfg = bot.get_rank_config(interaction.guild_id)
    whitelist_strs = []
    for cid in rank_cfg["whitelist"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            whitelist_strs.append(ch.mention)
        else:
            whitelist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    whitelist_ch_str = ", ".join(whitelist_strs) if whitelist_strs else "未設定 (無効チャンネル以外が対象)"

    blacklist_strs = []
    for cid in rank_cfg["blacklist"]:
        ch = interaction.guild.get_channel(cid)
        if ch:
            blacklist_strs.append(ch.mention)
        else:
            blacklist_strs.append(f"⚠️ 不明なチャンネル (ID: `{cid}`)")
    blacklist_ch_str = ", ".join(blacklist_strs) if blacklist_strs else "未設定 (制限なし)"

    wl_cat_strs = []
    for cid in rank_cfg.get("whitelist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        wl_cat_strs.append(f"📁 {cat.name}" if cat else f"⚠️ 不明 (ID: `{cid}`)")
    wl_cat_str = ", ".join(wl_cat_strs) if wl_cat_strs else "未設定"

    bl_cat_strs = []
    for cid in rank_cfg.get("blacklist_categories", set()):
        cat = interaction.guild.get_channel(cid)
        bl_cat_strs.append(f"📁 {cat.name}" if cat else f"⚠️ 不明 (ID: `{cid}`)")
    bl_cat_str = ", ".join(bl_cat_strs) if bl_cat_strs else "未設定"

    embed.add_field(
        name="📊 ランク設定 (TC/VC XP対象)",
        value=(
            f"• **対応チャンネル (有効)**: {whitelist_ch_str}\n"
            f"• **非対応チャンネル (無効)**: {blacklist_ch_str}\n"
            f"• **対応カテゴリー (有効)**: {wl_cat_str}\n"
            f"• **非対応カテゴリー (無効)**: {bl_cat_str}"
        ),
        inline=False
    )

    view = PanelSetupView()
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)

class PanelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="チンチロリン", description="チンチロリンゲームのパネルを設置します", emoji="🎲", value="chinchiro"),
            discord.SelectOption(label="コイントス", description="コイントスゲームのパネルを設置します", emoji="🪙", value="coinflip"),
            discord.SelectOption(label="スロット", description="スロットゲームのパネルを設置します", emoji="🎰", value="slot"),
            discord.SelectOption(label="ブラックジャック", description="ブラックジャックゲームのパネルを設置します", emoji="🃏", value="blackjack"),
            discord.SelectOption(label="ルーレット", description="ルーレットゲームのパネルを設置します", emoji="🎡", value="roulette"),
            discord.SelectOption(label="一般宿 (本・準メンバー用)", description="本・準メンバー用の無料宿パネルを設置します", emoji="🛖", value="inn_main"),
            discord.SelectOption(label="一般宿 (仮メンバー用)", description="仮メンバー用の有料宿パネルを設置します", emoji="🛖", value="inn_temp"),
            discord.SelectOption(label="高級宿", description="高級宿の購入パネルを設置します", emoji="🏰", value="inn_luxury"),
            discord.SelectOption(label="カスタムVC", description="カスタムVCの作成パネルを設置します", emoji="✨", value="custom_vc"),
            discord.SelectOption(label="スタンプ依頼", description="スタンプ制作依頼のパネルを設置します", emoji="🎨", value="stamp"),
            discord.SelectOption(label="告解・相談室", description="告解・相談依頼のパネルを設置します", emoji="⛪", value="confession"),
            discord.SelectOption(label="VC管理", description="VC名・人数制限変更のパネルを設置します", emoji="⚙️", value="vc_manage"),
            discord.SelectOption(label="入界手続き", description="新規メンバーの入界手続きパネルを設置します", emoji="📝", value="interview"),
            discord.SelectOption(label="お問い合わせ", description="お問い合わせ作成パネルを設置します", emoji="✉️", value="inquiry"),
            discord.SelectOption(label="カスタムチケット", description="任意のタイトル・説明文・担当ロールを指定したチケットパネルを設置します", emoji="🎫", value="custom_ticket"),
            discord.SelectOption(label="任意ロール", description="任意のロールをリアクションで付与するパネルを設置します", emoji="🎭", value="custom_role_panel")
        ]
        super().__init__(placeholder="設置するパネルを選択してください...", min_values=1, max_values=1, options=options, custom_id="admin_panel_setup_select")

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        channel = interaction.channel
        bot = interaction.client
        
        if not config.has_admin_role(bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            if val == "interview":
                user_role_ids = [r.id for r in interaction.user.roles]
                interviewer_ids = config.get_setting(bot, "INTERVIEWER_ROLE_IDS") or []
                is_interviewer = any(rid in interviewer_ids for rid in user_role_ids)
                if not is_interviewer:
                    user_role_names = [r.name for r in interaction.user.roles]
                    is_interviewer = any(name in config.INTERVIEWER_ROLE_NAMES for name in user_role_names)
                if not is_interviewer:
                    return await interaction.response.send_message("この操作を実行する権限がありません。", ephemeral=True)
            else:
                return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        if val == "chinchiro":
            embed = discord.Embed(title="🎲 チンチロリン", description="カジノへようこそ！", color=discord.Color.gold())
            await channel.send(embed=embed, view=ChinchiroView())
            await interaction.response.send_message("✅ チンチロリンパネルを設置しました。", ephemeral=True)
        elif val == "coinflip":
            embed = discord.Embed(title="🪙 コイントス", description="カジノへようこそ！", color=discord.Color.gold())
            await channel.send(embed=embed, view=CoinflipView())
            await interaction.response.send_message("✅ コイントスパネルを設置しました。", ephemeral=True)
        elif val == "slot":
            embed = discord.Embed(title="🎰 スロット", description="カジノへようこそ！", color=discord.Color.gold())
            await channel.send(embed=embed, view=SlotView())
            await interaction.response.send_message("✅ スロットパネルを設置しました。", ephemeral=True)
        elif val == "blackjack":
            embed = discord.Embed(title="🃏 ブラックジャック", description="カジノへようこそ！", color=discord.Color.gold())
            await channel.send(embed=embed, view=BlackjackView())
            await interaction.response.send_message("✅ ブラックジャックパネルを設置しました。", ephemeral=True)
        elif val == "roulette":
            embed = discord.Embed(title="🎡 ルーレット", description="カジノへようこそ！", color=discord.Color.gold())
            await channel.send(embed=embed, view=RouletteView())
            await interaction.response.send_message("✅ ルーレットパネルを設置しました。", ephemeral=True)
        elif val == "inn_main":
            main_sub_roles_str = format_setting_status(interaction.guild, 'MAIN_SUB_MEMBER_ROLE_IDS')
            if "❌" in main_sub_roles_str: 
                main_sub_roles_str = f"「{'」や「'.join(config.MAIN_SUB_MEMBER_ROLE_NAMES)}」"
            
            embed = discord.Embed(
                title="🏠 一般宿 (本・準メンバー用)", 
                description=f"部屋を無料で借りる（時間無制限）\n※対象ロール {main_sub_roles_str} をお持ちの方専用", 
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=MainInnPanelView())
            await interaction.response.send_message("✅ 宿屋(本・準メンバー用)パネルを設置しました。", ephemeral=True)
        elif val == "inn_temp":
            embed = discord.Embed(
                title="🏠 一般宿 (仮メンバー用)", 
                description="部屋を有料で借りる", 
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=TempInnPanelView())
            await interaction.response.send_message("✅ 宿屋(仮メンバー用)パネルを設置しました。", ephemeral=True)
        elif val == "inn_luxury":
            embed = discord.Embed(
                title="🏰 高級宿", 
                description="高級宿を有料で借りる", 
                color=discord.Color.purple()
            )
            await channel.send(embed=embed, view=LuxuryInnPanelView())
            await interaction.response.send_message("✅ 高級宿パネルを設置しました。", ephemeral=True)
        elif val == "custom_vc":
            embed = discord.Embed(title="✨ カスタムVC", description="自分だけの部屋を作成", color=discord.Color.purple())
            await channel.send(embed=embed, view=CustomRoomView())
            await interaction.response.send_message("✅ カスタムVCパネルを設置しました。", ephemeral=True)
        elif val == "stamp":
            embed = discord.Embed(
                title="スタンプ制作 依頼所",
                description=(
                    "こちらから製作者の方々へスタンプの制作を依頼できます。\n\n"
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
        elif val == "inquiry":
            embed = discord.Embed(
                title="✉️ お問い合わせ設定",
                description="お問い合わせの際に通知（メンション）するロールを選択してください。",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, view=InquirySetupView(), ephemeral=True)
        elif val == "custom_ticket":
            await interaction.response.send_modal(CustomTicketSetupModal())
        elif val == "custom_role_panel":
            await interaction.response.send_modal(CustomRolePanelSetupModal())

class PanelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PanelSelect())
        self.add_item(ManageVCTriggersButton())
        self.add_item(ManageLevelRolesButton())
        self.add_item(ManageRoomPricesButton())
        self.add_item(ManageLogSettingsButton())
        self.add_item(ManageEvaluationSettingsButton())
        self.add_item(ManageRankSettingsButton())

# --- Bot初期設定インタラクティブUI ---

class BotSetupMainSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👥 管理者ロール", value="ADMIN_ROLE_IDS", description="管理者のロールを設定します"),
            discord.SelectOption(label="👥 見習い・初級評価員", value="EVALUATOR_TIER1_ROLE_IDS", description="見習い・初級ランクの評価員ロール"),
            discord.SelectOption(label="👥 中級・上級評価員", value="EVALUATOR_TIER2_ROLE_IDS", description="中級・上級ランクの評価員ロール"),
            discord.SelectOption(label="👥 特級・統括評価員", value="EVALUATOR_TIER3_ROLE_IDS", description="特級・統括ランクの評価員ロール"),
            discord.SelectOption(label="👥 新規メンバーロール", value="NEW_MEMBER_ROLE_ID", description="入界後の一般メンバーロール"),
            discord.SelectOption(label="👥 入界待機者ロール", value="PENDING_MEMBER_ROLE_ID", description="面接待ちメンバーのロール"),
            discord.SelectOption(label="👥 面接官ロール", value="INTERVIEWER_ROLE_IDS", description="面接を行える権限ロール"),
            discord.SelectOption(label="👥 本・準メンバーロール", value="MAIN_SUB_MEMBER_ROLE_IDS", description="一般宿を無料・無制限で利用できる本・準メンバーのロール"),
            discord.SelectOption(label="👥 スタンプ統括ロール", value="EMBLEM_MANAGER_ROLE_ID", description="スタンプ制作を管理するロール"),
            discord.SelectOption(label="👥 スタンプ制作ロール", value="EMBLEM_MASTER_ROLE_ID", description="スタンプを制作するロール"),
            discord.SelectOption(label="👥 告解司祭ロール", value="CONFESSION_PRIEST_ROLE_ID", description="告解を対応する司祭ロール"),
            discord.SelectOption(label="👥 司祭ロール", value="PRIEST_ROLE_ID", description="相談を対応する司祭ロール"),
            discord.SelectOption(label="👥 イベント管理ロール", value="EVENT_MANAGER_ROLE_IDS", description="イベント登録・編集・削除ができるロール"),
            discord.SelectOption(label="📺 レベルアップチャンネル", value="LEVEL_UP_CHANNEL_ID", description="レベルアップ通知を送る先"),
            discord.SelectOption(label="📺 VC作成トリガー", value="CREATE_VC_CHANNEL_ID", description="入室すると自動VCを作る部屋"),
            discord.SelectOption(label="📺 評価時間対象カテゴリー", value="EVAL_TIME_CATEGORY_ID", description="評価時間を計測するカテゴリー"),
            discord.SelectOption(label="📺 自己紹介チャンネル", value="SELF_INTRO_CHANNEL_IDS", description="自己紹介を行う部屋（複数可）"),
            discord.SelectOption(label="📺 見習い・初級フォーラム", value="EVALUATION_FORUM_TIER1_IDS", description="見習い・初級用の評価フォーラム"),
            discord.SelectOption(label="📺 中級・上級フォーラム", value="EVALUATION_FORUM_TIER2_IDS", description="中級・上級用の評価フォーラム"),
            discord.SelectOption(label="📺 特級・統括フォーラム", value="EVALUATION_FORUM_TIER3_IDS", description="特級・統括用の評価フォーラム")
        ]
        super().__init__(placeholder="設定する項目を選択してください...", options=options, custom_id="admin_bot_setup_main_select")

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        view = BotSetupConfigureView(interaction.user, key)
        embed = view.build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)

class BotSetupMainView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=300)
        self.user = user
        self.add_item(BotSetupMainSelect())

    def build_embed(self, guild):
        embed = discord.Embed(
            title="⚙️ Bot初期設定・管理パネル",
            description="Discord内の各種設定を調整します。選択メニューから項目を選んでください。",
            color=0x2f3136
        )
        roles_text = (
            f"• 管理者: {format_setting_status(guild, 'ADMIN_ROLE_IDS')}\n"
            f"• 見習い・初級評価員: {format_setting_status(guild, 'EVALUATOR_TIER1_ROLE_IDS')}\n"
            f"• 中級・上級評価員: {format_setting_status(guild, 'EVALUATOR_TIER2_ROLE_IDS')}\n"
            f"• 特級・統括評価員: {format_setting_status(guild, 'EVALUATOR_TIER3_ROLE_IDS')}\n"
            f"• 新規メンバー: {format_setting_status(guild, 'NEW_MEMBER_ROLE_ID')}\n"
            f"• 入界待機者: {format_setting_status(guild, 'PENDING_MEMBER_ROLE_ID')}\n"
            f"• 面接官: {format_setting_status(guild, 'INTERVIEWER_ROLE_IDS')}\n"
            f"• 無料宿対象: {format_setting_status(guild, 'MAIN_SUB_MEMBER_ROLE_IDS')}\n"
            f"• スタンプ統括: {format_setting_status(guild, 'EMBLEM_MANAGER_ROLE_ID')}\n"
            f"• スタンプ制作: {format_setting_status(guild, 'EMBLEM_MASTER_ROLE_ID')}\n"
            f"• 告解司祭: {format_setting_status(guild, 'CONFESSION_PRIEST_ROLE_ID')}\n"
            f"• 司祭: {format_setting_status(guild, 'PRIEST_ROLE_ID')}\n"
            f"• イベント管理: {format_setting_status(guild, 'EVENT_MANAGER_ROLE_IDS')}"
        )
        embed.add_field(name="👥 ロール設定", value=roles_text, inline=False)
        
        channels_text = (
            f"• レベルアップ通知: {format_setting_status(guild, 'LEVEL_UP_CHANNEL_ID')}\n"
            f"• VC作成トリガー: {format_setting_status(guild, 'CREATE_VC_CHANNEL_ID')}\n"
            f"• 評価時間対象カテゴリ: {format_setting_status(guild, 'EVAL_TIME_CATEGORY_ID')}\n"
            f"• 自己紹介部屋: {format_setting_status(guild, 'SELF_INTRO_CHANNEL_IDS')}\n"
            f"• 見習い・初級フォーラム: {format_setting_status(guild, 'EVALUATION_FORUM_TIER1_IDS')}\n"
            f"• 中級・上級フォーラム: {format_setting_status(guild, 'EVALUATION_FORUM_TIER2_IDS')}\n"
            f"• 特級・統括フォーラム: {format_setting_status(guild, 'EVALUATION_FORUM_TIER3_IDS')}"
        )
        embed.add_field(name="📺 チャンネル・カテゴリー設定", value=channels_text, inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.user:
            await interaction.response.send_message("このパネルは操作できません。", ephemeral=True)
            return False
        return True

class BotSetupRoleSelect(discord.ui.RoleSelect):
    def __init__(self, key, is_multi):
        super().__init__(
            placeholder="設定するロールを選択してください...",
            min_values=1,
            max_values=10 if is_multi else 1,
            custom_id="admin_bot_setup_role_select"
        )
        self.key = key
        self.is_multi = is_multi

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        guild = interaction.guild
        if self.is_multi:
            value = [role.id for role in self.values]
        else:
            value = self.values[0].id
            
        await database.save_setting(self.key, value)
        interaction.client.bot_settings[self.key] = value

        embed = discord.Embed(
            title="✅ 設定完了",
            description=f"`{self.key}` を正常に設定しました！\n\n現在の設定値: {format_setting_status(guild, self.key)}",
            color=discord.Color.green()
        )
        back_view = BotSetupConfigureView(view.user, self.key)
        await interaction.response.edit_message(embed=embed, view=back_view)

class BotSetupChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, key, is_multi, channel_types):
        super().__init__(
            placeholder="設定するチャンネルを選択してください...",
            min_values=1,
            max_values=10 if is_multi else 1,
            channel_types=channel_types,
            custom_id="admin_bot_setup_channel_select"
        )
        self.key = key
        self.is_multi = is_multi

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        guild = interaction.guild
        if self.is_multi:
            value = [ch.id for ch in self.values]
        else:
            value = self.values[0].id
            
        await database.save_setting(self.key, value)
        interaction.client.bot_settings[self.key] = value
        
        if self.key == "CREATE_VC_CHANNEL_ID":
            await database.add_auto_vc_trigger(value)
            interaction.client.auto_vc_triggers.add(value)

        embed = discord.Embed(
            title="✅ 設定完了",
            description=f"`{self.key}` を正常に設定しました！\n\n現在の設定値: {format_setting_status(guild, self.key)}",
            color=discord.Color.green()
        )
        back_view = BotSetupConfigureView(view.user, self.key)
        await interaction.response.edit_message(embed=embed, view=back_view)

class BotSetupConfigureView(discord.ui.View):
    def __init__(self, user, key):
        super().__init__(timeout=300)
        self.user = user
        self.key = key
        
        is_multi = "IDS" in key
        if "ROLE" in key:
            self.add_item(BotSetupRoleSelect(key, is_multi))
        elif "CHANNEL" in key or "FORUM" in key:
            types = [discord.ChannelType.text]
            if "FORUM" in key:
                types = [discord.ChannelType.forum]
            elif "VC" in key:
                types = [discord.ChannelType.voice]
            self.add_item(BotSetupChannelSelect(key, is_multi, types))
        elif "CATEGORY" in key:
            types = [discord.ChannelType.category]
            self.add_item(BotSetupChannelSelect(key, is_multi, types))

    def build_embed(self, guild):
        embed = discord.Embed(
            title=f"🛠️ 設定の変更: {self.key}",
            description=(
                f"**現在の設定値:** {format_setting_status(guild, self.key)}\n\n"
                "下のドロップダウンメニューから、この項目に設定したいロールやチャンネルを選択してください。"
            ),
            color=0x3498db
        )
        return embed

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = BotSetupMainView(self.user)
        embed = view.build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.user:
            await interaction.response.send_message("このパネルは操作できません。", ephemeral=True)
            return False
        return True

class StickyTemplateModal(discord.ui.Modal, title='常設テンプレートの作成'):
    t_title = discord.ui.TextInput(
        label='題名',
        style=discord.TextStyle.short,
        placeholder='Stickied Message:',
        required=True,
        max_length=200
    )
    t_content = discord.ui.TextInput(
        label='テンプレ内容',
        style=discord.TextStyle.paragraph,
        placeholder='コピーさせたい内容を入力してください',
        required=True,
        max_length=4000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = interaction.channel_id
        title = self.t_title.value
        content = self.t_content.value
        
        await database.set_sticky_template(channel_id, title, content)
        
        text_content = content
        new_msg = await interaction.channel.send(content=text_content)
        
        await database.update_sticky_last_message(channel_id, new_msg.id, None)
        
        await interaction.followup.send("✅ このチャンネルに常設テンプレートを設定しました。", ephemeral=True)
