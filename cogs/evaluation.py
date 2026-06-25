import discord
from discord.ext import commands
from discord import app_commands
import database
import config

async def get_thread_reaction_counts(interaction: discord.Interaction, user: discord.Member):
    b010 = 0
    b011 = 0
    tier = config.get_evaluator_tier(interaction.client, interaction.user)
    forum_ids = set()
    if tier >= 1:
        if config.get_setting(interaction.client, "EVALUATION_FORUM_TIER1_IDS"): forum_ids.update(config.get_setting(interaction.client, "EVALUATION_FORUM_TIER1_IDS"))
        if config.get_setting(interaction.client, "EVALUATION_FORUM_CHANNEL_IDS"): forum_ids.update(config.get_setting(interaction.client, "EVALUATION_FORUM_CHANNEL_IDS"))
    if tier >= 2:
        if config.get_setting(interaction.client, "EVALUATION_FORUM_TIER2_IDS"): forum_ids.update(config.get_setting(interaction.client, "EVALUATION_FORUM_TIER2_IDS"))
    if tier >= 3:
        if config.get_setting(interaction.client, "EVALUATION_FORUM_TIER3_IDS"): forum_ids.update(config.get_setting(interaction.client, "EVALUATION_FORUM_TIER3_IDS"))
    
    active_threads = []
    try:
        active_threads = await interaction.guild.active_threads()
    except Exception:
        pass
    
    for fid in forum_ids:
        ch = interaction.guild.get_channel(fid)
        if not ch: continue
            
        target_threads = []
        
        # 1. APIから取得したアクティブスレッド
        for t in active_threads:
            if t.parent_id == ch.id:
                name_match = (
                    user.name in t.name or 
                    user.display_name in t.name or 
                    (hasattr(user, 'global_name') and user.global_name and user.global_name in t.name) or
                    str(user.id) in t.name
                )
                if name_match:
                    target_threads.append(t)
                    
        # 2. キャッシュ済みスレッド（重複排除）
        if hasattr(ch, "threads"):
            for t in ch.threads:
                if t not in target_threads:
                    name_match = (
                        user.name in t.name or 
                        user.display_name in t.name or 
                        (hasattr(user, 'global_name') and user.global_name and user.global_name in t.name) or
                        str(user.id) in t.name
                    )
                    if name_match:
                        target_threads.append(t)
                
        # 3. アーカイブ済みスレッド
        if hasattr(ch, 'archived_threads'):
            async for t in ch.archived_threads(limit=100):
                if t not in target_threads:
                    name_match = (
                        user.name in t.name or 
                        user.display_name in t.name or 
                        (hasattr(user, 'global_name') and user.global_name and user.global_name in t.name) or
                        str(user.id) in t.name
                    )
                    if name_match:
                        target_threads.append(t)
                
        for t in target_threads:
            try:
                first_msg = None
                async for msg in t.history(limit=1, oldest_first=True):
                    first_msg = msg
                    break
                
                if first_msg and str(user.id) in first_msg.content:
                    for r in first_msg.reactions:
                        name = r.emoji if isinstance(r.emoji, str) else r.emoji.name
                        if name == "b_010":
                            b010 += r.count
                        elif name == "b_011":
                            b011 += r.count
            except:
                pass
                
    return b010, b011

class EvaluatorSheetSelect(discord.ui.Select):
    def __init__(self, target_user: discord.Member, forum_channels: list, intro_link: str = None):
        self.target_user = target_user
        self.intro_link = intro_link
        options = []
        for ch in forum_channels:
            options.append(discord.SelectOption(label=f"📁 {ch.name}", value=str(ch.id)))
        
        super().__init__(
            placeholder="作成するフォーラムを選択 (複数可)...",
            min_values=1,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        created_links = []
        
        period = await database.get_evaluation_period(self.target_user.id)
        if period:
            start_str = config.format_evaluation_datetime(period['start_time'])
            end_str = config.format_evaluation_datetime(period['end_time'])
            base_content = (
                f"**対象者:** {self.target_user.mention}\n"
                f"**評価期間:** {start_str} ～ {end_str}\n\n"
            )
        else:
            base_content = (
                f"**対象者:** {self.target_user.mention}\n"
                f"**評価期間:** データが見つかりませんでした。\n\n"
            )
            
        if self.intro_link:
            base_content += f"**自己紹介へのリンク:**\n{self.intro_link}"
        else:
            base_content += f"**自己紹介へのリンク:**\n手動作成 (自己紹介リンクなし)"
            
        thread_name = f"{self.target_user.display_name}_{self.target_user.name}"
        
        for val in self.values:
            ch_id = int(val)
            ch = interaction.guild.get_channel(ch_id)
            if not ch: continue
            
            try:
                if isinstance(ch, discord.ForumChannel):
                    thread_with_message = await ch.create_thread(
                        name=thread_name,
                        content=base_content
                    )
                    thread = thread_with_message.thread
                else:
                    thread = await ch.create_thread(
                        name=thread_name,
                        type=discord.ChannelType.public_thread
                    )
                    await thread.send(base_content)
                created_links.append(f"• [{ch.name}]({thread.jump_url})")
            except Exception as e:
                created_links.append(f"• エラー ({ch.name}): {e}")
                
        res = "\n".join(created_links)
        await interaction.followup.send(f"以下の評価シートを作成しました:\n{res}", ephemeral=True)

class EvaluatorSheetSelectView(discord.ui.View):
    def __init__(self, target_user: discord.Member, forum_channels: list, intro_link: str = None):
        super().__init__(timeout=180)
        self.add_item(EvaluatorSheetSelect(target_user, forum_channels, intro_link))

class Evaluation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- 評価期間グループ ---
    EvaluationGroup = app_commands.Group(name="評価期間", description="評価期間関連コマンド")

    @EvaluationGroup.command(name="help", description="評価期間関連コマンドの使い方を表示します")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⏳ 評価期間コマンドの使い方", color=discord.Color.green())
        embed.add_field(name="/評価期間 一覧", value="【運営・評価員専用】現在評価期間中となっているユーザーとその終了予定日時の一覧を表示します。", inline=False)
        embed.add_field(name="/評価期間 確認 [ユーザー]", value="指定したユーザー（指定なしの場合は自分）の評価期間の開始・終了日時を確認します。", inline=False)
        embed.add_field(name="/評価期間 延長 <ユーザー> <日数>", value="【運営・評価員専用】指定したユーザーの評価期間を、指定した日数分だけ延長します。", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @EvaluationGroup.command(name="一覧", description="【運営・評価員専用】評価期間中のユーザー一覧を表示")
    async def list_periods(self, interaction: discord.Interaction):
        if not config.has_evaluator_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        periods = await database.get_all_evaluation_periods()
        if not periods:
            return await interaction.response.send_message("現在評価期間中のユーザーはいません。", ephemeral=True)
            
        embed = discord.Embed(title="📋 評価期間中ユーザー一覧", color=discord.Color.blue())
        for p in periods:
            member = interaction.guild.get_member(p['user_id'])
            name = member.display_name if member else f"ID: {p['user_id']}"
            end_str = config.format_evaluation_datetime(p['end_time'])
            embed.add_field(name=name, value=f"終了予定: {end_str} (<t:{int(p['end_time'].timestamp())}:R>)", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @EvaluationGroup.command(name="確認", description="自分または指定ユーザーの評価期間を確認します")
    @app_commands.describe(user="確認するユーザー (省略した場合は自分)")
    async def check_period(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        is_evaluator = config.has_evaluator_role(self.bot, interaction.user) or interaction.user.guild_permissions.administrator
        
        if target != interaction.user and not is_evaluator:
            return await interaction.response.send_message("他人の評価期間を確認する権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        period = await database.get_evaluation_period(target.id)
        if not period:
            return await interaction.followup.send(f"{target.display_name} は評価期間中ではありません。", ephemeral=True)
            
        start_str = config.format_evaluation_datetime(period['start_time'])
        end_str = config.format_evaluation_datetime(period['end_time'])
        end_t = int(period['end_time'].timestamp())
        
        embed = discord.Embed(title=f"⏳ {target.display_name} の評価期間", color=discord.Color.green())
        embed.add_field(name="開始時刻", value=start_str, inline=False)
        embed.add_field(name="終了予定", value=f"{end_str} (<t:{end_t}:R>)", inline=False)
        
        if is_evaluator:
            counts = await database.get_user_evaluation_counts(target.id)
            db_b010 = counts.get("b_010", 0)
            db_b011 = counts.get("b_011", 0)
            
            thread_b010, thread_b011 = await get_thread_reaction_counts(interaction, target)
            
            emoji_b010 = discord.utils.get(interaction.guild.emojis, name="b_010")
            b010_str = str(emoji_b010) if emoji_b010 else ":b_010:"
            emoji_b011 = discord.utils.get(interaction.guild.emojis, name="b_011")
            b011_str = str(emoji_b011) if emoji_b011 else ":b_011:"
            
            embed.add_field(name="📊 スレッド評価（合算）", value=f"{b010_str} {thread_b010} 個\n{b011_str} {thread_b011} 個", inline=False)
            if db_b010 > 0 or db_b011 > 0:
                embed.add_field(name="💾 過去の追加分（DB）", value=f"{b010_str} {db_b010} 個\n{b011_str} {db_b011} 個", inline=False)
            
        await interaction.followup.send(embed=embed, ephemeral=True)

    @EvaluationGroup.command(name="延長", description="【運営・評価員専用】ユーザーの評価期間を延長します")
    @app_commands.describe(user="延長するユーザー", extra_days="延長する日数")
    async def extend_period(self, interaction: discord.Interaction, user: discord.Member, extra_days: int):
        if not config.has_evaluator_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        if extra_days <= 0:
            return await interaction.response.send_message("1以上の延長日数を指定してください。", ephemeral=True)
            
        success = await database.extend_evaluation_period(user.id, extra_days)
        if not success:
            return await interaction.response.send_message(f"{user.display_name} は評価期間中ではありません。", ephemeral=True)
            
        period = await database.get_evaluation_period(user.id)
        end_str = config.format_evaluation_datetime(period['end_time'])
        await interaction.response.send_message(f"✅ {user.mention} の評価期間を {extra_days} 日延長しました。\n新しい終了予定: {end_str}", ephemeral=True)

    # --- 評価員グループ ---
    EvaluatorSheetGroup = app_commands.Group(name="評価員", description="評価員向けコマンド")

    @EvaluatorSheetGroup.command(name="help", description="評価員向けコマンドとスタンプ集計の仕様について説明します")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔰 評価員コマンド・スタンプ集計の仕様について",
            description="各種評価コマンドと、権限ランクに応じたスタンプ表示制限についての説明です。",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="1. /評価員 評価確認",
            value="対象ユーザーの現在の評価スタンプ数を確認します。\n実行者の権限ランク（見習い/中級/特級など）に応じて、**閲覧できるフォーラムのスタンプ範囲が自動的に制限**されます。",
            inline=False
        )
        embed.add_field(
            name="2. /評価期間 確認",
            value="対象ユーザーの評価期間を確認します。\n一般メンバーが自身を確認した場合は期間のみが表示され、**評価員が確認した場合はスタンプ数も合算して表示**されます（閲覧範囲は1と同じく権限に依存します）。",
            inline=False
        )
        embed.add_field(
            name="3. 【管理者向け】/管理 bot設定",
            value="評価員ロールと対象フォーラムを3段階のランク（見習い・初級、中級・上級、特級・統括）に分けて設定できます。これにより、ランクに応じたスタンプの表示制限が機能します。",
            inline=False
        )
        embed.set_footer(text="※過去にデータベースへ手動追加されたスタンプは、スレッドとは別に「過去の追加分」として表示されます。")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @EvaluatorSheetGroup.command(name="評価シート作成", description="指定したユーザーの評価シート(スレッド)を作成します")
    @app_commands.describe(user="評価シートを作成するユーザー", intro_link="自己紹介のメッセージリンク等（任意）")
    async def create_sheet(self, interaction: discord.Interaction, user: discord.Member, intro_link: str = None):
        if not config.has_evaluator_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        cfg = self.bot.get_evaluation_config(interaction.guild_id)
        forum_ids = cfg.get("forum_channel_ids", [])
        if not forum_ids:
            return await interaction.response.send_message("評価用フォーラムが設定されていません。", ephemeral=True)
            
        forum_channels = []
        for fid in forum_ids:
            ch = interaction.guild.get_channel(fid)
            if ch:
                forum_channels.append(ch)
                
        if not forum_channels:
            return await interaction.response.send_message("有効な評価用フォーラムが見つかりません。", ephemeral=True)
            
        view = EvaluatorSheetSelectView(user, forum_channels, intro_link)
        await interaction.response.send_message(f"{user.display_name} さんの評価シート作成先を選択してください:", view=view, ephemeral=True)

    @EvaluatorSheetGroup.command(name="評価確認", description="指定したユーザーの評価スタンプ数を確認します")
    @app_commands.describe(user="確認するユーザー")
    async def check_eval(self, interaction: discord.Interaction, user: discord.Member):
        if not config.has_evaluator_role(self.bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        counts = await database.get_user_evaluation_counts(user.id)
        db_b010 = counts.get("b_010", 0)
        db_b011 = counts.get("b_011", 0)
        
        thread_b010, thread_b011 = await get_thread_reaction_counts(interaction, user)
        
        emoji_b010 = discord.utils.get(interaction.guild.emojis, name="b_010")
        b010_str = str(emoji_b010) if emoji_b010 else ":b_010:"
        emoji_b011 = discord.utils.get(interaction.guild.emojis, name="b_011")
        b011_str = str(emoji_b011) if emoji_b011 else ":b_011:"

        embed = discord.Embed(title=f"📊 {user.display_name} さんの評価結果", color=discord.Color.blue())
        embed.add_field(name="📊 スレッド評価（合算）", value=f"{b010_str} {thread_b010} 個\n{b011_str} {thread_b011} 個", inline=False)
        if db_b010 > 0 or db_b011 > 0:
            embed.add_field(name="💾 過去の追加分（DB）", value=f"{b010_str} {db_b010} 個\n{b011_str} {db_b011} 個", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    cog = Evaluation(bot)
    await bot.add_cog(cog)
