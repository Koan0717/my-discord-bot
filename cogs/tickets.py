import discord
from discord.ext import commands
import asyncio
import database
import config

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(Tickets(bot))

# --- スタンプ依頼システム ---

class EmblemRequestModal(discord.ui.Modal, title='スタンプ制作依頼'):
    details = discord.ui.TextInput(
        label='依頼内容の詳細',
        style=discord.TextStyle.paragraph,
        placeholder='例: 自分のアイコンを使った「了解」スタンプをお願いします！',
        required=True,
        max_length=500
    )

    def __init__(self, target_member):
        super().__init__()
        self.target_member = target_member

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith("ticket-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"ticket-{ticket_num:03d}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.target_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        roles_to_overwrite = []
        for role_name in config.ADMIN_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                roles_to_overwrite.append(role)
        
        manager_role = config.get_role_by_setting(interaction.client, guild, "EMBLEM_MANAGER_ROLE_ID", config.EMBLEM_MANAGER_ROLE_NAME)
        if manager_role and manager_role not in roles_to_overwrite:
            roles_to_overwrite.append(manager_role)
            
        for role in roles_to_overwrite:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Stamp request ticket for {interaction.user.display_name}"
            )
            
            embed = discord.Embed(
                title="🎨 スタンプ制作依頼チケット",
                description=(
                    f"**依頼者:** {interaction.user.mention}\n"
                    f"**担当者:** {self.target_member.mention}\n\n"
                    f"**【依頼内容】**\n{self.details.value}\n\n"
                    "内容の確認や相談はこちらのチャンネルで行ってください。\n"
                    "完了したら下のボタンでチケットを閉じることができます。"
                ),
                color=discord.Color.blue()
            )
            
            mentions = [interaction.user.mention, self.target_member.mention]
            manager_role = config.get_role_by_setting(interaction.client, guild, "EMBLEM_MANAGER_ROLE_ID", config.EMBLEM_MANAGER_ROLE_NAME)
            if manager_role:
                mentions.append(manager_role.mention)
            
            mention_str = " ".join(mentions)
            await ticket_channel.send(content=mention_str, embed=embed, view=TicketControlView())
            
            await interaction.followup.send(f"✅ チケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class EmblemSelectView(discord.ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=60)
        master_role = config.get_role_by_setting(bot, guild, "EMBLEM_MASTER_ROLE_ID", config.EMBLEM_MASTER_ROLE_NAME)
        manager_role = config.get_role_by_setting(bot, guild, "EMBLEM_MANAGER_ROLE_ID", config.EMBLEM_MANAGER_ROLE_NAME)
        
        member_set = set()
        if master_role: member_set.update(master_role.members)
        if manager_role: member_set.update(manager_role.members)
        
        options = []
        for member in sorted(member_set, key=lambda m: m.display_name):
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"{member.name}"
            ))
        
        if not options:
            self.add_item(discord.ui.Button(label="現在、依頼可能な製作者がいません", disabled=True))
        else:
            select = discord.ui.Select(
                placeholder="担当する製作者を選択してください...",
                options=options[:25]
            )
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_member = interaction.guild.get_member(user_id)
        if not target_member:
            await interaction.response.send_message("メンバーが見つかりませんでした。", ephemeral=True)
            return
        
        await interaction.response.send_modal(EmblemRequestModal(target_member))

class EmblemRequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="スタンプを依頼する", style=discord.ButtonStyle.primary, emoji="🎨", custom_id="persistent_emblem_req_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # callback内で `interaction.client` から `bot` への参照を取得して `get_role_by_setting` に渡す
        master_role = config.get_role_by_setting(interaction.client, interaction.guild, "EMBLEM_MASTER_ROLE_ID", config.EMBLEM_MASTER_ROLE_NAME)
        manager_role = config.get_role_by_setting(interaction.client, interaction.guild, "EMBLEM_MANAGER_ROLE_ID", config.EMBLEM_MANAGER_ROLE_NAME)
        
        member_set = set()
        if master_role: member_set.update(master_role.members)
        if manager_role: member_set.update(manager_role.members)
        
        options = []
        for member in sorted(member_set, key=lambda m: m.display_name):
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"{member.name}"
            ))
            
        if not options:
            await interaction.response.send_message("現在、依頼可能な製作者がいません", ephemeral=True)
            return
            
        view = EmblemSelectView(interaction.client, interaction.guild)
        # SelectOptionなどを正しくバインド
        await interaction.response.send_message("担当者を選択してください：", view=view, ephemeral=True)


# --- 告解チケットシステム ---

class ConfessionRequestModal(discord.ui.Modal, title='告解・相談依頼'):
    details = discord.ui.TextInput(
        label='依頼内容の詳細',
        style=discord.TextStyle.paragraph,
        placeholder='例: 告解をお願いしたいです。 / ○○について相談したいです。',
        required=True,
        max_length=500
    )

    def __init__(self, target_member):
        super().__init__()
        self.target_member = target_member

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith("confess-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"confess-{ticket_num:03d}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.target_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        for role_name in config.ADMIN_ROLE_NAMES + [config.CONFESSION_PRIEST_ROLE_NAME, config.PRIEST_ROLE_NAME]:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Confession ticket for {interaction.user.display_name}"
            )
            
            embed = discord.Embed(
                title="⛪ 告解・相談チケット",
                description=(
                    f"**依頼者:** {interaction.user.mention}\n"
                    f"**担当者:** {self.target_member.mention}\n\n"
                    f"**【相談内容】**\n{self.details.value}\n\n"
                    "内容の確認や相談はこちらのチャンネルで行ってください。\n"
                    "完了したら下のボタンでチケットを閉じることができます。"
                ),
                color=discord.Color.purple()
            )
            
            mentions = []
            for role_name in config.ADMIN_ROLE_NAMES + [config.CONFESSION_PRIEST_ROLE_NAME, config.PRIEST_ROLE_NAME]:
                role = discord.utils.get(guild.roles, name=role_name)
                if role: mentions.append(role.mention)
            
            mention_str = " ".join(mentions)
            await ticket_channel.send(content=f"{interaction.user.mention} {self.target_member.mention} {mention_str}", embed=embed, view=TicketControlView())
            
            await interaction.followup.send(f"✅ チケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class ConfessionSelectView(discord.ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=60)
        priest1_role = config.get_role_by_setting(bot, guild, "CONFESSION_PRIEST_ROLE_ID", config.CONFESSION_PRIEST_ROLE_NAME)
        priest2_role = config.get_role_by_setting(bot, guild, "PRIEST_ROLE_ID", config.PRIEST_ROLE_NAME)
        
        member_set = set()
        if priest1_role: member_set.update(priest1_role.members)
        if priest2_role: member_set.update(priest2_role.members)
        
        options = []
        for member in sorted(member_set, key=lambda m: m.display_name):
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"{member.name}"
            ))
        
        if not options:
            self.add_item(discord.ui.Button(label="現在、対応可能な司祭がいません", disabled=True))
        else:
            select = discord.ui.Select(
                placeholder="担当する司祭を選択してください...",
                options=options[:25]
            )
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_member = interaction.guild.get_member(user_id)
        if not target_member:
            await interaction.response.send_message("メンバーが見つかりませんでした。", ephemeral=True)
            return
        
        await interaction.response.send_modal(ConfessionRequestModal(target_member))

class ConfessionRequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="告解・相談をする", style=discord.ButtonStyle.primary, emoji="⛪", custom_id="persistent_confession_req_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        priest1_role = config.get_role_by_setting(interaction.client, interaction.guild, "CONFESSION_PRIEST_ROLE_ID", config.CONFESSION_PRIEST_ROLE_NAME)
        priest2_role = config.get_role_by_setting(interaction.client, interaction.guild, "PRIEST_ROLE_ID", config.PRIEST_ROLE_NAME)
        
        member_set = set()
        if priest1_role: member_set.update(priest1_role.members)
        if priest2_role: member_set.update(priest2_role.members)
        
        options = []
        for member in sorted(member_set, key=lambda m: m.display_name):
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"{member.name}"
            ))
            
        if not options:
            await interaction.response.send_message("現在、対応可能な司祭がいません", ephemeral=True)
            return
            
        view = ConfessionSelectView(interaction.client, interaction.guild)
        await interaction.response.send_message("担当者を選択してください：", view=view, ephemeral=True)


# --- お問い合わせチケットシステム ---

class InquiryRequestModal(discord.ui.Modal, title="お問い合わせ"):
    subject = discord.ui.TextInput(
        label="件名",
        placeholder="例: ○○について質問",
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

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        role_ids = await database.get_inquiry_panel_roles(interaction.channel.id)
        mention_roles = [guild.get_role(rid) for rid in role_ids]
        mention_roles = [r for r in mention_roles if r is not None]
        
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith("inquiry-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"inquiry-{ticket_num:03d}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        for role_name in config.ADMIN_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        for m_role in mention_roles:
            overwrites[m_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Inquiry ticket for {interaction.user.display_name}"
            )
            
            embed = discord.Embed(
                title="✉️ お問い合わせチケット",
                description=(
                    f"**件名:** {self.subject.value}\n\n"
                    f"**内容:**\n{self.details.value}\n\n"
                    f"**作成者:** {interaction.user.mention}\n\n"
                    "内容の確認はこちらのチャンネルで行ってください。\n"
                    "完了したら下のボタンでチケットを閉じることができます。"
                ),
                color=discord.Color.blue()
            )
            
            mention_str = f"{interaction.user.mention}"
            if mention_roles:
                mention_str += " " + " ".join([r.mention for r in mention_roles])
            else:
                mentions = []
                for role_name in config.ADMIN_ROLE_NAMES:
                    role = discord.utils.get(guild.roles, name=role_name)
                    if role: mentions.append(role.mention)
                if mentions:
                    mention_str += " " + " ".join(mentions)

            await ticket_channel.send(content=mention_str, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ お問い合わせチケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

class InquiryRequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="お問い合わせチケットを作成", style=discord.ButtonStyle.primary, emoji="✉️", custom_id="persistent_inquiry_req_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(InquiryRequestModal())


# --- カスタムチケットパネルシステム ---

class CustomTicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(style=discord.ButtonStyle.primary, custom_id="persistent_custom_ticket_panel_btn")
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel = await database.get_custom_ticket_panel(interaction.channel.id)
        if not panel:
            return await interaction.response.send_message("❌ パネルの設定が見つかりません。設定が削除された可能性があります。", ephemeral=True)
            
        guild = interaction.guild
        target_role_ids = panel.get("target_role_ids", [])
        
        if target_role_ids:
            member_set = set()
            for rid in target_role_ids:
                role = guild.get_role(rid)
                if role:
                    member_set.update(role.members)
            
            options = []
            for member in sorted(member_set, key=lambda m: m.display_name):
                options.append(discord.SelectOption(
                    label=member.display_name,
                    value=str(member.id),
                    description=f"{member.name}"
                ))
                
            if not options:
                return await interaction.response.send_message("❌ 現在、対応可能な担当者がいません（指定されたロールを持つメンバーがいません）。", ephemeral=True)
            
            view = CustomTicketSelectView(options, panel)
            await interaction.response.send_message("担当者を選択してください：", view=view, ephemeral=True)
        else:
            modal = CustomTicketRequestModal(target_member=None, panel=panel)
            await interaction.response.send_modal(modal)

class CustomTicketSelectView(discord.ui.View):
    def __init__(self, options, panel):
        super().__init__(timeout=60)
        self.panel = panel
        
        select = discord.ui.Select(
            placeholder="担当者を選択してください...",
            options=options[:25]
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_member = interaction.guild.get_member(user_id)
        if not target_member:
            return await interaction.response.send_message("メンバーが見つかりませんでした。", ephemeral=True)
            
        modal = CustomTicketRequestModal(target_member=target_member, panel=self.panel)
        await interaction.response.send_modal(modal)

class CustomTicketRequestModal(discord.ui.Modal):
    details = discord.ui.TextInput(
        label="ご用件・相談内容の詳細",
        style=discord.TextStyle.paragraph,
        placeholder="内容を詳しく入力してください。",
        required=True,
        max_length=1000
    )

    def __init__(self, target_member, panel):
        title = panel["panel_title"]
        if len(title) > 45:
            title = title[:42] + "..."
        super().__init__(title=title)
        self.target_member = target_member
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        prefix = self.panel.get("ticket_prefix") or "ticket"
        
        current_ticket_nums = []
        for c in guild.channels:
            if c.name.startswith(f"{prefix}-"):
                try:
                    num = int(c.name.split("-")[1])
                    current_ticket_nums.append(num)
                except:
                    pass
        
        ticket_num = 1
        while ticket_num in current_ticket_nums:
            ticket_num += 1
            
        channel_name = f"{prefix}-{ticket_num:03d}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        if self.target_member:
            overwrites[self.target_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
        for role_name in config.ADMIN_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
        admin_role_ids = config.get_setting(interaction.client, "ADMIN_ROLE_IDS") or []
        for rid in admin_role_ids:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
        for rid in self.panel.get("mention_role_ids", []):
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
        try:
            category = interaction.channel.category
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Custom ticket ({prefix}) for {interaction.user.display_name}"
            )
            
            title_text = f"🎫 {self.panel['panel_title']} チケット"
            desc_text = f"**作成者:** {interaction.user.mention}\n"
            if self.target_member:
                desc_text += f"**担当者:** {self.target_member.mention}\n"
            desc_text += f"\n**【内容】**\n{self.details.value}\n\n"
            desc_text += "内容の確認や相談はこちらのチャンネルで行ってください。\n"
            desc_text += "完了したら下のボタンでチケットを閉じることができます。"
            
            embed = discord.Embed(
                title=title_text,
                description=desc_text,
                color=discord.Color.blue()
            )
            
            mentions = [interaction.user.mention]
            if self.target_member:
                mentions.append(self.target_member.mention)
                
            for rid in self.panel.get("mention_role_ids", []):
                role = guild.get_role(rid)
                if role:
                    mentions.append(role.mention)
                    
            mention_str = " ".join(mentions)
            
            await ticket_channel.send(content=mention_str, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ チケットを作成しました: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)


# --- 共通チケットコントロール ---

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを閉じる", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="persistent_close_ticket_btn")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="確認", description="このチケットを閉じてもよろしいですか？", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, view=TicketCloseConfirmView(), ephemeral=True)

class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="閉じる", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("チケットを削除します...")
        await asyncio.sleep(2)
        await interaction.channel.delete()

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", embed=None, view=None)


# --- お問い合わせセットアップ ---

class InquirySetupRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="通知先（メンション）ロールを選択...",
            min_values=1,
            max_values=10
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        roles = self.values
        channel = interaction.channel
        
        # DBに保存
        await database.add_inquiry_panel(channel.id, [r.id for r in roles])
        
        # チャンネルにお問い合わせボタン付きEmbedを送信
        embed = discord.Embed(
            title="✉️ お問い合わせ窓口",
            description=(
                "お問い合わせやご相談はこちらのボタンからチケットを作成してください。\n\n"
                "ボタンを押すと「件名」と「内容」の入力画面が開きます。"
            ),
            color=discord.Color.blue()
        )
        await channel.send(embed=embed, view=InquiryRequestPanelView())
        
        # 管理者に完了を通知
        mentions_str = ", ".join([r.mention for r in roles])
        await interaction.followup.send(f"✅ お問い合わせパネルを設置し、通知先ロールを {mentions_str} に設定しました。", ephemeral=True)

class InquirySetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(InquirySetupRoleSelect())


# --- カスタムチケットセットアップ ---

class CustomTicketSetupModal(discord.ui.Modal, title="カスタムチケットパネル設定"):
    panel_title = discord.ui.TextInput(
        label="パネルのタイトル",
        placeholder="例: スタンプ制作 依頼所",
        max_length=100,
        required=True
    )
    panel_description = discord.ui.TextInput(
        label="パネルの説明文",
        style=discord.TextStyle.paragraph,
        placeholder="例: ここからスタンプの制作を依頼できます。\n下のボタンを押して担当者を選択してください。",
        max_length=1000,
        required=True
    )
    button_label = discord.ui.TextInput(
        label="ボタンのテキスト",
        placeholder="例: スタンプを依頼する",
        max_length=20,
        default="チケットを作成する",
        required=True
    )
    button_emoji = discord.ui.TextInput(
        label="ボタンの絵文字 (任意 - 絵文字1つ)",
        placeholder="例: 🎨 / ✉️ / ⛪",
        max_length=10,
        required=False
    )
    ticket_prefix = discord.ui.TextInput(
        label="チケット接頭辞 (チャンネル名の頭につく英数字)",
        placeholder="例: ticket (ticket-001のようになります)",
        max_length=15,
        default="ticket",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        view = CustomTicketMentionRoleSelectView(
            title=self.panel_title.value,
            description=self.panel_description.value,
            button_label=self.button_label.value,
            button_emoji=self.button_emoji.value or None,
            prefix=self.ticket_prefix.value
        )
        
        embed = discord.Embed(
            title="🎫 カスタムチケット設定 (1/2)",
            description="チケット作成時に**通知（メンション）するロール**を選択してください。",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CustomTicketMentionRoleSelectView(discord.ui.View):
    def __init__(self, title, description, button_label, button_emoji, prefix):
        super().__init__(timeout=180)
        self.panel_title = title
        self.panel_description = description
        self.button_label = button_label
        self.button_emoji = button_emoji
        self.ticket_prefix = prefix
        
        self.add_item(CustomTicketMentionRoleSelect())


class CustomTicketMentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="通知先（メンション）ロールを選択...",
            min_values=1,
            max_values=10
        )

    async def callback(self, interaction: discord.Interaction):
        roles = self.values
        mention_role_ids = [r.id for r in roles]
        
        view = CustomTicketTargetRoleSelectView(
            title=self.view.panel_title,
            description=self.view.panel_description,
            button_label=self.view.button_label,
            button_emoji=self.view.button_emoji,
            prefix=self.view.ticket_prefix,
            mention_role_ids=mention_role_ids
        )
        
        embed = discord.Embed(
            title="🎫 カスタムチケット設定 (2/2)",
            description=(
                "**依頼先となる人のロール**を選択してください。\n"
                "ここにロールを設定すると、チケット作成時にそのロールを持つメンバーのリストが選択肢として表示されます。\n"
                "設定しない（誰宛てでもない直接のお問い合わせ）場合は、「設定しない（直接作成）」を押してください。"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)


class CustomTicketTargetRoleSelectView(discord.ui.View):
    def __init__(self, title, description, button_label, button_emoji, prefix, mention_role_ids):
        super().__init__(timeout=180)
        self.panel_title = title
        self.panel_description = description
        self.button_label = button_label
        self.button_emoji = button_emoji
        self.ticket_prefix = prefix
        self.mention_role_ids = mention_role_ids
        
        self.add_item(CustomTicketTargetRoleSelect())

    @discord.ui.button(label="設定しない（直接作成）", style=discord.ButtonStyle.secondary, row=2)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.save_and_send_panel(interaction, target_role_ids=[])

    async def save_and_send_panel(self, interaction: discord.Interaction, target_role_ids: list[int]):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        
        # DBに保存
        await database.add_custom_ticket_panel(
            channel_id=channel.id,
            panel_title=self.panel_title,
            panel_description=self.panel_description,
            button_label=self.button_label,
            button_emoji=self.button_emoji,
            mention_role_ids=self.mention_role_ids,
            target_role_ids=target_role_ids,
            ticket_prefix=self.ticket_prefix
        )
        
        # パネル送信
        embed = discord.Embed(
            title=self.panel_title,
            description=self.panel_description,
            color=discord.Color.blue()
        )
        
        view = CustomTicketPanelView()
        button = view.children[0]
        button.label = self.button_label
        if self.button_emoji:
            button.emoji = self.button_emoji
            
        await channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ カスタムチケットパネルを設置しました！", ephemeral=True)


class CustomTicketTargetRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="依頼先（担当）ロールを選択...",
            min_values=1,
            max_values=10,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        roles = self.values
        target_role_ids = [r.id for r in roles]
        await self.view.save_and_send_panel(interaction, target_role_ids)

