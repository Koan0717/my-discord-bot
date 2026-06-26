import discord
from discord.ext import commands
import database
import config

class ShopItemRoleSetupView(discord.ui.View):
    def __init__(self, bot, guild_id: int, item_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.item_id = item_id
        self.target_role_id = None
        self.reward_role_id = None
        
        self.target_select = discord.ui.RoleSelect(placeholder="対象ロールを選択（任意・未選択で誰でも）", min_values=1, max_values=1, custom_id=f"shop_item_target_{item_id}")
        self.target_select.callback = self.target_callback
        self.add_item(self.target_select)
        
        self.reward_select = discord.ui.RoleSelect(placeholder="購入品ロールを選択（任意・未選択でなし）", min_values=1, max_values=1, custom_id=f"shop_item_reward_{item_id}")
        self.reward_select.callback = self.reward_callback
        self.add_item(self.reward_select)
        
        self.save_btn = discord.ui.Button(label="設定完了", style=discord.ButtonStyle.success, custom_id=f"shop_item_save_{item_id}")
        self.save_btn.callback = self.save_callback
        self.add_item(self.save_btn)

    async def target_callback(self, interaction: discord.Interaction):
        self.target_role_id = self.target_select.values[0].id
        await interaction.response.defer()

    async def reward_callback(self, interaction: discord.Interaction):
        self.reward_role_id = self.reward_select.values[0].id
        await interaction.response.defer()

    async def save_callback(self, interaction: discord.Interaction):
        item = await database.get_shop_item(self.item_id)
        if item:
            await database.update_shop_item(self.item_id, item["name"], item["usage"], item["price"], self.target_role_id, self.reward_role_id)
            await interaction.response.send_message(f"「{item['name']}」のロール設定を保存しました。", ephemeral=True)
            self.stop()
        else:
            await interaction.response.send_message("商品の取得に失敗しました。", ephemeral=True)

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
            
            item_id = await database.add_shop_item(self.guild_id, self.name.value, self.usage.value, price_val)
            if item_id:
                await interaction.response.send_message(
                    f"商品「{self.name.value}」の基本情報を追加しました。続いて、対象ロールと購入品ロールを設定してください（任意）。", 
                    view=ShopItemRoleSetupView(self.bot, self.guild_id, item_id), 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("商品の追加に失敗しました。", ephemeral=True)
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
            await database.update_shop_item(self.item["item_id"], self.name.value, self.usage.value, price_val, self.item.get("target_role_id"), self.item.get("reward_role_id"))
            await interaction.response.send_message(
                f"商品「{self.name.value}」の基本情報を更新しました。ロールを再設定する場合は以下のメニューから選択してください。", 
                view=ShopItemRoleSetupView(self.bot, self.guild_id, self.item["item_id"]), 
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("価格は数値で入力してください。", ephemeral=True)

class ShopItemSelect(discord.ui.Select):
    def __init__(self, items, action):
        self.action = action
        options = []
        for item in items:
            options.append(discord.SelectOption(
                label=item["name"][:100],
                description=f"価格: {item['price']}円"[:100],
                value=str(item["item_id"])
            ))
        super().__init__(placeholder="商品を選択してください...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        item_id = int(self.values[0])
        item = await database.get_shop_item(item_id)
        if not item:
            return await interaction.response.send_message("商品が見つかりませんでした。", ephemeral=True)

        if self.action == "edit":
            await interaction.response.send_modal(ShopItemEditModal(item, interaction.client, interaction.guild_id))
        elif self.action == "delete":
            await database.delete_shop_item(item_id)
            await interaction.response.send_message(f"商品「{item['name']}」を削除しました。", ephemeral=True)
        elif self.action == "buy":
            # 対象ロールチェック
            target_role_id = item.get("target_role_id")
            if target_role_id:
                user_role_ids = [r.id for r in interaction.user.roles]
                if target_role_id not in user_role_ids:
                    return await interaction.response.send_message("この商品は対象のロールを持っていないため購入できません。", ephemeral=True)

            # 購入処理
            user_balance = await database.get_balance(interaction.user.id)
            if user_balance < item["price"]:
                return await interaction.response.send_message("所持金が足りません。", ephemeral=True)
            
            # 引き落としとアイテム付与履歴
            await database.add_balance(interaction.user.id, -item["price"])
            await database.add_user_item(interaction.user.id, item["item_id"])
            
            # ロール付与
            reward_role_id = item.get("reward_role_id")
            added_role_msg = ""
            if reward_role_id:
                reward_role = interaction.guild.get_role(reward_role_id)
                if reward_role:
                    try:
                        await interaction.user.add_roles(reward_role)
                        added_role_msg = f"\n特典ロール「{reward_role.name}」が付与されました！"
                    except discord.Forbidden:
                        added_role_msg = f"\n特典ロールの付与に失敗しました（Botの権限が不足しています）。"
            
            await interaction.response.send_message(f"🎉 商品「{item['name']}」を購入しました！{added_role_msg}", ephemeral=True)

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
        items = await database.get_shop_items(self.guild_id)
        if not items:
            return await interaction.response.send_message("編集できる商品がありません。", ephemeral=True)
        await interaction.response.send_message("編集する商品を選択してください:", view=ShopItemSelectView(items, "edit"), ephemeral=True)

    @discord.ui.button(label="商品を削除", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        items = await database.get_shop_items(self.guild_id)
        if not items:
            return await interaction.response.send_message("削除できる商品がありません。", ephemeral=True)
        await interaction.response.send_message("削除する商品を選択してください:", view=ShopItemSelectView(items, "delete"), ephemeral=True)

class ShopPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="ショップを開く", style=discord.ButtonStyle.primary, emoji="🛒", custom_id="shop_panel_open_btn")
    async def open_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        items = await database.get_shop_items(interaction.guild_id)
        if not items:
            return await interaction.response.send_message("現在販売中の商品はありません。", ephemeral=True)
        
        embed = discord.Embed(title="🛒 ショップ", description="購入したい商品を選択してください。", color=discord.Color.gold())
        for item in items:
            target_text = "誰でも"
            if item.get("target_role_id"):
                target_role = interaction.guild.get_role(item["target_role_id"])
                target_text = target_role.mention if target_role else "不明なロール"
            
            reward_text = "なし"
            if item.get("reward_role_id"):
                reward_role = interaction.guild.get_role(item["reward_role_id"])
                reward_text = reward_role.mention if reward_role else "不明なロール"
                
            embed.add_field(name=f"🛒 {item['name']} (価格: {item['price']}円)", value=f"**用途:** {item['usage']}\n**対象:** {target_text}\n**購入品:** {reward_text}", inline=False)
        
        await interaction.response.send_message(embed=embed, view=ShopItemSelectView(items, "buy"), ephemeral=True)

    @discord.ui.button(label="お問い合わせ", style=discord.ButtonStyle.secondary, emoji="✉️", custom_id="shop_panel_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        settings = await database.get_shop_settings(guild.id)
        emp_role_id = settings.get("employee_role_id")
        mgr_role_id = settings.get("manager_role_id")
        
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
        
        channel_name = f"Shop-ticket-{ticket_num:03d}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        if emp_role_id and guild.get_role(emp_role_id):
            overwrites[guild.get_role(emp_role_id)] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if mgr_role_id and guild.get_role(mgr_role_id):
            overwrites[guild.get_role(mgr_role_id)] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=interaction.channel.category,
                overwrites=overwrites
            )
            
            mentions = []
            if emp_role_id: mentions.append(f"<@&{emp_role_id}>")
            if mgr_role_id: mentions.append(f"<@&{mgr_role_id}>")
            mention_str = " ".join(mentions) if mentions else ""
            
            await ticket_channel.send(f"{interaction.user.mention} ショップに関するお問い合わせチケットを作成しました。\n{mention_str}")
            await interaction.response.send_message(f"お問い合わせチャンネル {ticket_channel.mention} を作成しました。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"チケットの作成に失敗しました: {e}", ephemeral=True)



    @discord.ui.button(label="従業員専用", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="shop_panel_employee_btn")
    async def employee_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await database.get_shop_settings(interaction.guild_id)
        emp_role_id = settings.get("employee_role_id")
        mgr_role_id = settings.get("manager_role_id")
        
        user_roles = [r.id for r in interaction.user.roles]
        
        is_emp = emp_role_id in user_roles
        is_mgr = mgr_role_id in user_roles or interaction.user.guild_permissions.administrator
        
        if not (is_emp or is_mgr):
            return await interaction.response.send_message("この機能を使用する権限がありません。", ephemeral=True)
            
        if is_mgr:
            embed = discord.Embed(title="🔒 従業員・統括専用パネル", description="商品の追加や編集、削除を行えます。", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, view=ShopEmployeeView(self.bot, interaction.guild_id), ephemeral=True)
        else:
            await interaction.response.send_message("従業員として認証されました。現在、従業員向けの操作パネルは統括機能のみ提供されています。", ephemeral=True)

class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
