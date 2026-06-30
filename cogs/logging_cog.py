import discord
from discord.ext import commands
import datetime
import asyncio
import database
import config
import os
import hashlib

class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # 匿名チャットの転送処理（受信場所 -> 設置場所）
        if message.guild:
            panel_channel_ids = await database.get_panel_channel_by_dest(message.channel.id)
            if panel_channel_ids:
                for panel_id in panel_channel_ids:
                    panel_channel = self.bot.get_channel(panel_id) or await self.bot.fetch_channel(panel_id)
                    if panel_channel:
                        embed = discord.Embed(
                            description=message.content,
                            color=discord.Color.green(),
                            timestamp=message.created_at
                        )
                        embed.set_author(name="運営メンバー")
                        
                        files = []
                        if message.attachments:
                            for att in message.attachments:
                                try:
                                    file = await att.to_file()
                                    files.append(file)
                                except:
                                    pass
                                    
                        await panel_channel.send(embed=embed, files=files)
        
        # 1. 常設テンプレート (Sticky Template) 処理
        if message.guild:
            sticky_data = await database.get_sticky_template(message.channel.id)
            if sticky_data:
                if sticky_data["last_message_id"]:
                    try:
                        old_msg = await message.channel.fetch_message(sticky_data["last_message_id"])
                        await old_msg.delete()
                    except:
                        pass
                if sticky_data.get("last_text_message_id"):
                    try:
                        old_text_msg = await message.channel.fetch_message(sticky_data["last_text_message_id"])
                        await old_text_msg.delete()
                    except:
                        pass

                text_content = sticky_data['content']
                new_msg = await message.channel.send(content=text_content)
                await database.update_sticky_last_message(message.channel.id, new_msg.id, None)

        user_id = message.author.id
        now = datetime.datetime.now(config.JST)

        # 2. 荒らし対策: 連続同じメッセージ、@everyone/URLスパム、メンションスパム
        if isinstance(message.author, discord.Member):
            # 適用対象および免除ロールの確認
            guild = message.guild
            if guild:
                cfg = self.bot.get_antigrief_config(guild.id)
                
                # 免除ロールチェック
                exempt_roles = cfg.get("exempt_roles", set())
                author_role_ids = {role.id for role in message.author.roles}
                if exempt_roles & author_role_ids:
                    return
                
                # 対象カテゴリー/チャンネルチェック
                target_categories = cfg.get("categories", set())
                target_channels = cfg.get("channels", set())
                if target_categories or target_channels:
                    in_target_channel = message.channel.id in target_channels
                    in_target_category = message.channel.category and message.channel.category.id in target_categories
                    if not in_target_channel and not in_target_category:
                        return
            user_tracker = self.bot.spam_tracker.setdefault(user_id, {
                "last_content": None,
                "content_count": 0,
                "everyone_url_count": 0,
                "mention_count": 0,
                "last_time": now
            })

            # 3秒以上経過していればリセット
            if (now - user_tracker["last_time"]).total_seconds() > 3:
                user_tracker["content_count"] = 0
                user_tracker["everyone_url_count"] = 0
                user_tracker["mention_count"] = 0

            user_tracker["last_time"] = now
            timeout_reason = None

            # 同じメッセージの連続検知 (内容が存在する場合)
            if message.content and message.content == user_tracker["last_content"]:
                user_tracker["content_count"] += 1
                if user_tracker["content_count"] >= 3:
                    timeout_reason = "連続で同じメッセージを送信したため"
            else:
                user_tracker["last_content"] = message.content
                user_tracker["content_count"] = 1

            # @everyone / @here メンション、またはDiscord招待URL送信の検知 (3秒以内累計5回以上)
            import re
            DISCORD_INVITE_PATTERN = re.compile(
                r'(?:https?://)?(?:www\.)?(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)/[a-zA-Z0-9-]+',
                re.IGNORECASE
            )
            
            if message.mention_everyone or DISCORD_INVITE_PATTERN.search(message.content):
                user_tracker["everyone_url_count"] += 1
                if user_tracker["everyone_url_count"] >= 5:
                    timeout_reason = "短時間にDiscord招待リンクまたは@everyoneメンションを複数回送信したため"

            # メンションスパムの検知 (ユーザーメンション + 役職メンション)
            msg_mentions = len(message.mentions) + len(message.role_mentions)
            if msg_mentions >= 5:
                timeout_reason = "1つのメッセージで大量のメンションを送信したため"
            elif msg_mentions > 0:
                user_tracker["mention_count"] += msg_mentions
                if user_tracker["mention_count"] >= 10:
                    timeout_reason = "短時間に連続してメンションを送信したため"

            if timeout_reason:
                try:
                    # トリガーとなったメッセージの自動削除を試みる
                    try:
                        await message.delete()
                    except discord.Forbidden:
                        print(f"[WARNING] Cannot delete message. Missing permissions.")
                    except Exception as de:
                        print(f"[ERROR] Message deletion failed: {de}")

                    timeout_duration = datetime.timedelta(hours=1)
                    await message.author.timeout(timeout_duration, reason=timeout_reason)
                    await message.channel.send(f"🚨 {message.author.mention} がスパム行為（{timeout_reason}）によりタイムアウトされました。")
                    
                    user_tracker["content_count"] = 0
                    user_tracker["everyone_url_count"] = 0
                    user_tracker["mention_count"] = 0
                    return # スパムなら処理終了
                except Exception as e:
                    print(f"[ERROR] Timeout failed for {message.author.display_name}: {e}")

        # 3. 自己紹介チャンネルでの発言検知（スレッド自動作成）
        guild = message.guild
        if guild:
            cfg = self.bot.get_evaluation_config(guild.id)
            if cfg["forum_channel_ids"] and message.channel.id in cfg["self_intro_channel_ids"]:
                human_role = config.get_role_by_setting(self.bot, guild, "NEW_MEMBER_ROLE_ID", config.NEW_MEMBER_ROLE_NAME)
                if human_role and human_role in message.author.roles:
                    for forum_id in cfg["forum_channel_ids"]:
                        forum_channel = self.bot.get_channel(forum_id)
                        if isinstance(forum_channel, discord.ForumChannel):
                            # 重複チェック: アクティブなスレッド名にユーザー名（アカウント名）が含まれているか
                            duplicate = any(message.author.name in thread.name for thread in forum_channel.threads)
                            
                            if not duplicate:
                                period = await database.get_evaluation_period(user_id)
                                if period:
                                    start_str = config.format_evaluation_datetime(period['start_time'])
                                    end_str = config.format_evaluation_datetime(period['end_time'])
                                    content_thread = (
                                        f"**対象者:** {message.author.mention}\n"
                                        f"**評価期間:** {start_str} ～ {end_str}\n\n"
                                        f"**自己紹介へのリンク:**\n{message.jump_url}"
                                    )
                                else:
                                    content_thread = (
                                        f"**対象者:** {message.author.mention}\n"
                                        f"**評価期間:** データが見つかりませんでした。\n\n"
                                        f"**自己紹介へのリンク:**\n{message.jump_url}"
                                    )
                                    
                                thread_name = f"{message.author.display_name}_{message.author.name}"
                                try:
                                    await forum_channel.create_thread(
                                        name=thread_name,
                                        content=content_thread,
                                        reason=f"Auto created evaluation thread for {message.author.display_name}"
                                    )
                                    print(f"[Evaluation Thread] Created for {message.author.display_name} in forum {forum_id}")
                                except Exception as e:
                                    print(f"[ERROR] Failed to create forum thread in forum {forum_id}: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            if member.bot: return
            
            guild = member.guild
            if guild:
                embed = None
                if before.channel is None and after.channel is not None:
                    embed = discord.Embed(
                        title="🎙️ VC参加",
                        description=f"{member.mention} が {after.channel.mention} に参加しました。",
                        color=discord.Color.green(),
                        timestamp=datetime.datetime.now(config.JST)
                    )
                    embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
                elif before.channel is not None and after.channel is None:
                    embed = discord.Embed(
                        title="🎙️ VC退出",
                        description=f"{member.mention} が {before.channel.mention} から退出しました。",
                        color=discord.Color.red(),
                        timestamp=datetime.datetime.now(config.JST)
                    )
                    embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
                elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
                    embed = discord.Embed(
                        title="🎙️ VC移動",
                        description=f"{member.mention} が {before.channel.mention} から {after.channel.mention} に移動しました。",
                        color=discord.Color.blue(),
                        timestamp=datetime.datetime.now(config.JST)
                    )
                    embed.set_author(name=f"{member} (ID: {member.id})", icon_url=member.display_avatar.url)
                    
                if embed:
                    await config.send_log(guild, "vc_join_leave", embed)
        except Exception as log_e:
            print(f"[ERROR] Failed to send VC log: {log_e}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        room_data = await database.get_room(channel.id)
        if room_data:
            await database.remove_room(channel.id)
            self.bot.empty_custom_vcs.pop(channel.id, None)
        
        await database.remove_inquiry_panel(channel.id)
        await database.remove_anonymous_chat(channel.id)
        await database.remove_custom_ticket_panel(channel.id)

        if channel.guild:
            cfg = self.bot.get_evaluation_config(channel.guild.id)
            changed = False
            if channel.id in cfg["forum_channel_ids"]:
                cfg["forum_channel_ids"].discard(channel.id)
                changed = True
            if channel.id in cfg["self_intro_channel_ids"]:
                cfg["self_intro_channel_ids"].discard(channel.id)
                changed = True
            if changed:
                await database.set_evaluation_settings(channel.guild.id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))



    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        human_role = config.get_role_by_setting(self.bot, after.guild, "NEW_MEMBER_ROLE_ID", config.NEW_MEMBER_ROLE_NAME)
        if human_role and human_role in after.roles and human_role not in before.roles:
            existing = await database.get_evaluation_period(after.id)
            if not existing:
                now = datetime.datetime.now(config.JST)
                if 23 <= now.hour <= 23:
                    start_time = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                else:
                    start_time = now + datetime.timedelta(minutes=5)
                
                end_time = start_time + datetime.timedelta(days=14)
                await database.add_evaluation_period(after.id, start_time, end_time)
                print(f"[Evaluation] Started for {after.display_name}: {start_time} to {end_time}")

        # 評価落ちロール付与検知
        eval_failed_role = config.get_role_by_setting(self.bot, after.guild, "EVALUATION_FAILED_ROLE_ID", config.EVALUATION_FAILED_ROLE_NAME)
        if eval_failed_role and eval_failed_role in after.roles and eval_failed_role not in before.roles:
            await asyncio.sleep(1)
            moderator = None
            reason = "評価基準未到達のため"
            is_manual = True
            try:
                async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_role_update):
                    if entry.target.id == after.id:
                        if eval_failed_role in entry.after.roles and eval_failed_role not in entry.before.roles:
                            moderator = entry.user
                            if entry.reason == "通貨マイナスになったため":
                                is_manual = False
                            break
            except Exception as e:
                print(f"[Evaluation Failure Log] Failed to fetch audit log: {e}")
            
            if is_manual:
                embed = discord.Embed(
                    title="📉 評価落ち",
                    description=f"{after.mention} が評価落ちしました。",
                    color=discord.Color.red()
                )
                embed.add_field(name="理由", value=reason, inline=False)
                embed.add_field(name="実行者", value=moderator.mention if moderator else "不明", inline=False)
                await config.send_log(after.guild, "evaluation_failure", embed)

        # タイムアウト検知ロジック
        guild = after.guild
        if before.timed_out_until != after.timed_out_until:
            now = datetime.datetime.now(config.JST)
            
            if after.timed_out_until and after.timed_out_until > now:
                await asyncio.sleep(1)
                moderator = None
                reason = "理由なし"
                try:
                    async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                        if entry.target.id == after.id:
                            if hasattr(entry.after, "timed_out_until") and entry.after.timed_out_until:
                                moderator = entry.user
                                if entry.reason:
                                    reason = entry.reason
                                break
                except Exception as e:
                    print(f"[Timeout Log] Failed to fetch audit log: {e}")
                
                embed = discord.Embed(
                    description=f"{after.mention} がタイムアウトされました。",
                    color=discord.Color.from_rgb(245, 166, 35)
                )
                embed.set_author(name=after.name, icon_url=after.display_avatar.url)
                embed.set_thumbnail(url=after.display_avatar.url)
                
                duration_val = f"{self.format_relative_time(after.timed_out_until)} (期限: {self.format_absolute_time(after.timed_out_until)})"
                embed.add_field(name="期間", value=duration_val, inline=False)
                embed.add_field(name="理由", value=reason, inline=True)
                embed.add_field(name="実行者", value=moderator.mention if moderator else "不明", inline=True)
                
                embed.set_footer(text=f"🟡 {guild.name} • {self.format_footer_time(now)}")
                embed.timestamp = now
                await config.send_log(guild, "member_join_leave", embed)
            
            elif before.timed_out_until and (not after.timed_out_until or after.timed_out_until <= now):
                await asyncio.sleep(1)
                moderator = None
                reason = "理由なし"
                try:
                    async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                        if entry.target.id == after.id:
                            if hasattr(entry.before, "timed_out_until") and entry.before.timed_out_until and (not hasattr(entry.after, "timed_out_until") or not entry.after.timed_out_until):
                                moderator = entry.user
                                if entry.reason:
                                    reason = entry.reason
                                break
                except Exception as e:
                    print(f"[Timeout Log] Failed to fetch audit log: {e}")
                
                embed = discord.Embed(
                    description=f"{after.mention} のタイムアウトが解除されました。",
                    color=discord.Color.from_rgb(87, 242, 135)
                )
                embed.set_author(name=after.name, icon_url=after.display_avatar.url)
                embed.set_thumbnail(url=after.display_avatar.url)
                
                embed.add_field(name="理由", value=reason, inline=True)
                embed.add_field(name="実行者", value=moderator.mention if moderator else "不明", inline=True)
                
                embed.set_footer(text=f"🟢 {guild.name} • {self.format_footer_time(now)}")
                embed.timestamp = now
                await config.send_log(guild, "member_join_leave", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot:
            return
        if before.content == after.content:
            return
        
        guild = before.guild
        if not guild:
            return
        
        embed = discord.Embed(
            title="📝 メッセージ編集",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(config.JST)
        )
        embed.set_author(name=f"{before.author} (ID: {before.author.id})", icon_url=before.author.display_avatar.url)
        embed.add_field(name="チャンネル", value=before.channel.mention, inline=True)
        embed.add_field(name="メッセージID", value=before.id, inline=True)
        
        before_content = before.content or "*メッセージ内容なし*"
        after_content = after.content or "*メッセージ内容なし*"
        
        if len(before_content) > 1024:
            before_content = before_content[:1020] + "..."
        if len(after_content) > 1024:
            after_content = after_content[:1020] + "..."
            
        embed.add_field(name="変更前", value=before_content, inline=False)
        embed.add_field(name="変更後", value=after_content, inline=False)
        embed.set_footer(text=f"編集者: {before.author.display_name}")
        
        await config.send_log(guild, "message_edit", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
            
        guild = message.guild
        if not guild:
            return
            
        embed = discord.Embed(
            title="🗑️ メッセージ削除",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(config.JST)
        )
        embed.set_author(name=f"{message.author} (ID: {message.author.id})", icon_url=message.author.display_avatar.url)
        embed.add_field(name="チャンネル", value=message.channel.mention, inline=True)
        embed.add_field(name="メッセージID", value=message.id, inline=True)
        
        content = message.content or "*メッセージ内容なし*"
        if len(content) > 1024:
            content = content[:1020] + "..."
        embed.add_field(name="内容", value=content, inline=False)
        
        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            if len(attachment_urls) > 1024:
                attachment_urls = attachment_urls[:1020] + "..."
            embed.add_field(name="添付ファイル", value=attachment_urls, inline=False)
            
        embed.set_footer(text=f"作成者: {message.author.display_name}")
        
        await config.send_log(guild, "message_delete", embed)

    # --- 日時フォーマット用ヘルパー ---
    def format_relative_time(self, dt: datetime.datetime) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        diff = now - dt
        
        years = now.year - dt.year
        months = now.month - dt.month
        if months < 0:
            years -= 1
            months += 12
            
        if years > 0:
            return f"{years}年前"
        if months > 0:
            return f"{months}ヶ月前"
            
        days = diff.days
        if days > 0:
            return f"{days}日前"
            
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours}時間前"
            
        minutes = (diff.seconds % 3600) // 60
        if minutes > 0:
            return f"{minutes}分前"
            
        return f"{diff.seconds}秒前"

    def format_absolute_time(self, dt: datetime.datetime) -> str:
        dt_jst = dt.astimezone(config.JST)
        weekday_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][dt_jst.weekday()]
        return f"{dt_jst.year}年{dt_jst.month}月{dt_jst.day}日 {weekday_ja} {dt_jst.hour}:{dt_jst.minute:02d}"

    def format_footer_time(self, dt: datetime.datetime) -> str:
        dt_jst = dt.astimezone(config.JST)
        now_jst = datetime.datetime.now(config.JST)
        if dt_jst.date() == now_jst.date():
            return f"今日 {dt_jst.strftime('%H:%M')}"
        elif (now_jst.date() - dt_jst.date()).days == 1:
            return f"昨日 {dt_jst.strftime('%H:%M')}"
        else:
            return dt_jst.strftime("%Y/%m/%d %H:%M")

    # --- 招待リンクキャッシュ管理用ヘルパー ---
    async def update_invite_cache(self, guild: discord.Guild):
        if not guild.me.guild_permissions.manage_guild:
            return
        try:
            invites = await guild.invites()
            self.bot.invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
            if guild.vanity_url_code:
                try:
                    vanity = await guild.vanity_invite()
                    self.bot.invite_cache[guild.id]["vanity"] = vanity.uses
                except:
                    pass
        except Exception as e:
            print(f"[Invite Cache] Failed to update cache for guild {guild.id}: {e}")

    async def find_used_invite(self, guild: discord.Guild):
        if guild.id not in self.bot.invite_cache:
            await self.update_invite_cache(guild)
            return None
            
        old_cache = self.bot.invite_cache[guild.id]
        new_invites = {}
        used_invite = None
        
        if guild.me.guild_permissions.manage_guild:
            try:
                invites = await guild.invites()
                for invite in invites:
                    new_invites[invite.code] = invite.uses
                    if invite.uses > old_cache.get(invite.code, 0):
                        used_invite = invite
                
                if guild.vanity_url_code:
                    try:
                        vanity = await guild.vanity_invite()
                        new_invites["vanity"] = vanity.uses
                        if vanity.uses > old_cache.get("vanity", 0):
                            class VanityInvite:
                                code = guild.vanity_url_code
                                uses = vanity.uses
                                inviter = None
                            used_invite = VanityInvite()
                    except:
                        pass
                
                self.bot.invite_cache[guild.id] = new_invites
            except Exception as e:
                print(f"[Invite Cache] Error matching invite: {e}")
                
        return used_invite

    # --- 招待キャッシュ同期リスナー ---
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.update_invite_cache(guild)
        print("[Invite Cache] Initialized invite cache for all guilds.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.update_invite_cache(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        guild = invite.guild
        if guild.id not in self.bot.invite_cache:
            self.bot.invite_cache[guild.id] = {}
        self.bot.invite_cache[guild.id][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        guild = invite.guild
        if guild.id in self.bot.invite_cache:
            self.bot.invite_cache[guild.id].pop(invite.code, None)

    # --- イベントリスナー ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        
        invite = await self.find_used_invite(guild)
        invite_code_val = "不明"
        inviter_val = "不明"
        if invite:
            invite_code_val = f"{invite.code} (使用回数: {invite.uses}回)"
            if invite.inviter:
                inviter_val = invite.inviter.mention
            elif invite.code == guild.vanity_url_code:
                inviter_val = "特別リンク（バニティURL）"
        
        embed = discord.Embed(
            description=f"{member.mention} がサーバーに参加しました",
            color=discord.Color.from_rgb(87, 242, 135)
        )
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        created_val = f"{self.format_relative_time(member.created_at)}\n{self.format_absolute_time(member.created_at)}"
        embed.add_field(name="アカウントの年齢", value=created_val, inline=False)
        
        embed.add_field(name="招待コード", value=invite_code_val, inline=True)
        embed.add_field(name="招待者", value=inviter_val, inline=True)
        
        now = datetime.datetime.now(config.JST)
        embed.set_footer(text=f"🟢 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        
        await config.send_log(guild, "member_join_leave", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        
        embed = discord.Embed(
            description=f"{member.mention} がサーバーから退出しました",
            color=discord.Color.from_rgb(237, 66, 69)
        )
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        if member.joined_at:
            joined_val = f"{self.format_relative_time(member.joined_at)}前 (滞在期間)\n{self.format_absolute_time(member.joined_at)}"
        else:
            joined_val = "不明"
        embed.add_field(name="サーバー参加日", value=joined_val, inline=False)
        
        now = datetime.datetime.now(config.JST)
        embed.set_footer(text=f"🔴 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        
        await config.send_log(guild, "member_join_leave", embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await asyncio.sleep(1)
        moderator = None
        reason = "理由なし"
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    moderator = entry.user
                    if entry.reason:
                        reason = entry.reason
                    break
        except Exception as e:
            print(f"[Ban Log] Failed to fetch audit log: {e}")
            
        embed = discord.Embed(
            description=f"{user.mention} がサーバーからBANされました。",
            color=discord.Color.from_rgb(237, 66, 69)
        )
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(name="理由", value=reason, inline=True)
        embed.add_field(name="実行者", value=moderator.mention if moderator else "不明", inline=True)
        
        now = datetime.datetime.now(config.JST)
        embed.set_footer(text=f"🔴 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        await config.send_log(guild, "member_join_leave", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await asyncio.sleep(1)
        moderator = None
        reason = "理由なし"
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                if entry.target.id == user.id:
                    moderator = entry.user
                    if entry.reason:
                        reason = entry.reason
                    break
        except Exception as e:
            print(f"[Unban Log] Failed to fetch audit log: {e}")
            
        embed = discord.Embed(
            description=f"{user.mention} のBANが解除されました。",
            color=discord.Color.from_rgb(87, 242, 135)
        )
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(name="理由", value=reason, inline=True)
        embed.add_field(name="実行者", value=moderator.mention if moderator else "不明", inline=True)
        
        now = datetime.datetime.now(config.JST)
        embed.set_footer(text=f"🟢 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        await config.send_log(guild, "member_join_leave", embed)

async def setup(bot):
    await bot.add_cog(Logging(bot))

# --- 匿名チャットシステム用UI ---

class AnonymousMessageModal(discord.ui.Modal, title="匿名メッセージ送信"):
    message_input = discord.ui.TextInput(
        label="メッセージ内容",
        style=discord.TextStyle.paragraph,
        placeholder="ここにメッセージを入力してください...",
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        dest_channel_id = await database.get_anonymous_chat(interaction.channel.id)
        if not dest_channel_id:
            return await interaction.followup.send("❌ 掲載先チャンネルが設定されていません。", ephemeral=True)
            
        guild = interaction.guild
        dest_channel = guild.get_channel(dest_channel_id)
        if not dest_channel:
            try:
                dest_channel = await guild.fetch_channel(dest_channel_id)
            except:
                pass
        
        if not dest_channel:
            return await interaction.followup.send("❌ 掲載先チャンネルが見つかりません。削除された可能性があります。", ephemeral=True)
            
        today_str = datetime.datetime.now(config.JST).strftime("%Y-%m-%d")
        salt = os.getenv("ANONYMOUS_SALT", "anon_default_salt_998")
        user_hash = hashlib.sha256(f"{interaction.user.id}-{today_str}-{salt}".encode()).hexdigest()
        anon_id = user_hash[:8].upper()
        
        embed = discord.Embed(
            description=self.message_input.value,
            color=0x2f3136
        )
        embed.set_author(
            name=f"匿名ユーザー (ID: {anon_id})",
            icon_url="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=150"
        )
        embed.timestamp = datetime.datetime.now(config.JST)
        
        try:
            await dest_channel.send(embed=embed)
            await interaction.followup.send("✅ 匿名メッセージを送信しました！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 送信に失敗しました: {e}", ephemeral=True)

class AnonymousChatPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="匿名メッセージを送信", style=discord.ButtonStyle.primary, emoji="💬", custom_id="persistent_anon_chat_btn")
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AnonymousMessageModal())

class AnonymousPanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="① パネルを設置するテキストチャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.panel_channel = self.values[0]
        await self.view.update_state(interaction)

class AnonymousDestChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="② 掲載するテキストチャンネルを選択...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.dest_channel = self.values[0]
        await self.view.update_state(interaction)

class ConfirmAnonymousSetupButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="設定を確定",
            style=discord.ButtonStyle.success,
            emoji="✅",
            row=2,
            disabled=True,
            custom_id="admin_anon_setup_confirm_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel_ch_raw = self.view.panel_channel
        dest_ch_raw = self.view.dest_channel
        
        if not panel_ch_raw or not dest_ch_raw:
            return await interaction.followup.send("❌ 設置先と掲載先の両方を選択してください。", ephemeral=True)
            
        guild = interaction.guild
        panel_ch = guild.get_channel(panel_ch_raw.id)
        dest_ch = guild.get_channel(dest_ch_raw.id)
        
        if not panel_ch:
            try: panel_ch = await guild.fetch_channel(panel_ch_raw.id)
            except: pass
        if not dest_ch:
            try: dest_ch = await guild.fetch_channel(dest_ch_raw.id)
            except: pass
                
        if not panel_ch or not dest_ch:
            return await interaction.followup.send("❌ 選択されたチャンネルが見つかりませんでした。", ephemeral=True)
            
        try:
            await database.add_anonymous_chat(panel_ch.id, dest_ch.id)
            
            embed = discord.Embed(
                title="💬 匿名チャット窓口",
                description=(
                    "こちらのチャンネルは匿名チャットの送信窓口です。\n\n"
                    "下の「匿名メッセージを送信」ボタンを押すと、入力フォーム（モーダル）が開きます。\n"
                    "送信したメッセージは、設定された掲載チャンネルへ匿名で送信されます。\n"
                    "※発言者を特定することはできませんが、なりすまし防止のため毎日ランダムに変わる「日替わり一時ID」が付与されます。"
                ),
                color=discord.Color.purple()
            )
            await panel_ch.send(embed=embed, view=AnonymousChatPanelView())
            
            await interaction.followup.send(
                f"✅ 匿名チャットの設置が完了しました！\n"
                f"設置先: {panel_ch.mention}\n"
                f"掲載先: {dest_ch.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 設置に失敗しました: {e}", ephemeral=True)

class AnonymousChatSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.panel_channel = None
        self.dest_channel = None
        
        self.panel_select = AnonymousPanelChannelSelect()
        self.dest_select = AnonymousDestChannelSelect()
        self.confirm_button = ConfirmAnonymousSetupButton()
        
        self.add_item(self.panel_select)
        self.add_item(self.dest_select)
        self.add_item(self.confirm_button)

    async def update_state(self, interaction: discord.Interaction):
        if self.panel_channel and self.dest_channel:
            self.confirm_button.disabled = False
        else:
            self.confirm_button.disabled = True
            
        embed = discord.Embed(
            title="💬 匿名チャット設定",
            description=(
                "匿名チャットの設置設定を行います。\n\n"
                "**1. パネル（送信ボタン）を設置するテキストチャンネル** を選択してください。\n"
                "**2. 匿名メッセージが掲載されるテキストチャンネル** を選択してください。"
            ),
            color=discord.Color.purple()
        )
        
        panel_mention = self.panel_channel.mention if self.panel_channel else "❌ 未選択"
        dest_mention = self.dest_channel.mention if self.dest_channel else "❌ 未選択"
        
        embed.add_field(name="① パネル設置先", value=panel_mention, inline=True)
        embed.add_field(name="② メッセージ掲載先", value=dest_mention, inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)
