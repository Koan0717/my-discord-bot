import discord
from discord.ext import commands
from discord import app_commands
import database
import config
import re

class InterviewNicknameModal(discord.ui.Modal, title='入界手続き：名前の設定'):
    name_input = discord.ui.TextInput(label='サーバーでの名前（ニックネーム）', placeholder='例: ヤマダ太郎', max_length=32, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_role = config.get_role_by_setting(interaction.client, interaction.guild, "NEW_MEMBER_ROLE_ID", config.NEW_MEMBER_ROLE_NAME)
        pending_role = config.get_role_by_setting(interaction.client, interaction.guild, "PENDING_MEMBER_ROLE_ID", config.PENDING_MEMBER_ROLE_NAME)
        if not new_role:
            await interaction.followup.send(f"エラー: ロール「{config.NEW_MEMBER_ROLE_NAME}」が見つかりません。", ephemeral=True)
            return
        if new_role in interaction.user.roles:
            await interaction.followup.send("既に手続きは完了しています。", ephemeral=True)
            return
        try:
            await interaction.user.edit(nick=self.name_input.value)
            await interaction.user.add_roles(new_role)
            if pending_role and pending_role in interaction.user.roles:
                await interaction.user.remove_roles(pending_role)
            await database.add_balance(interaction.user.id, config.INITIAL_COINS)
            await database.set_initial_issued(interaction.user.id)
            await interaction.followup.send(f"✅ 完了！名前を「{self.name_input.value}」にし、{config.INITIAL_COINS} {config.CURRENCY_NAME} を発行しました。", ephemeral=True)
            await config.send_economy_log(
                interaction.guild,
                "🆕 初期通貨発行",
                f"{interaction.user.mention} が入界手続きを行い、初期通貨 **{config.INITIAL_COINS} {config.CURRENCY_NAME}** を受け取りました。",
                user=interaction.user
            )
        except Exception as e:
            print(f"[ERROR] InterviewNicknameModal: {e}")
            await interaction.followup.send("エラー: 権限不足です。Botのロール順位を確認してください。", ephemeral=True)

class InterviewPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="入界手続きを開始", style=discord.ButtonStyle.success, emoji="📝", custom_id="persistent_interview_btn")
    async def start_button(self, interaction, button): await interaction.response.send_modal(InterviewNicknameModal())

class InterviewCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    InterviewerGroup = app_commands.Group(name="面接官", description="【面接官専用】手続きコマンド")

    @InterviewerGroup.command(name="help", description="面接官用コマンドの使い方を表示します")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(title="👔 面接官コマンドの使い方", color=discord.Color.blue())
        embed.add_field(name="/面接官 パネル設置_入界手続き", value="新規メンバーが入界手続きを行うためのボタン付きパネルを現在のチャンネルに送信します。", inline=False)
        embed.add_field(name="/面接官 入界手続き実行", value="現在のチャンネルの履歴（最大50件）から、待機者ロールを持つユーザーの発言を読み取り、「入力された名前への変更」「新規メンバーロールの付与」「待機者ロールの剥奪」「初期通貨の付与」を一括で自動実行します。", inline=False)
        embed.add_field(name="/面接官 チャット削除", value="現在のチャンネルのチャット履歴を、指定した件数分（デフォルト100件）削除します。", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @InterviewerGroup.command(name="パネル設置_入界手続き", description="入界手続きパネルを送信")
    async def s_int(self, it):
        if not config.has_interviewer_role(self.bot, it.user) and not config.has_admin_role(self.bot, it.user) and not it.user.guild_permissions.administrator:
            return await it.response.send_message("権限がありません。", ephemeral=True)
        await it.channel.send(embed=discord.Embed(title="✨ 入界手続き", description="下のボタンから登録してください。", color=discord.Color.green()), view=InterviewPanelView())
        await it.response.send_message("設置完了", ephemeral=True)

    @InterviewerGroup.command(name="入界手続き実行", description="VCチャットの履歴から入界待機者の発言を取得し、入界手続きを一括実行します")
    async def execute_interview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        
        if not config.has_interviewer_role(self.bot, interaction.user) and not config.has_admin_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send("権限がありません。", ephemeral=True)
            
        pending_role = config.get_role_by_setting(self.bot, interaction.guild, "PENDING_MEMBER_ROLE_ID", config.PENDING_MEMBER_ROLE_NAME)
        new_role = config.get_role_by_setting(self.bot, interaction.guild, "NEW_MEMBER_ROLE_ID", config.NEW_MEMBER_ROLE_NAME)
        
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
                await database.add_balance(member.id, config.INITIAL_COINS)
                await database.set_initial_issued(member.id)
                results.append(f"✅ {member.mention} -> **{desired_name}**")
                await config.send_economy_log(
                    interaction.guild,
                    "🆕 初期通貨発行 (一括)",
                    f"面接官の {interaction.user.mention} が {member.mention} の入界手続きを実行し、初期通貨 **{config.INITIAL_COINS} {config.CURRENCY_NAME}** を付与しました。",
                    user=member
                )
                try:
                    await database.add_interviewer_log(interaction.user.id, member.id, interaction.guild.id)
                    interviewer_count = await database.get_interviewer_count(interaction.user.id)
                    vc_name = "❌ VC未接続"
                    if interaction.user.voice and interaction.user.voice.channel:
                        vc_name = f"🔊 {interaction.user.voice.channel.name}"
                    embed_interviewer = discord.Embed(
                        title="📝 面接官アクション: 入界手続き実行",
                        description="面接官による入界手続きアクションが実行されました。",
                        color=discord.Color.purple(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed_interviewer.add_field(name="面接官", value=f"{interaction.user.mention} (ID: {interaction.user.id})", inline=False)
                    embed_interviewer.add_field(name="許可されたユーザー", value=f"{member.mention} (ID: {member.id})", inline=False)
                    embed_interviewer.add_field(name="実行場所", value=vc_name, inline=True)
                    embed_interviewer.add_field(name="対応実績", value=f"累計 {interviewer_count} 人目の対応", inline=True)
                    await config.send_log(interaction.guild, "interviewer", embed_interviewer)
                except Exception as log_err:
                    print(f"[ERROR] Failed to send interviewer log in execute_interview: {log_err}")
            except Exception as e:
                results.append(f"❌ {member.display_name} -> 権限エラー等")
                
        embed = discord.Embed(title="✨ 入界手続き一括実行結果", description="\n".join(results), color=discord.Color.green())
        await interaction.followup.send(embed=embed)

    @InterviewerGroup.command(name="初期発行", description="指定ユーザーの手動入界手続き（初期発行）を行います")
    @app_commands.describe(user="対象ユーザー")
    async def manual_issue(self, interaction: discord.Interaction, user: discord.Member):
        if not config.has_interviewer_role(self.bot, interaction.user) and not config.has_admin_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=False)
        
        pending_role = config.get_role_by_setting(self.bot, interaction.guild, "PENDING_MEMBER_ROLE_ID", config.PENDING_MEMBER_ROLE_NAME)
        new_role = config.get_role_by_setting(self.bot, interaction.guild, "NEW_MEMBER_ROLE_ID", config.NEW_MEMBER_ROLE_NAME)
        
        if not pending_role or not new_role:
            return await interaction.followup.send("エラー：ロールの設定が見つかりません。", ephemeral=True)
            
        try:
            if pending_role in user.roles:
                await user.remove_roles(pending_role)
            if new_role not in user.roles:
                await user.add_roles(new_role)
                
            await database.add_balance(user.id, config.INITIAL_COINS)
            await database.set_initial_issued(user.id)
            
            embed = discord.Embed(
                title="✨ 手動入界手続き完了", 
                description=f"✅ {user.mention} の初期発行を完了しました。\n（ロールの付与・剥奪、初期通貨の付与）", 
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)
            await config.send_economy_log(
                interaction.guild,
                "🆕 初期通貨発行 (手動)",
                f"面接官の {interaction.user.mention} が {user.mention} の手動入界手続きを実行し、初期通貨 **{config.INITIAL_COINS} {config.CURRENCY_NAME}** を付与しました。",
                user=user
            )
            try:
                await database.add_interviewer_log(interaction.user.id, user.id, interaction.guild.id)
                interviewer_count = await database.get_interviewer_count(interaction.user.id)
                vc_name = "❌ VC未接続"
                if interaction.user.voice and interaction.user.voice.channel:
                    vc_name = f"🔊 {interaction.user.voice.channel.name}"
                embed_interviewer = discord.Embed(
                    title="📝 面接官アクション: 初期発行 (手動)",
                    description="面接官による手動入界手続き（初期発行）アクションが実行されました。",
                    color=discord.Color.purple(),
                    timestamp=discord.utils.utcnow()
                )
                embed_interviewer.add_field(name="面接官", value=f"{interaction.user.mention} (ID: {interaction.user.id})", inline=False)
                embed_interviewer.add_field(name="許可されたユーザー", value=f"{user.mention} (ID: {user.id})", inline=False)
                embed_interviewer.add_field(name="実行場所", value=vc_name, inline=True)
                embed_interviewer.add_field(name="対応実績", value=f"累計 {interviewer_count} 人目の対応", inline=True)
                await config.send_log(interaction.guild, "interviewer", embed_interviewer)
            except Exception as log_err:
                print(f"[ERROR] Failed to send interviewer log in manual_issue: {log_err}")
        except Exception as e:
            await interaction.followup.send(f"❌ {user.display_name} の手続き中にエラーが発生しました: {e}", ephemeral=True)

    @InterviewerGroup.command(name="未発行者一括付与", description="過去のログから未発行のメンバーを抽出し、初期発行を一括で行います")
    @app_commands.describe(log_channel_id="ログを参照するチャンネルID（デフォルトは指定のチャンネル）")
    async def batch_initial_issue(self, interaction: discord.Interaction, log_channel_id: str = "1506457200149795006"):
        if not config.has_interviewer_role(self.bot, interaction.user) and not config.has_admin_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=False)
        try:
            target_channel_id = int(log_channel_id)
            channel = interaction.guild.get_channel(target_channel_id)
            if not channel:
                return await interaction.followup.send("エラー：指定されたチャンネルが見つかりません。")

            issued_user_ids = set()
            give_pattern = re.compile(r"✅\s*<@!?(\d+)>\s*に\s*([0-9,]+)\s*Rune\s*付与しました")
            issue_pattern = re.compile(r"✅\s*<@!?(\d+)>\s*の初期発行を完了しました")

            async for message in channel.history(limit=None, oldest_first=True):
                if message.author.id != self.bot.user.id: continue
                content = message.content or ""
                if message.embeds:
                    for embed in message.embeds:
                        if embed.description: content += "\n" + embed.description

                match_give = give_pattern.search(content)
                if match_give:
                    user_id = int(match_give.group(1))
                    amount = int(match_give.group(2).replace(",", ""))
                    if amount >= 30000:
                        issued_user_ids.add(user_id)
                match_issue = issue_pattern.search(content)
                if match_issue:
                    user_id = int(match_issue.group(1))
                    issued_user_ids.add(user_id)

            new_issue_count = 0
            already_issued_count = 0
            for member in interaction.guild.members:
                if member.bot: continue
                if member.id in issued_user_ids:
                    await database.set_initial_issued(member.id)
                    already_issued_count += 1
                else:
                    user_data = await database.get_user(member.id)
                    if user_data["initial_issued"]:
                        already_issued_count += 1
                        continue
                    
                    await database.add_balance(member.id, config.INITIAL_COINS)
                    await database.set_initial_issued(member.id)
                    new_issue_count += 1
                    await config.send_economy_log(
                        interaction.guild,
                        "🆕 初期通貨発行 (未発行者一括)",
                        f"管理者の {interaction.user.mention} による一括処理で、{member.mention} に初期通貨 **{config.INITIAL_COINS} {config.CURRENCY_NAME}** が付与されました。",
                        user=member
                    )

            embed = discord.Embed(title="✨ 一括初期発行 完了", color=discord.Color.green())
            embed.add_field(name="新規発行", value=f"{new_issue_count} 名", inline=True)
            embed.add_field(name="発行済み確認", value=f"{already_issued_count} 名", inline=True)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}")

    @InterviewerGroup.command(name="チャット削除", description="現在のチャンネルのチャット履歴を削除します（最大100件）")
    async def clear_chat(self, interaction: discord.Interaction, amount: int = 100):
        if not config.has_interviewer_role(self.bot, interaction.user) and not config.has_admin_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"✅ {len(deleted)}件のメッセージを削除しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ メッセージを削除する権限（メッセージの管理）がBotにありません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

async def setup(bot):
    cog = InterviewCog(bot)
    await bot.add_cog(cog)
