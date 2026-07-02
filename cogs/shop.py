import discord
from discord.ext import commands, tasks
import database
import config

class ShopItemDurationModal(discord.ui.Modal, title="有効期限の設定"):
    duration = discord.ui.TextInput(
        label="有効期限 (日数)", 
        placeholder="日数を半角数字で入力してください (空欄または0で期限なし)", 
        required=False
    )

    def __init__(self, bot, guild_id, item_id, target_role_ids, reward_role_ids, setup_view):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.item_id = item_id
        self.target_role_ids = target_role_ids
        self.reward_role_ids = reward_role_ids
        self.setup_view = setup_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            duration_val = None
            if self.duration.value.strip():
                duration_val = int(self.duration.value.strip())
                if duration_val < 0:
                    return await interaction.response.send_message("日数は0以上である必要があります。", ephemeral=True)
                if duration_val == 0:
                    duration_val = None
            
            await interaction.response.defer(ephemeral=True)
            item = await database.get_shop_item(self.item_id)
            if item:
                await database.update_shop_item(
                    self.item_id, 
                    item["name"], 
                    item["usage"], 
                    item["price"], 
                    self.target_role_ids, 
                    self.reward_role_ids,
                    duration_val
                )
                
                duration_str = f"{duration_val}日" if duration_val else "制限なし (永続)"
                await interaction.followup.send(f"「{item['name']}」のロール・有効期限設定を保存しました。", ephemeral=True)
                
                # ロール設定更新ログの送信
                target_mentions = [interaction.guild.get_role(r).mention for r in self.target_role_ids if interaction.guild.get_role(r)]
                reward_mentions = [interaction.guild.get_role(r).mention for r in self.reward_role_ids if interaction.guild.get_role(r)]
                target_str = "、".join(target_mentions) if target_mentions else "制限なし (誰でも)"
                reward_str = "、".join(reward_mentions) if reward_mentions else "なし"
                
                embed = discord.Embed(title="🛒 商品ロール・有効期限設定更新", color=discord.Color.orange())
                embed.add_field(name="実行者", value=f"{interaction.user.mention} (ID: {interaction.user.id})", inline=False)
                embed.add_field(name="商品ID", value=str(self.item_id), inline=True)
                embed.add_field(name="商品名", value=item["name"], inline=True)
                embed.add_field(name="対象ロール", value=target_str, inline=True)
                embed.add_field(name="購入品ロール", value=reward_str, inline=True)
                embed.add_field(name="有効期限", value=duration_str, inline=True)
                await config.send_log(interaction.guild, "shop", embed)
                
                self.setup_view.stop()
            else:
                await interaction.followup.send("商品の取得に失敗しました。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("有効期限は数値で入力してください。", ephemeral=True)

class ShopItemRoleSetupView(discord.ui.View):
    def __init__(self, bot, guild_id: int, item_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.item_id = item_id
        self.target_role_ids = []
        self.reward_role_ids = []
        
        self.target_select = discord.ui.RoleSelect(
            placeholder="対象ロールを選択（任意・未選択で誰でも）", 
            min_values=1, 
            max_values=25, 
            custom_id=f"shop_item_target_{item_id}"
        )
        self.target_select.callback = self.target_callback
        self.add_item(self.target_select)
        
        self.reward_select = discord.ui.RoleSelect(
            placeholder="購入品ロールを選択（任意・未選択でなし）", 
            min_values=1, 
            max_values=25, 
            custom_id=f"shop_item_reward_{item_id}"
        )
        self.reward_select.callback = self.reward_callback
        self.add_item(self.reward_select)
        
        self.save_btn = discord.ui.Button(
            label="設定完了", 
            style=discord.ButtonStyle.success, 
            custom_id=f"shop_item_save_{item_id}"
        )
        self.save_btn.callback = self.save_callback
        self.add_item(self.save_btn)

    async def target_callback(self, interaction: discord.Interaction):
        self.target_role_ids = [role.id for role in self.target_select.values]
        await interaction.response.defer()

    async def reward_callback(self, interaction: discord.Interaction):
        self.reward_role_ids = [role.id for role in self.reward_select.values]
        await interaction.response.defer()

    async def save_callback(self, interaction: discord.Interaction):
        # モーダルを送信する。レスポンスはモーダルが処理するため、defer は呼ばない
        await interaction.response.send_modal(
            ShopItemDurationModal(
                self.bot, 
                self.guild_id, 
                self.item_id, 
                self.target_role_ids, 
                self.reward_role_ids, 
                self
            )
        )

class ShopItemAddModal(discord.ui.Modal, title="商品の追加"):
    name = discord.ui.TextInput(label="商品名", placeholder="商品名を入力してください", required=True)
    usage = discord.ui.TextInput(label="用途", placeholder="用途を入力してください", style=discord.TextStyle.paragraph, required=True)
    price = discord.ui.TextInput(label="価格 (Bot内通貨)", placeholder="価格を数値で入力してください", required=True)

    def __init__(self, bot, guild_id):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value)
            if price_val < 0:
                return await interaction.response.send_message("価格は0以上である必要があります。", ephemeral=True)
            
            await interaction.response.defer(ephemeral=True)
            item_id = await database.add_shop_item(self.guild_id, self.name.value, self.usage.value, price_val)
            if item_id:
                await interaction.followup.send(
                    f"商品「{self.name.value}」の基本情報を追加しました。続いて、対象ロールと購入品ロールを設定してください（任意）。", 
                    view=ShopItemRoleSetupView(self.bot, self.guild_id, item_id), 
                    ephemeral=True
                )
                
                # 商品追加ログの送信
                embed = discord.Embed(title="🛒 商品追加", color=discord.Color.green())
                embed.add_field(name="実行者", value=f"{interaction.user.mention} (ID: {interaction.user.id})", inline=False)
                embed.add_field(name="商品ID", value=str(item_id), inline=True)
                embed.add_field(name="商品名", value=self.name.value, inline=True)
                embed.add_field(name="価格", value=f"{price_val:,} {config.CURRENCY_NAME}", inline=True)
                embed.add_field(name="用途", value=self.usage.value, inline=False)
                await config.send_log(interaction.guild, "shop", embed)
            else:
                await interaction.followup.send("商品の追加に失敗しました。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("価格は数値で入力してください。", ephemeral=True)

class ShopItemEditModal(discord.ui.Modal, title="商品の編集"):
    def __init__(self, item, bot, guild_id):
        super().__init__()
        self.item = item
        self.bot = bot
        self.guild_id = guild_id
        
        self.name = discord.ui.TextInput(label="商品名", default=item["name"], required=True)
        self.usage = discord.ui.TextInput(label="用途", default=item["usage"], style=discord.TextStyle.paragraph, required=True)
        self.price = discord.ui.TextInput(label="価格", default=str(item["price"]), required=True)

        self.add_item(self.name)
        self.add_item(self.usage)
        self.add_item(self.price)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value)
            await interaction.response.defer(ephemeral=True)
            await database.update_shop_item(
                self.item["item_id"], 
                self.name.value, 
                self.usage.value, 
                price_val, 
                self.item.get("target_role_ids"), 
                self.item.get("reward_role_ids")
            )
            await interaction.followup.send(
                f"商品「{self.name.value}」の基本情報を更新しました。ロールを再設定する場合は以下のメニューから選択してください。", 
                view=ShopItemRoleSetupView(self.bot, self.guild_id, self.item["item_id"]), 
                ephemeral=True
            )
            
            # 商品情報編集ログの送信
            embed = discord.Embed(title="🛒 商品情報編集", color=discord.Color.blue())
            embed.add_field(name="実行者", value=f"{interaction.user.mention} (ID: {interaction.user.id})", inline=False)
            embed.add_field(name="商品ID", value=str(self.item["item_id"]), inline=True)
            embed.add_field(name="商品名", value=self.name.value, inline=True)
            embed.add_field(name="価格", value=f"{price_val:,} {config.CURRENCY_NAME}", inline=True)
            embed.add_field(name="用途", value=self.usage.value, inline=False)
            await config.send_log(interaction.guild, "shop", embed)
        except ValueError:
            await interaction.response.send_message("価格は数値で入力してください。", ephemeral=True)

class ShopItemSelect(discord.ui.Select):
    def __init__(self, items, action):
        self.action = action
        options = []
        for item in items:
            options.append(discord.SelectOption(
                label=item["name"][:100],
                description=f"価格: {item['price']:,} {config.CURRENCY_NAME}"[:100],
                value=str(item["item_id"])
            ))
        super().__init__(placeholder="商品を選択してください...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        item_id = int(self.values[0])
        if self.action == "edit":
            item = await database.get_shop_item(item_id)
            if not item:
                return await interaction.response.send_message("商品が見つかりませんでした。", ephemeral=True)
            await interaction.response.send_modal(ShopItemEditModal(item, interaction.client, interaction.guild_id))
        else:
            await interaction.response.defer(ephemeral=True)
            item = await database.get_shop_item(item_id)
            if not item:
                return await interaction.followup.send("商品が見つかりませんでした。", ephemeral=True)

            if self.action == "delete":
                await database.delete_shop_item(item_id)
                await interaction.followup.send(f"商品「{item['name']}」を削除しました。", ephemeral=True)
                
                # 商品削除ログの送信
                embed = discord.Embed(title="🛒 商品削除", color=discord.Color.red())
                embed.add_field(name="実行者", value=f"{interaction.user.mention} (ID: {interaction.user.id})", inline=False)
                embed.add_field(name="商品ID", value=str(item_id), inline=True)
                embed.add_field(name="商品名", value=item["name"], inline=True)
                embed.add_field(name="価格", value=f"{item['price']:,} {config.CURRENCY_NAME}", inline=True)
                await config.send_log(interaction.guild, "shop", embed)
                
            elif self.action == "buy":
                # 対象ロールチェック
                target_role_ids = item.get("target_role_ids") or []
                if target_role_ids:
                    user_role_ids = [r.id for r in interaction.user.roles]
                    if not any(rid in user_role_ids for rid in target_role_ids):
                        return await interaction.followup.send("この商品は対象のロールを持っていないため購入できません。", ephemeral=True)

                # 購入処理
                user_balance = await database.get_balance(interaction.user.id)
                if user_balance < item["price"]:
                    return await interaction.followup.send("所持金が足りません。", ephemeral=True)
                
                # 有効期限の計算
                import datetime as dt
                duration_days = item.get("duration_days")
                expire_at = None
                if duration_days and duration_days > 0:
                    expire_at = database.get_now_naive() + dt.timedelta(days=duration_days)

                # 引き落としとアイテム付与履歴
                await database.add_balance(interaction.user.id, -item["price"])
                await database.add_user_item(interaction.user.id, item["item_id"], expire_at)
                
                # ロール付与
                reward_role_ids = item.get("reward_role_ids") or []
                added_role_msg = ""
                succeeded_roles = []
                failed_roles = []
                if reward_role_ids:
                    for rid in reward_role_ids:
                        reward_role = interaction.guild.get_role(rid)
                        if reward_role:
                            try:
                                await interaction.user.add_roles(reward_role)
                                succeeded_roles.append(reward_role.name)
                            except discord.Forbidden:
                                failed_roles.append(reward_role.name)
                    
                    if succeeded_roles:
                        added_role_msg += f"\n特典ロール「{'、'.join(succeeded_roles)}」が付与されました！"
                        if duration_days:
                            added_role_msg += f" (有効期限: {duration_days}日間)"
                    if failed_roles:
                        added_role_msg += f"\n特典ロール「{'、'.join(failed_roles)}」の付与に失敗しました（Botの権限が不足しています）。"
                
                await interaction.followup.send(f"🎉 商品「{item['name']}」を購入しました！{added_role_msg}", ephemeral=True)
                
                # 商品購入ログの送信
                embed = discord.Embed(title="🛒 商品購入", color=discord.Color.gold())
                embed.add_field(name="購入者", value=f"{interaction.user.mention} (ID: {interaction.user.id})", inline=False)
                embed.add_field(name="商品ID", value=str(item_id), inline=True)
                embed.add_field(name="商品名", value=item["name"], inline=True)
                embed.add_field(name="支払額", value=f"{item['price']:,} {config.CURRENCY_NAME}", inline=True)
                if succeeded_roles:
                    embed.add_field(name="付与ロール", value="、".join(succeeded_roles), inline=False)
                    if duration_days:
                        embed.add_field(name="有効期限", value=f"{duration_days}日間", inline=True)
                if failed_roles:
                    embed.add_field(name="付与失敗ロール (権限不足等)", value="、".join(failed_roles), inline=False)
                await config.send_log(interaction.guild, "shop", embed)


class ShopItemSelectView(discord.ui.View):
    def __init__(self, items, action):
        super().__init__(timeout=180)
        self.add_item(ShopItemSelect(items, action))

class ShopEmployeeView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="商品を追加", style=discord.ButtonStyle.success, emoji="➕")
    async def add_item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ShopItemAddModal(self.bot, self.guild_id))

    @discord.ui.button(label="商品を編集", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        items = await database.get_shop_items(self.guild_id)
        if not items:
            return await interaction.followup.send("編集できる商品がありません。", ephemeral=True)
        await interaction.followup.send("編集する商品を選択してください:", view=ShopItemSelectView(items, "edit"), ephemeral=True)

    @discord.ui.button(label="商品を削除", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        items = await database.get_shop_items(self.guild_id)
        if not items:
            return await interaction.followup.send("削除できる商品がありません。", ephemeral=True)
        await interaction.followup.send("削除する商品を選択してください:", view=ShopItemSelectView(items, "delete"), ephemeral=True)

class ShopInquiryModal(discord.ui.Modal, title="ショップお問い合わせ"):
    subject = discord.ui.TextInput(
        label="件名",
        placeholder="例: ○○商品の在庫について",
        max_length=100,
        required=True
    )
    details = discord.ui.TextInput(
        label="内容",
        style=discord.TextStyle.paragraph,
        placeholder="お問い合わせ内容の具体的な詳細をご記入ください。",
        required=True,
        max_length=1000
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        settings = await database.get_shop_settings(guild.id)
        emp_role_id = settings.get("employee_role_id")
        mgr_role_id = settings.get("manager_role_id")
        mention_role_ids = settings.get("inquiry_mention_role_ids") or []
        
        current_ticket_nums = []
        for c in guild.text_channels:
            if c.name.lower().startswith("shop-ticket-"):
                try:
                    num = int(c.name.split("-")[-1])
                    current_ticket_nums.append(num)
                except ValueError:
                    pass
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
        
        channel_name = f"shop-ticket-{ticket_num:03d}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        if emp_role_id and guild.get_role(emp_role_id):
            overwrites[guild.get_role(emp_role_id)] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if mgr_role_id and guild.get_role(mgr_role_id):
            overwrites[guild.get_role(mgr_role_id)] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        for m_id in mention_role_ids:
            m_role = guild.get_role(m_id)
            if m_role:
                overwrites[m_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=interaction.channel.category,
                overwrites=overwrites
            )
            
            mentions = [interaction.user.mention]
            valid_mentions = []
            for m_id in mention_role_ids:
                if guild.get_role(m_id):
                    valid_mentions.append(f"<@&{m_id}>")
            if valid_mentions:
                mentions.extend(valid_mentions)
            else:
                if emp_role_id and guild.get_role(emp_role_id):
                    mentions.append(f"<@&{emp_role_id}>")
                if mgr_role_id and guild.get_role(mgr_role_id):
                    mentions.append(f"<@&{mgr_role_id}>")
            mention_str = " ".join(mentions)
            
            embed = discord.Embed(
                title="🛒 ショップお問い合わせチケット",
                description=(
                    f"**件名:** {self.subject.value}\n\n"
                    f"**内容:**\n{self.details.value}\n\n"
                    f"**作成者:** {interaction.user.mention}\n\n"
                    "内容の確認はこちらのチャンネルで行ってください。\n"
                    "完了したら下のボタンでチケットを閉じることができます。"
                ),
                color=discord.Color.gold()
            )
            
            from cogs.tickets import TicketControlView
            await ticket_channel.send(content=mention_str, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"お問い合わせチャンネル {ticket_channel.mention} を作成しました。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"チケットの作成に失敗しました: {e}", ephemeral=True)

class ShopPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="ショップを開く", style=discord.ButtonStyle.primary, emoji="🛒", custom_id="shop_panel_open_btn")
    async def open_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        items = await database.get_shop_items(interaction.guild_id)
        if not items:
            return await interaction.followup.send("現在販売中の商品はありません。", ephemeral=True)
        
        embed = discord.Embed(title="🛒 ショップ", description="購入したい商品を選択してください。", color=discord.Color.gold())
        for item in items:
            target_role_ids = item.get("target_role_ids") or []
            target_text = "誰でも"
            if target_role_ids:
                target_roles = [interaction.guild.get_role(rid).mention for rid in target_role_ids if interaction.guild.get_role(rid)]
                if target_roles:
                    target_text = "、".join(target_roles)
            
            reward_role_ids = item.get("reward_role_ids") or []
            reward_text = "なし"
            if reward_role_ids:
                reward_roles = [interaction.guild.get_role(rid).mention for rid in reward_role_ids if interaction.guild.get_role(rid)]
                if reward_roles:
                    reward_text = "、".join(reward_roles)
            
            duration_days = item.get("duration_days")
            if reward_role_ids and duration_days and duration_days > 0:
                reward_text += f" (有効期限: {duration_days}日間)"
                
            embed.add_field(name=f"🛒 {item['name']} (価格: {item['price']:,} {config.CURRENCY_NAME})", value=f"**用途:** {item['usage']}\n**対象:** {target_text}\n**購入品:** {reward_text}", inline=False)
        
        await interaction.followup.send(embed=embed, view=ShopItemSelectView(items, "buy"), ephemeral=True)

    @discord.ui.button(label="お問い合わせ", style=discord.ButtonStyle.secondary, emoji="✉️", custom_id="shop_panel_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ShopInquiryModal(self.bot))

    @discord.ui.button(label="従業員専用", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="shop_panel_employee_btn")
    async def employee_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        settings = await database.get_shop_settings(interaction.guild_id)
        emp_role_id = settings.get("employee_role_id")
        mgr_role_id = settings.get("manager_role_id")
        
        user_roles = [r.id for r in interaction.user.roles]
        
        is_emp = emp_role_id in user_roles
        is_mgr = mgr_role_id in user_roles or interaction.user.guild_permissions.administrator
        
        if not (is_emp or is_mgr):
            return await interaction.followup.send("この機能を使用する権限がありません。", ephemeral=True)
            
        if is_mgr:
            embed = discord.Embed(title="🔒 従業員・統括専用パネル", description="商品の追加や編集、削除を行えます。", color=discord.Color.red())
            await interaction.followup.send(embed=embed, view=ShopEmployeeView(self.bot, interaction.guild_id), ephemeral=True)
        else:
            await interaction.followup.send("従業員として認証されました。現在、従業員向けの操作パネルは統括機能のみ提供されています。", ephemeral=True)

class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_expired_roles.start()

    def cog_unload(self):
        self.check_expired_roles.cancel()

    @tasks.loop(minutes=1)
    async def check_expired_roles(self):
        try:
            expired_items = await database.get_expired_user_items()
            for item in expired_items:
                guild = self.bot.get_guild(item["guild_id"])
                if not guild:
                    try:
                        guild = await self.bot.fetch_guild(item["guild_id"])
                    except Exception:
                        pass
                
                if guild:
                    member = guild.get_member(item["user_id"])
                    if not member:
                        try:
                            member = await guild.fetch_member(item["user_id"])
                        except Exception:
                            pass
                    
                    if member:
                        removed_roles = []
                        for role_id in (item["reward_role_ids"] or []):
                            role = guild.get_role(role_id)
                            if role:
                                try:
                                    await member.remove_roles(role, reason="購入品ロールの期限切れによる剥奪")
                                    removed_roles.append(role.name)
                                except discord.Forbidden:
                                    print(f"[Shop] Failed to remove role {role.name} from {member.display_name} due to permissions.")
                                except Exception as e:
                                    print(f"[Shop] Error removing role {role.name} from {member.display_name}: {e}")
                        
                        # ログの送信
                        if removed_roles:
                            embed = discord.Embed(title="⏰ 特典ロール期限切れ剥奪", color=discord.Color.red())
                            embed.add_field(name="対象者", value=f"{member.mention} (ID: {member.id})", inline=False)
                            embed.add_field(name="剥奪されたロール", value="、".join(removed_roles), inline=False)
                            await config.send_log(guild, "shop", embed)
                            
                await database.mark_user_item_role_removed(item["id"])
        except Exception as e:
            print(f"[Shop] Error in check_expired_roles loop: {e}")

    @check_expired_roles.before_loop
    async def before_check_expired_roles(self):
        await self.bot.wait_until_ready()

    @commands.command(name="shop_panel")
    @commands.has_permissions(administrator=True)
    async def setup_shop_panel(self, ctx):
        embed = discord.Embed(
            title="🛒 ショップフロント",
            description="鯖内の通行証を買うことができる。\n気になることや何か問題等を発見した際にはお問い合わせボタンを押してください",
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed, view=ShopPanelView(self.bot))

async def setup(bot):
    await bot.add_cog(ShopCog(bot))
    bot.add_view(ShopPanelView(bot))
