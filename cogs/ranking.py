import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import database
import config

class Ranking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.vc_reward_loop.start()

    def cog_unload(self):
        self.vc_reward_loop.cancel()

    # --- スラッシュコマンド ---
    rank_group = app_commands.Group(name="rank", description="ランク（レベル）関連のコマンド")

    @rank_group.command(name="status", description="自分または他ユーザーのランク（レベル）を表示します")
    async def rank_status(self, interaction: discord.Interaction, user: discord.Member = None):
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

            tc_needed = tc_next - tc_xp
            tc_est_msgs = -(-tc_needed // config.TC_XP_REWARD)
            
            vc_needed = vc_next - vc_xp
            vc_est_mins = -(-vc_needed // config.VC_XP_PER_MIN)

            embed = discord.Embed(
                title=f"✨ {target_user.display_name} のステータス",
                description=f"{target_user.mention} の活動記録です。",
                color=0x2f3136
            )
            embed.set_thumbnail(url=target_user.display_avatar.url)

            # TC
            tc_value = (
                f"**Level:** `{tc_lv}`\n"
                f"**Next:** `{tc_xp}` / `{tc_next}` XP\n"
                f"{create_progress_bar(tc_xp, tc_next)}\n"
                f"┗ 次のレベルまであと **{tc_needed}** XP\n"
                f"┗ 目安: あと **約{tc_est_msgs}通** のチャット"
            )
            embed.add_field(name="💬 テキスト活動 (TC)", value=tc_value, inline=False)

            # VC
            eval_time_cat_id = config.get_setting(self.bot, "EVAL_TIME_CATEGORY_ID")
            current_session_str = ""

            if target_user.voice and target_user.voice.channel:
                vc = target_user.voice.channel
                cat = vc.category
                join_time = self.bot.vc_sessions.get(target_user.id)
                if join_time:
                    now_aware = datetime.datetime.now(config.JST)
                    delta_sec = (now_aware - join_time).total_seconds()
                    hours = int(delta_sec // 3600)
                    mins = int((delta_sec % 3600) // 60)
                    dur_str = f"{hours}時間{mins}分" if hours > 0 else f"{mins}分"
                else:
                    dur_str = "0分"

                if cat and cat.id == eval_time_cat_id:
                    current_session_str = (
                        f"\n🟢 **現在の滞在先:** {vc.mention} (評価対象)\n"
                        f"　⏱️ 今回の滞在時間: **{dur_str}**"
                    )
                elif config.is_xp_enabled(self.bot, vc):
                    current_session_str = (
                        f"\n🟡 **現在の滞在先:** {vc.mention} (XP対象・評価対象外)\n"
                        f"　⏱️ 今回の滞在時間: **{dur_str}**"
                    )
                else:
                    current_session_str = (
                        f"\n⚪ **現在の滞在先:** {vc.mention} (XP対象外)\n"
                        f"　⏱️ 今回の滞在時間: **{dur_str}**"
                    )

            vc_value = (
                f"**Level:** `{vc_lv}`\n"
                f"**Next:** `{vc_xp}` / `{vc_next}` XP\n"
                f"{create_progress_bar(vc_xp, vc_next)}\n"
                f"┗ 次のレベルまであと **{vc_needed}** XP\n"
                f"┗ 目安: あと **約{vc_est_mins}分** の滞在"
                f"{current_session_str}"
            )
            embed.add_field(name="🎙️ ボイス活動 (VC)", value=vc_value, inline=False)

            # 評価時間
            eval_time_sec = user_data.get("evaluation_vc_time", 0)
            join_time = self.bot.eval_vc_sessions.get(target_user.id)
            if join_time:
                now_aware = datetime.datetime.now(config.JST)
                current_sec = int((now_aware - join_time).total_seconds())
                if current_sec > 0:
                    eval_time_sec += current_sec

            def format_duration(seconds: int) -> str:
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                if hours > 0:
                    return f"{hours}時間{minutes}分"
                return f"{minutes}分"

            embed.add_field(
                name="⏱️ 評価浮上時間",
                value=f"**{format_duration(eval_time_sec)}**",
                inline=False
            )

            embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
            embed.timestamp = datetime.datetime.now(config.JST)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"[ERROR] rank status command: {e}")
            try:
                await interaction.followup.send(f"❌ エラーが発生しました: `{e}`", ephemeral=True)
            except:
                pass

    # --- サブグループ top ---
    # rank_group の中に top_group を子として追加するため、setup_hookでbotに登録する際にバインドされるか、
    # またはCog内で app_commands.Group をネストして定義します。
    rank_top_group = app_commands.Group(name="top", description="ランキング上位を表示します", parent=rank_group)

    @rank_top_group.command(name="tc", description="テキストチャット(TC)のランキング上位10名を表示します")
    async def rank_top_tc(self, interaction: discord.Interaction):
        await self._show_ranking(interaction, "tc")

    @rank_top_group.command(name="vc", description="ボイスチャット(VC)のランキング上位10名を表示します")
    async def rank_top_vc(self, interaction: discord.Interaction):
        await self._show_ranking(interaction, "vc")

    async def _show_ranking(self, interaction: discord.Interaction, mode: str):
        await interaction.response.defer()
        try:
            top_users = await database.get_top_users(mode, 10)
            
            embed = discord.Embed(
                title="💬 TCランキング上位10名" if mode == "tc" else "🎙️ VCランキング上位10名",
                color=0x2f3136
            )
            
            desc = ""
            for i, u in enumerate(top_users):
                member = interaction.guild.get_member(u["user_id"])
                name = member.display_name if member else f"不明なユーザー({u['user_id']})"
                desc += f"**{i+1}位** {name} - Lv.{u['level']} ({u['xp']} XP)\n"
                
            if not desc:
                desc = "データがありません。"
                
            embed.description = desc
            embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
            embed.timestamp = datetime.datetime.now(config.JST)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"[ERROR] rank top command: {e}")
            try:
                await interaction.followup.send(f"❌ エラーが発生しました: `{e}`", ephemeral=True)
            except:
                pass

    # --- リスナーとループ ---

    @tasks.loop(minutes=1)
    async def vc_reward_loop(self):
        now = datetime.datetime.now(config.JST)
        for user_id, last_reward_time in list(self.bot.vc_sessions.items()):
            member = None
            for guild in self.bot.guilds:
                m = guild.get_member(user_id)
                if m and m.voice and m.voice.channel:
                    member = m
                    break
            
            if member:
                in_correct_category = config.is_xp_enabled(self.bot, member.voice.channel)
                if not in_correct_category:
                    self.bot.vc_sessions.pop(user_id, None)
                    continue

                elapsed_minutes = int((now - last_reward_time).total_seconds() / 60)
                if elapsed_minutes >= 1:
                    xp_reward = elapsed_minutes * config.VC_XP_PER_MIN
                    category_name = member.voice.channel.category.name if member.voice.channel and member.voice.channel.category else "なし"
                    print(f"[DEBUG] VC XP Awarding: {member.display_name} in {category_name}")
                    new_lv = await database.add_xp(user_id, xp_reward, "vc")
                    
                    self.bot.vc_sessions[user_id] = last_reward_time + datetime.timedelta(minutes=elapsed_minutes)
                    
                    if new_lv:
                        lv_channel = self.bot.get_channel(config.get_setting(self.bot, "LEVEL_UP_CHANNEL_ID"))
                        if lv_channel:
                            await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
                        await config.check_and_assign_level_roles(self.bot, member, "vc", new_lv)
            else:
                self.bot.vc_sessions.pop(user_id, None)

        eval_cat_id = config.get_setting(self.bot, "EVAL_TIME_CATEGORY_ID")
        for user_id, last_reward_time in list(self.bot.eval_vc_sessions.items()):
            member = None
            for guild in self.bot.guilds:
                m = guild.get_member(user_id)
                if m and m.voice and m.voice.channel:
                    member = m
                    break
            
            if member:
                in_correct_category = member.voice.channel.category and member.voice.channel.category.id == eval_cat_id
                if not in_correct_category:
                    self.bot.eval_vc_sessions.pop(user_id, None)
                    continue

                elapsed_seconds = int((now - last_reward_time).total_seconds())
                if elapsed_seconds >= 60:
                    await database.add_evaluation_vc_time(user_id, elapsed_seconds)
                    print(f"[Eval Time] Mid-loop added {elapsed_seconds}s to {member.display_name}")
                    self.bot.eval_vc_sessions[user_id] = now
            else:
                self.bot.eval_vc_sessions.pop(user_id, None)

    @vc_reward_loop.before_loop
    async def before_vc_reward_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        user_id = message.author.id
        now = datetime.datetime.now(config.JST)

        in_correct_category = config.is_xp_enabled(self.bot, message.channel)

        if in_correct_category:
            last_xp_time = self.bot.tc_xp_cooldowns.get(user_id)
            if not last_xp_time or (now - last_xp_time).total_seconds() > config.TC_XP_COOLDOWN:
                category_name = message.channel.category.name if message.channel.category else "なし"
                print(f"[DEBUG] TC XP Awarding: {message.author.display_name} in {category_name}")
                new_lv = await database.add_xp(user_id, config.TC_XP_REWARD, "tc")
                self.bot.tc_xp_cooldowns[user_id] = now
                if new_lv:
                    lv_channel = self.bot.get_channel(config.get_setting(self.bot, "LEVEL_UP_CHANNEL_ID"))
                    if lv_channel:
                        await lv_channel.send(f"🎊 {message.author.mention} が **TCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
                    if isinstance(message.author, discord.Member):
                        await config.check_and_assign_level_roles(self.bot, message.author, "tc", new_lv)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        user_id = member.id
        now_aware = datetime.datetime.now(config.JST)

        # 評価時間対象カテゴリーの滞在時間追跡
        eval_cat_id = config.get_setting(self.bot, "EVAL_TIME_CATEGORY_ID")
        was_in_eval = before.channel and before.channel.category and before.channel.category.id == eval_cat_id
        is_in_eval = after.channel and after.channel.category and after.channel.category.id == eval_cat_id

        if was_in_eval and not is_in_eval:
            join_time = self.bot.eval_vc_sessions.pop(user_id, None)
            if join_time:
                elapsed_seconds = int((now_aware - join_time).total_seconds())
                if elapsed_seconds > 0:
                    await database.add_evaluation_vc_time(user_id, elapsed_seconds)
                    print(f"[Eval Time] Added {elapsed_seconds}s to {member.display_name}")

        if is_in_eval and not was_in_eval:
            self.bot.eval_vc_sessions[user_id] = now_aware
            print(f"[Eval Time] Started session for {member.display_name}")

        # VCから退出・移動した時
        if before.channel is not None and (after.channel is None or before.channel.id != after.channel.id):
            join_time = self.bot.vc_sessions.pop(user_id, None)
            if join_time:
                duration_minutes = int((now_aware - join_time).total_seconds() / 60)
                if duration_minutes > 0:
                    xp_reward = duration_minutes * config.VC_XP_PER_MIN
                    new_lv = await database.add_xp(user_id, xp_reward, "vc")
                    if new_lv:
                        lv_channel = self.bot.get_channel(config.get_setting(self.bot, "LEVEL_UP_CHANNEL_ID"))
                        if lv_channel:
                            await lv_channel.send(f"🎊 {member.mention} が **VCレベルアップ！** (Lv.{new_lv-1} ➔ **{new_lv}**)")
                        await config.check_and_assign_level_roles(self.bot, member, "vc", new_lv)

        # VCに参加・移動した時
        if after.channel is not None:
            is_join = before.channel is None or before.channel.id != after.channel.id
            if is_join:
                in_correct_category = config.is_xp_enabled(self.bot, after.channel)
                if in_correct_category:
                    print(f"[VC XP] Started session for {member.display_name}")
                    self.bot.vc_sessions[user_id] = now_aware

async def setup(bot):
    cog = Ranking(bot)
    await bot.add_cog(cog)
