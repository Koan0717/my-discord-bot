import discord
from discord.ext import commands, tasks
import datetime
import asyncio
import database
import config

class Rooms(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_expired_rooms.start()

    def cog_unload(self):
        self.check_expired_rooms.cancel()

    @tasks.loop(minutes=1)
    async def check_expired_rooms(self):
        # 1. 有効期限切れの部屋を削除
        expired_channel_ids = await database.get_expired_rooms()
        for channel_id in expired_channel_ids:
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete()
                except discord.NotFound:
                    pass
            await database.remove_room(channel_id)
            self.bot.empty_custom_vcs.pop(channel_id, None)
        
        # 2. 無人のカスタムVCをチェックして削除 (10分経過)
        now = datetime.datetime.now(config.JST)
        to_delete = []
        for channel_id, empty_since in list(self.bot.empty_custom_vcs.items()):
            if (now - empty_since).total_seconds() >= 600: # 10分 = 600秒
                to_delete.append(channel_id)
        
        for channel_id in to_delete:
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete()
                except discord.NotFound:
                    pass
            await database.remove_room(channel_id)
            self.bot.empty_custom_vcs.pop(channel_id, None)

    @check_expired_rooms.before_loop
    async def before_check_expired_rooms(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            if member.bot: return
            user_id = member.id
            now_aware = datetime.datetime.now(config.JST)

            # 1. VCから退出・移動した時
            if before.channel is not None and (after.channel is None or before.channel.id != after.channel.id):
                # 退出した部屋が無人になった場合
                if len(before.channel.members) == 0:
                    room_data = await database.get_room(before.channel.id)
                    if room_data:
                        if room_data["room_type"] in ["一時部屋", "宿"]:
                            try:
                                print(f"[Auto-VC] Deleting empty room: {before.channel.name}")
                                await before.channel.delete()
                                await database.remove_room(before.channel.id)
                            except Exception as del_e:
                                print(f"[Auto-VC] Delete error: {del_e}")
                        elif room_data["room_type"] == "カスタムVC":
                            self.bot.empty_custom_vcs[before.channel.id] = now_aware

            # 2. VCに参加・移動した時
            if after.channel is not None:
                if after.channel.id in self.bot.auto_vc_triggers:
                    trigger_id = after.channel.id
                    try:
                        pool = await database.get_pool()
                        async with pool.acquire() as conn:
                            existing_room = await conn.fetchrow('SELECT channel_id FROM rooms WHERE owner_id = $1 AND room_type = $2', member.id, "一時部屋")

                        if existing_room:
                            existing_channel = self.bot.get_channel(existing_room["channel_id"])
                            if not existing_channel:
                                try: existing_channel = await self.bot.fetch_channel(existing_room["channel_id"])
                                except: pass

                            if existing_channel:
                                await asyncio.sleep(0.3)
                                if member.voice and member.voice.channel and member.voice.channel.id == trigger_id:
                                    await member.move_to(existing_channel)
                                return
                            else:
                                await database.remove_room(existing_room["channel_id"])

                        guild = member.guild
                        category = after.channel.category

                        channel_name = f"🔊│{member.display_name}の部屋"

                        if category:
                            for existing_ch in category.voice_channels:
                                if existing_ch.name == channel_name:
                                    now_naive_vc = database.get_now_naive()
                                    far_future = now_naive_vc + datetime.timedelta(days=36500)
                                    await database.add_room(existing_ch.id, member.id, "一時部屋", far_future)
                                    await asyncio.sleep(0.3)
                                    if member.voice and member.voice.channel and member.voice.channel.id == trigger_id:
                                        await member.move_to(existing_ch)
                                    return
                        new_channel = await guild.create_voice_channel(
                            name=channel_name,
                            category=category,
                            reason=f"Auto-VC for {member.display_name}"
                        )

                        now_naive_vc = database.get_now_naive()
                        far_future = now_naive_vc + datetime.timedelta(days=36500)
                        await database.add_room(new_channel.id, member.id, "一時部屋", far_future)
                        print(f"[Auto-VC] Created room {new_channel.id} and registered in DB")

                        embed = discord.Embed(
                            title="⚙️ 部屋の設定",
                            description="このボタンから部屋の名前や人数制限を変更できます。",
                            color=discord.Color.blue()
                        )
                        await new_channel.send(embed=embed, view=VCRenamePanelView())

                        for i in range(3):
                            await asyncio.sleep(0.5 if i == 0 else 1.0)
                            if member.voice and member.voice.channel and member.voice.channel.id == trigger_id:
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

                self.bot.empty_custom_vcs.pop(after.channel.id, None)
        except Exception as global_e:
            print(f"CRITICAL ERROR in Rooms.on_voice_state_update: {global_e}")

async def setup(bot):
    await bot.add_cog(Rooms(bot))

# --- VCコントロールパネル系 ---

class ExtendInnSelectView(discord.ui.View):
    def __init__(self, is_free: bool):
        super().__init__(timeout=60)
        p12 = config.ROOM_SETTINGS["宿"][12]["price"]
        p24 = config.ROOM_SETTINGS["宿"][24]["price"]
        self.twelve.label = f"12時間 ({p12:,} {config.CURRENCY_NAME})"
        self.twenty_four.label = f"24時間 ({p24:,} {config.CURRENCY_NAME})"
        if is_free:
            self.twelve.label = "12時間 (無料)"
            self.twenty_four.label = "24時間 (無料)"
            
    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success)
    async def twelve(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = config.ROOM_SETTINGS["宿"][12]["price"]
        await process_room_extension(interaction, "宿", 12, price)
        
    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success)
    async def twenty_four(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = config.ROOM_SETTINGS["宿"][24]["price"]
        await process_room_extension(interaction, "宿", 24, price)
        
    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class ExtendLuxuryInnSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p12 = config.ROOM_SETTINGS["高級宿"][12]["price"]
        p24 = config.ROOM_SETTINGS["高級宿"][24]["price"]
        self.twelve.label = f"12時間 ({p12:,} {config.CURRENCY_NAME})"
        self.twenty_four.label = f"24時間 ({p24:,} {config.CURRENCY_NAME})"
        
    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success)
    async def twelve(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = config.ROOM_SETTINGS["高級宿"][12]["price"]
        await process_room_extension(interaction, "高級宿", 12, price)
        
    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success)
    async def twenty_four(self, interaction: discord.Interaction, button: discord.ui.Button):
        price = config.ROOM_SETTINGS["高級宿"][24]["price"]
        await process_room_extension(interaction, "高級宿", 24, price)
        
    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

async def process_room_extension(interaction: discord.Interaction, room_type: str, duration: int, price: int):
    await interaction.response.defer(ephemeral=True)
    channel_id = interaction.channel_id
    room_data = await database.get_room(channel_id)
    if not room_data:
        return await interaction.edit_original_response(content="この部屋のデータが見つかりません。", view=None)
        
    if room_data.get("expire_at") is None:
        return await interaction.edit_original_response(content="この部屋は無制限のため延長の必要はありません。", view=None)
        
    if interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
        return await interaction.edit_original_response(content="延長は作成者または管理者のみ可能です。", view=None)

    if await database.get_balance(interaction.user.id) < price:
        return await interaction.edit_original_response(content=f"残高が不足しています！(必要: {price} {config.CURRENCY_NAME})", view=None)
        
    if price == 0 or await database.remove_balance(interaction.user.id, price):
        new_expire = room_data["expire_at"] + datetime.timedelta(hours=duration)
        await database.extend_room(channel_id, new_expire)
        embed = discord.Embed(
            title="⏱️ 部屋の延長",
            description=f"**{price} {config.CURRENCY_NAME}** を支払い、部屋の時間を **{duration}時間** 延長しました！\n新しい終了予定時刻: <t:{int(new_expire.timestamp())}:F>",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(content="✅ 延長手続きが完了しました！", view=None)
        await interaction.channel.send(embed=embed)
        if price > 0:
            await config.send_economy_log(
                interaction.guild,
                "🏨 部屋延長",
                f"{interaction.user.mention} が **{price} {config.CURRENCY_NAME}** を支払い、部屋 (<#{channel_id}>) を **{duration}時間** 延長しました。",
                user=interaction.user
            )

async def handle_extend(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    room_data = await database.get_room(channel_id)
    if not room_data:
        await interaction.response.send_message("この部屋のデータが見つかりません。", ephemeral=True)
        return
    if room_data.get("expire_at") is None:
        await interaction.response.send_message("この部屋は無制限のため延長の必要はありません。", ephemeral=True)
        return
    if interaction.user.id != room_data["owner_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("延長は作成者または管理者のみ可能です。", ephemeral=True)
        return
        
    room_type = room_data["room_type"]
    is_free_inn = room_type == "宿" and config.is_main_or_sub_member(interaction.client, interaction.user)
    
    if room_type == "宿":
        view = ExtendInnSelectView(is_free_inn)
        msg = "「一般宿」の延長期間を選択してください。"
        if is_free_inn:
            msg += "\nあなたは対象ロールのため **無料** で延長可能です。"
        await interaction.response.send_message(msg, view=view, ephemeral=True)
    elif room_type == "高級宿":
        view = ExtendLuxuryInnSelectView()
        await interaction.response.send_message("「高級宿」の延長期間を選択してください。", view=view, ephemeral=True)
    elif room_type == "カスタムVC":
        price = config.ROOM_SETTINGS["カスタムVC"][24]["price"]
        await process_room_extension(interaction, "カスタムVC", 24, price)

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
    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="招待するユーザーを選択", custom_id="persistent_room_invite_select", row=2)
    async def invite_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        channel = interaction.channel
        room_data = await database.get_room(channel.id)
        if not room_data or room_data["owner_id"] != interaction.user.id:
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("自分が作成した（所有している）部屋ではありません。", ephemeral=True)
        target_user = select.values[0]
        if target_user == interaction.user:
            return await interaction.response.send_message("自分自身を招待することはできません。", ephemeral=True)
        try:
            await channel.set_permissions(target_user, view_channel=True, connect=True)
            await interaction.response.send_message(f"{target_user.mention} を招待しました！", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"エラーが発生しました: {e}", ephemeral=True)
    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="追放するユーザーを選択", custom_id="persistent_room_kick_select", row=3)
    async def kick_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        channel = interaction.channel
        room_data = await database.get_room(channel.id)
        if not room_data or room_data["owner_id"] != interaction.user.id:
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("自分が作成した（所有している）部屋ではありません。", ephemeral=True)
        target_user = select.values[0]
        if target_user == interaction.user:
            return await interaction.response.send_message("自分自身を追放することはできません。", ephemeral=True)
        try:
            await channel.set_permissions(target_user, overwrite=None)
            if isinstance(target_user, discord.Member) and target_user.voice and target_user.voice.channel == channel:
                await target_user.move_to(None)
            await interaction.response.send_message(f"{target_user.mention} の招待を取り消し、追放しました。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"エラーが発生しました: {e}", ephemeral=True)

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

class VCRenamePanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    @discord.ui.button(label="VC名を変更", style=discord.ButtonStyle.primary, emoji="📝", custom_id="persistent_vc_rename_panel_btn")
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("ボイスチャンネルに参加していません。", ephemeral=True)
        
        room_data = await database.get_room(interaction.user.voice.channel.id)
        if not room_data or room_data["owner_id"] != interaction.user.id:
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

# --- VC購入システム ---

async def process_room_purchase(interaction: discord.Interaction, room_type: str, duration: int):
    await interaction.response.defer(ephemeral=True)
    owner_id = interaction.user.id
    if room_type in ["宿", "高級宿"] and await database.has_room_type(owner_id, ["宿", "高級宿"]):
        return await interaction.edit_original_response(content="既に「宿」を持っています！(1人1つまで)")
    if room_type == "カスタムVC" and await database.has_room_type(owner_id, ["カスタムVC"]):
        return await interaction.edit_original_response(content="既に「カスタムVC」を持っています！")
    
    if duration == 0:
        price = 0
    else:
        settings = config.ROOM_SETTINGS[room_type][duration]
        price = settings["price"]

    if price > 0 and await database.get_balance(owner_id) < price:
        return await interaction.edit_original_response(content="残高が不足しています。")
    
    if price == 0 or await database.remove_balance(owner_id, price):
        try:
            if room_type == "高級宿":
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True, manage_permissions=True)
                }
            elif room_type == "宿":
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True)
                }
                for rid in [1502720032780845097, 1502719973213343814, 1502719883991978033, 1502720409710100520]:
                    role = interaction.guild.get_role(rid)
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(view_channel=True, connect=True)
            else:
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(connect=True),
                    interaction.user: discord.PermissionOverwrite(move_members=True)
                }
            channel = await interaction.guild.create_voice_channel(name=f"{room_type}-{interaction.user.display_name}", category=interaction.channel.category, overwrites=overwrites, user_limit=(2 if room_type=="宿" else 0))
            
            if duration == 0:
                expire_at = None
                dur_str = "無制限"
                end_str = "無制限"
            else:
                expire_at = database.get_now_naive() + datetime.timedelta(hours=duration)
                dur_str = f"{duration}時間"
                end_str = f"<t:{int(expire_at.timestamp())}:F>"
                
            await database.add_room(channel.id, owner_id, room_type, expire_at)
            await interaction.edit_original_response(content=f"✅ {channel.mention} を作成しました！", view=None)
            view = CustomRoomControlView() if room_type=="カスタムVC" else (RoomControlView() if room_type=="高級宿" else InnControlView())
            embed = discord.Embed(title=f"🏠 {room_type}", description=f"作成者: {interaction.user.mention}\n利用期間: {dur_str}\n終了予定: {end_str}", color=discord.Color.blue())
            await channel.send(content=f"{interaction.user.mention}", embed=embed, view=view)
            if price > 0:
                await config.send_economy_log(
                    interaction.guild,
                    "🏨 部屋作成",
                    f"{interaction.user.mention} が **{price} {config.CURRENCY_NAME}** を支払い、部屋 ({channel.mention}) を作成しました。",
                    user=interaction.user
                )
        except Exception as e:
            if price > 0:
                await database.add_balance(owner_id, price)
            await interaction.edit_original_response(content=f"エラー: {e}")

class TempInnDurationSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p12 = config.ROOM_SETTINGS["宿"][12]["price"]
        p24 = config.ROOM_SETTINGS["宿"][24]["price"]
        self.twelve_hours.label = f"12時間 ({p12:,} {config.CURRENCY_NAME})"
        self.twenty_four_hours.label = f"24時間 ({p24:,} {config.CURRENCY_NAME})"

    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success, emoji="🛖")
    async def twelve_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "宿", 12)

    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success, emoji="🛖")
    async def twenty_four_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "宿", 24)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class LuxuryInnDurationSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p12 = config.ROOM_SETTINGS["高級宿"][12]["price"]
        p24 = config.ROOM_SETTINGS["高級宿"][24]["price"]
        self.twelve_hours.label = f"12時間 ({p12:,} {config.CURRENCY_NAME})"
        self.twenty_four_hours.label = f"24時間 ({p24:,} {config.CURRENCY_NAME})"

    @discord.ui.button(label="12時間", style=discord.ButtonStyle.success, emoji="🏰")
    async def twelve_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "高級宿", 12)

    @discord.ui.button(label="24時間", style=discord.ButtonStyle.success, emoji="🏰")
    async def twenty_four_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "高級宿", 24)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class CustomRoomConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        p24 = config.ROOM_SETTINGS["カスタムVC"][24]["price"]
        self.confirm.label = f"確定 (24時間 / {p24:,} {config.CURRENCY_NAME})"

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "カスタムVC", 24)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class MainInnConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="作成する", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_room_purchase(interaction, "宿", 0)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="✖")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class MainInnPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="一般宿を作成 (無料・無制限)", style=discord.ButtonStyle.primary, emoji="🛖", custom_id="persistent_inn_main_btn")
    async def inn_main(self, it, btn):
        if not config.is_main_or_sub_member(it.client, it.user):
            return await it.response.send_message("このパネルは対象ロール(本・準メンバー)をお持ちの方のみ利用可能です。仮メンバーの方は有料の一般宿をご利用ください。", ephemeral=True)
        await it.response.send_message("「一般宿」を無料・時間無制限で作成しますか？", view=MainInnConfirmView(), ephemeral=True)

class TempInnPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="一般宿を作成 (有料)", style=discord.ButtonStyle.primary, emoji="🛖", custom_id="persistent_inn_temp_btn")
    async def inn_temp(self, it, btn):
        if config.is_main_or_sub_member(it.client, it.user):
            return await it.response.send_message("あなたは対象ロール(本・準メンバー)をお持ちのため、専用 of 無料パネルをご利用ください。", ephemeral=True)
        await it.response.send_message("「一般宿」の利用期間を選択してください。", view=TempInnDurationSelectView(), ephemeral=True)

class LuxuryInnPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="高級宿を作成", style=discord.ButtonStyle.primary, emoji="🏰", custom_id="persistent_luxury_inn_panel_btn")
    async def luxury(self, it, btn):
        await it.response.send_message("「高級宿」の利用期間を選択してください。", view=LuxuryInnDurationSelectView(), ephemeral=True)

class CustomRoomView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="カスタムVCを作成", style=discord.ButtonStyle.primary, emoji="✨", custom_id="persistent_custom_room_btn")
    async def custom(self, it, btn):
        await it.response.send_message("「カスタムVC」を購入しますか？", view=CustomRoomConfirmView(), ephemeral=True)
