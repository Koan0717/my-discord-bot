import discord
from discord.ext import commands
import asyncio
import database
import config

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
            
        emoji_str = str(payload.emoji)
        role_id = await database.get_reaction_role(payload.message_id, emoji_str)
        if not role_id:
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        member = guild.get_member(payload.user_id)
        if not member:
            return
            
        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
            
        emoji_str = str(payload.emoji)
        role_id = await database.get_reaction_role(payload.message_id, emoji_str)
        if not role_id:
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        member = guild.get_member(payload.user_id)
        if not member:
            return
            
        role = guild.get_role(role_id)
        if role:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))

class CustomRolePanelSetupModal(discord.ui.Modal, title="任意ロールパネル設置"):
    panel_title = discord.ui.TextInput(label="パネルのタイトル", default="ロール付与パネル")
    panel_desc = discord.ui.TextInput(
        label="説明文 (例: 🎮:ゲーム)", 
        style=discord.TextStyle.paragraph, 
        default="以下のリアクションを押してロールを取得してください。"
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=self.panel_title.value, description=self.panel_desc.value, color=discord.Color.gold())
        msg = await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            "パネルを設置しました！続けて以下のメニューから、付与するロールと絵文字を紐付けてください。",
            view=ReactionRoleAdminView(msg),
            ephemeral=True
        )

class ReactionRoleAdminView(discord.ui.View):
    def __init__(self, target_message: discord.Message):
        super().__init__(timeout=None)
        self.target_message = target_message

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="付与するロールを選択してください...")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        selected_role = select.values[0]
        await interaction.response.send_message(
            f"🎯 ロール {selected_role.mention} を選択しました。\n\n"
            f"**対象のパネル（上のメッセージ）に、Discord標準の絵文字ピッカーを使って直接リアクションを付けてください！**\n"
            f"（※スタンプ一覧からの検索機能がそのまま使えます。60秒以内にリアクションをお願いします）", 
            ephemeral=True
        )
        
        def check(payload: discord.RawReactionActionEvent):
            return payload.message_id == self.target_message.id and payload.user_id == interaction.user.id

        try:
            payload = await interaction.client.wait_for('raw_reaction_add', timeout=60.0, check=check)
        except asyncio.TimeoutError:
            try:
                await interaction.followup.send("⏳ タイムアウトしました。もう一度メニューからロールを選び直してください。", ephemeral=True)
            except:
                pass
            return
            
        emoji_str = str(payload.emoji)
        
        try:
            await self.target_message.remove_reaction(payload.emoji, interaction.user)
            await self.target_message.add_reaction(payload.emoji)
        except Exception:
            pass

        await database.add_reaction_role(self.target_message.id, emoji_str, selected_role.id)
        await interaction.followup.send(f"✅ 追加完了！\n絵文字 {emoji_str} にロール {selected_role.mention} を紐付けました！\n続けて別のロールを設定する場合は、上のメニューから再度選択してください。", ephemeral=True)
