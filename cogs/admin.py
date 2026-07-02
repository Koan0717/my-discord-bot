import discord
from discord.ext import commands
from discord import app_commands
import database
import config
import datetime
import os
import asyncio

# 他の Cog / View のインポート
from cogs.reaction_roles import CustomRolePanelSetupModal
from cogs.tickets import InquiryRequestPanelView, EmblemRequestPanelView, ConfessionRequestPanelView, CustomTicketSetupModal, InquirySetupView
from cogs.rooms import MainInnPanelView, TempInnPanelView, LuxuryInnPanelView, CustomRoomView, VCRenamePanelView
from cogs.gambling import ChinchiroView, CoinflipView, SlotView, BlackjackView, RouletteView
from cogs.logging_cog import AnonymousChatSetupView

_bot_instance = None

async def trigger_evaluation_failure(guild, target, reason, executor, bot):
    # 通貨マイナス落ち対象ロールを剥奪
    minus_target_ids = config.get_setting(bot, "MINUS_TARGET_ROLE_IDS") or []
    roles_to_remove = [r for r in target.roles if r.id in minus_target_ids]
    if roles_to_remove:
        try:
            await target.remove_roles(*roles_to_remove, reason=reason)
        except Exception as e:
            print(f"[Evaluation] Failed to remove minus target roles: {e}")

    # 評価落ちロールを付与
    role = config.get_role_by_setting(bot, guild, "EVALUATION_FAILED_ROLE_ID", config.EVALUATION_FAILED_ROLE_NAME)
    if role and role not in target.roles:
        try:
            await target.add_roles(role, reason=reason)
        except Exception as e:
            print(f"[Evaluation] Failed to add role: {e}")
            
    # 自分にしか見えないチャット (DM)
    dm_msg = "審査の結果評価落ちになりました。" if reason != "通貨マイナスになったため" else "通貨がマイナスになった為、評価落ちしました。"
    try:
        await target.send(dm_msg)
    except Exception:
        pass
        
    # 評価落ちログ
    embed = discord.Embed(
        title="📉 評価落ち",
        description=f"{target.mention} が評価落ちしました。",
        color=discord.Color.red()
    )
    embed.add_field(name="理由", value=reason, inline=False)
    embed.add_field(name="実行者", value=executor.mention if executor else "システム", inline=False)
    await config.send_log(guild, "evaluation_failure", embed)

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

def is_admin_or_interviewer():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild:
            return False
        if config.has_admin_role(interaction.client, interaction.user) or config.has_interviewer_role(interaction.client, interaction.user):
            return True
        await interaction.response.send_message("このコマンドを実行する権限がありません（運営または面接官権限が必要です）。", ephemeral=True)
        return False
    return app_commands.check(predicate)


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        global _bot_instance
        _bot_instance = bot

    AdminGroup = app_commands.Group(name="運営", description="【運営専用】管理コマンド")

    @AdminGroup.command(name="設定パネル", description="【運営専用】Botの基本設定パネルを表示します")
    @is_admin()
    async def bot_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = BotSetupMainView(interaction.user, interaction.client)
        embed = await view.build_embed(interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @AdminGroup.command(name="パネル設置", description="【運営専用】各種コントロールパネル（カジノ、部屋作成など）を設置します")
    @is_admin()
    async def panel_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚙️ パネル設置メニュー", description="設置したい機能を選択肢から選んでください。\n（現在のテキストチャンネルに設置用Embedが送信されます）", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=PanelSetupView(), ephemeral=True)

    @AdminGroup.command(name="任意ロールパネル設置", description="【運営専用】ユーザーがリアクションを押すことで自由に付与・剥奪できるロールパネルを設置します")
    @is_admin()
    async def reaction_role_setup(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CustomRolePanelSetupModal())

    @AdminGroup.command(name="固定テンプレート設定", description="【運営専用】このチャンネルのチャットテンプレートを固定し、常に最新の発言として自動更新します")
    @is_admin()
    async def sticky_template_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StickyTemplateModal())

    @AdminGroup.command(name="固定テンプレート削除", description="【運営専用】このチャンネルに設定されている固定テンプレートを削除します")
    @is_admin()
    async def sticky_template_delete(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = interaction.channel_id
        data = await database.get_sticky_template(channel_id)
        if not data:
            return await interaction.followup.send("❌ このチャンネルには固定テンプレートが設定されていません。", ephemeral=True)
        
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
        await interaction.followup.send("✅ 固定テンプレートを削除しました。", ephemeral=True)

    @AdminGroup.command(name="チャット消去", description="【運営・面接官専用】チャンネル内のメッセージを指定された件数分、一括削除します")
    @is_admin_or_interviewer()
    async def clear_chat(self, interaction: discord.Interaction, count: int):
        if count <= 0:
            return await interaction.response.send_message("1以上の件数を指定してください。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=count)
        await interaction.followup.send(f"🧹 メッセージを {len(deleted)} 件削除しました。", ephemeral=True)

    @AdminGroup.command(name="手動給与", description="【運営専用】指定したユーザーに通貨を直接発行して付与します（最大10人まで）")
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
            new_bal = await database.add_balance(t.id, amount)
            await it.followup.send(f"✅ {t.mention} に {amount} {config.CURRENCY_NAME} 付与しました。")
            await config.send_economy_log(
                it.guild,
                "💰 通貨付与 (手動給与)",
                f"管理者の {it.user.mention} が {t.mention} に **{amount} {config.CURRENCY_NAME}** を付与しました。",
                user=it.user
            )
            if new_bal < 0:
                minus_target_ids = config.get_setting(self.bot, "MINUS_TARGET_ROLE_IDS") or []
                member_roles = [r.id for r in t.roles]
                if any(rid in minus_target_ids for rid in member_roles):
                    await trigger_evaluation_failure(it.guild, t, "通貨マイナスになったため", it.user, self.bot)

    @AdminGroup.command(name="手動没収", description="【運営専用】指定したユーザーから通貨を直接没収します")
    @app_commands.describe(target="没収するユーザー", amount="金額")
    @is_admin()
    async def remove(self, it: discord.Interaction, target: discord.Member, amount: int):
        if amount <= 0:
            await it.response.send_message("❌ 1以上の金額を指定してください。", ephemeral=True)
            return
        await it.response.defer()
        await database.remove_balance(target.id, amount, force=True)
        new_bal = await database.get_balance(target.id)
        await it.followup.send(f"✅ {target.mention} から {amount} {config.CURRENCY_NAME} 没収しました。（現在の残高: **{new_bal} {config.CURRENCY_NAME}**）")
        await config.send_economy_log(
            it.guild,
            "📉 通貨没収 (手動没収)",
            f"管理者の {it.user.mention} が {target.mention} から **{amount} {config.CURRENCY_NAME}** を没収しました。（新残高: {new_bal:,} {config.CURRENCY_NAME}）",
            user=it.user,
            color=discord.Color.red()
        )
        if new_bal < 0:
            minus_target_ids = config.get_setting(self.bot, "MINUS_TARGET_ROLE_IDS") or []
            member_roles = [r.id for r in target.roles]
            if any(rid in minus_target_ids for rid in member_roles):
                await trigger_evaluation_failure(it.guild, target, "通貨マイナスになったため", it.user, self.bot)

    @AdminGroup.command(name="所持金リセット", description="【運営専用】指定したユーザーの所持金を初期化します")
    @app_commands.checks.has_permissions(administrator=True)
    async def rbal(self, it, user: discord.Member):
        await database.reset_user_balance(user.id)
        await it.response.send_message("リセット完了", ephemeral=True)
        await config.send_economy_log(
            it.guild,
            "🔄 所持金リセット",
            f"管理者の {it.user.mention} が {user.mention} の所持金をリセットしました。",
            user=it.user,
            color=discord.Color.red()
        )

    @AdminGroup.command(name="一括初期給与", description="【運営専用】まだ初期給与（30000コイン）を受け取っていない全員に一括で発行します")
    @is_admin()
    async def batch_initial_issue(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        bot = self.bot
        new_role = config.get_role_by_setting(bot, guild, "NEW_MEMBER_ROLE_ID", config.NEW_MEMBER_ROLE_NAME)
        if not new_role:
            return await interaction.followup.send(f"❌ 新規メンバーロールが設定されていないか見つかりません。", ephemeral=True)
            
        initial_coins = config.INITIAL_COINS
        cur_name = config.CURRENCY_NAME
        
        issued_count = 0
        issued_members = []
        for member in new_role.members:
            if member.bot: continue
            
            user_data = await database.get_user(member.id)
            if not user_data.get("initial_issued", False):
                await database.add_balance(member.id, initial_coins)
                await database.set_initial_issued(member.id)
                issued_count += 1
                issued_members.append(f"{member.mention} (ID: {member.id})")
                
        await interaction.followup.send(f"✅ 未受け取りの {issued_count} 名に初期給与 **{initial_coins} {cur_name}** を発行しました！", ephemeral=True)

        if issued_count > 0:
            embed = discord.Embed(
                title="🪙 一括初期給与 (運営)",
                description="運営による一括初期給与が実行されました。",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="実行者", value=f"{interaction.user.mention} ({interaction.user.id})", inline=True)
            embed.add_field(name="対象人数", value=f"{issued_count} 名", inline=True)
            embed.add_field(name="発行総額", value=f"{issued_count * initial_coins:,} {cur_name}", inline=True)
            
            members_text = "\n".join(issued_members[:20])
            if len(issued_members) > 20:
                members_text += f"\n他 {len(issued_members) - 20} 名..."
            embed.add_field(name="対象メンバー一覧 (最大20名)", value=members_text, inline=False)
            
            await config.send_log(interaction.guild, "economy", embed)

    @AdminGroup.command(name="デバッグ_一時部屋", description="【運営専用】一時部屋のDB登録状況を確認します")
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

    @AdminGroup.command(name="デバッグ用vc強制退室", description="【運営専用】指定したユーザーのVC接続セッションを強制的に終了させます（時間測定のバグ修正用）")
    @is_admin()
    @app_commands.describe(user="強制退室させるユーザー")
    async def debug_vc_kick(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        session = self.bot.vc_sessions.pop(user.id, None)
        if session:
            await interaction.followup.send(f"✅ {user.display_name} のVCセッションを破棄しました。", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ {user.display_name} はVCセッションを保持していませんでした。", ephemeral=True)

    @AdminGroup.command(name="ランクリセット", description="【運営専用】ユーザーのレベル・経験値をリセットします")
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



# --- ショップ設定 ---

async def update_shop_settings_config_view(interaction: discord.Interaction, bot):
    view = ShopSettingsConfigView(bot, interaction.guild_id)
    embed = await view.build_embed(interaction.guild)
    await interaction.response.edit_message(embed=embed, view=view)

class ShopSettingsConfigView(discord.ui.View):
    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id

    async def build_embed(self, guild):
        shop_settings = await database.get_shop_settings(self.guild_id)
        emp_role = guild.get_role(shop_settings["employee_role_id"]) if shop_settings["employee_role_id"] else None
        mgr_role = guild.get_role(shop_settings["manager_role_id"]) if shop_settings["manager_role_id"] else None
        
        mention_roles_text = "未設定"
        mention_role_ids = shop_settings.get("inquiry_mention_role_ids") or []
        if mention_role_ids:
            mentions = [guild.get_role(rid).mention for rid in mention_role_ids if guild.get_role(rid)]
            if mentions:
                mention_roles_text = ", ".join(mentions)
        
        embed = discord.Embed(
            title="🛒 ショップ設定",
            description="ショップの従業員ロール、統括ロール、およびお問い合わせの通知先メンションを設定します。",
            color=discord.Color.gold()
        )
        embed.add_field(name="ショップ従業員ロール", value=emp_role.mention if emp_role else "未設定", inline=False)
        embed.add_field(name="ショップ統括ロール", value=mgr_role.mention if mgr_role else "未設定", inline=False)
        embed.add_field(name="お問い合わせ通知先メンション", value=mention_roles_text, inline=False)
        return embed

    @discord.ui.button(label="従業員ロールを設定", style=discord.ButtonStyle.primary, custom_id="persistent_admin_shop_emp_btn")
    async def set_employee_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopRoleSelectView(self.bot, self.guild_id, "employee")
        await interaction.response.edit_message(content="従業員ロールを選択してください：", view=view, embed=None)

    @discord.ui.button(label="統括ロールを設定", style=discord.ButtonStyle.primary, custom_id="persistent_admin_shop_mgr_btn")
    async def set_manager_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopRoleSelectView(self.bot, self.guild_id, "manager")
        await interaction.response.edit_message(content="統括ロールを選択してください：", view=view, embed=None)

    @discord.ui.button(label="お問い合わせメンションを設定", style=discord.ButtonStyle.primary, custom_id="persistent_admin_shop_mention_btn")
    async def set_mention_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopRoleSelectView(self.bot, self.guild_id, "mention")
        await interaction.response.edit_message(content="お問い合わせ通知先となるメンションロールを選択してください：", view=view, embed=None)

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, custom_id="persistent_admin_shop_back_btn")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = BotSetupMainView(interaction.user, self.bot)
        embed = await view.build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)


class ShopRoleSelectView(discord.ui.View):
    def __init__(self, bot, guild_id: int, role_type: str):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.role_type = role_type
        
        if role_type == "employee":
            placeholder = "従業員ロールを選択..."
            max_values = 1
        elif role_type == "manager":
            placeholder = "統括ロールを選択..."
            max_values = 1
        else:
            placeholder = "通知先メンションロールを選択（複数可）..."
            max_values = 10
            
        self.select = discord.ui.RoleSelect(placeholder=placeholder, min_values=1, max_values=max_values, custom_id="shop_role_select")
        self.select.callback = self.role_select_callback
        self.add_item(self.select)

        # Add manual ID button
        btn_manual = discord.ui.Button(label="手動でIDを入力", style=discord.ButtonStyle.secondary, custom_id="shop_role_manual_btn")
        btn_manual.callback = self.manual_input_callback
        self.add_item(btn_manual)

    async def manual_input_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ShopRoleModal(self.bot, self.guild_id, self.role_type))

    async def role_select_callback(self, interaction: discord.Interaction):
        settings = await database.get_shop_settings(self.guild_id)
        emp_role_id = settings["employee_role_id"]
        mgr_role_id = settings["manager_role_id"]
        mention_role_ids = settings.get("inquiry_mention_role_ids") or []
        
        if self.role_type == "employee":
            emp_role_id = self.select.values[0].id
            role_str = self.select.values[0].mention
        elif self.role_type == "manager":
            mgr_role_id = self.select.values[0].id
            role_str = self.select.values[0].mention
        else:
            mention_role_ids = [role.id for role in self.select.values]
            role_str = ", ".join([role.mention for role in self.select.values])
            
        first_mention_role_id = mention_role_ids[0] if mention_role_ids else None
        await database.set_shop_settings(self.guild_id, emp_role_id, mgr_role_id, first_mention_role_id, mention_role_ids)
        role_type_ja = "従業員" if self.role_type == "employee" else ("統括" if self.role_type == "manager" else "お問い合わせ通知先メンション")
        await interaction.response.send_message(f"{role_type_ja}ロールを {role_str} に設定しました。", ephemeral=True)
        
        try:
            view = ShopSettingsConfigView(self.bot, self.guild_id)
            embed = await view.build_embed(interaction.guild)
            await interaction.message.edit(embed=embed, view=view)
        except:
            pass

class ShopRoleModal(discord.ui.Modal):
    def __init__(self, bot, guild_id: int, role_type: str):
        if role_type == "employee":
            title = "ショップ従業員ロール設定"
        elif role_type == "manager":
            title = "ショップ統括ロール設定"
        else:
            title = "お問い合わせ先メンション設定"
        super().__init__(title=title)
        self.bot = bot
        self.guild_id = guild_id
        self.role_type = role_type

        self.role_id = discord.ui.TextInput(
            label="ロールID",
            placeholder="IDを入力（複数指定時はスペースかカンマ区切り）",
            required=True
        )
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            raw_val = self.role_id.value.replace(",", " ").replace(";", " ")
            role_id_strs = raw_val.split()
            
            role_ids = []
            roles = []
            for rid_str in role_id_strs:
                try:
                    rid = int(rid_str)
                    role = interaction.guild.get_role(rid)
                    if role:
                        role_ids.append(rid)
                        roles.append(role)
                except ValueError:
                    pass
                    
            if not role_ids:
                return await interaction.response.send_message("有効なロールIDが入力されませんでした。", ephemeral=True)
            
            settings = await database.get_shop_settings(self.guild_id)
            emp_role_id = settings["employee_role_id"]
            mgr_role_id = settings["manager_role_id"]
            mention_role_ids = settings.get("inquiry_mention_role_ids") or []
            
            if self.role_type == "employee":
                emp_role_id = role_ids[0]
                role_str = roles[0].mention
            elif self.role_type == "manager":
                mgr_role_id = role_ids[0]
                role_str = roles[0].mention
            else:
                mention_role_ids = role_ids
                role_str = ", ".join([r.mention for r in roles])
                
            first_mention_role_id = mention_role_ids[0] if mention_role_ids else None
            await database.set_shop_settings(self.guild_id, emp_role_id, mgr_role_id, first_mention_role_id, mention_role_ids)
            role_type_ja = "従業員" if self.role_type == "employee" else ("統括" if self.role_type == "manager" else "お問い合わせ通知先メンション")
            await interaction.response.send_message(f"{role_type_ja}ロールを {role_str} に設定しました。", ephemeral=True)
            
            try:
                view = ShopSettingsConfigView(self.bot, self.guild_id)
                embed = await view.build_embed(interaction.guild)
                await interaction.message.edit(embed=embed, view=view)
            except:
                pass
                
        except ValueError:
            await interaction.response.send_message("IDは数値で入力してください。", ephemeral=True)

class ManageShopSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="ショップ設定",
            style=discord.ButtonStyle.secondary,
            emoji="🛒",
            custom_id="persistent_admin_manage_shop_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("権限がありません。", ephemeral=True)

        bot = interaction.client
        await update_shop_settings_config_view(interaction, bot)


class DowngradeGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="評価落ち", description="評価落ちに関するコマンド")
        self.bot = bot

    @app_commands.command(name="実行", description="【運営・評価員統括専用】指定したユーザーを評価落ちさせます")
    @app_commands.describe(target="対象メンバー", reason="評価落ちの理由")
    async def downgrade_execute(self, interaction: discord.Interaction, target: discord.Member, reason: str):
        if config.get_evaluator_tier(self.bot, interaction.user) < 3:
            return await interaction.response.send_message("このコマンドを実行する権限がありません（運営・評価員統括専用）。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        await trigger_evaluation_failure(interaction.guild, target, reason, interaction.user, self.bot)
        await interaction.followup.send(f"✅ {target.mention} を評価落ちさせました（理由: {reason}）。", ephemeral=True)

async def setup(bot):
    cog = AdminCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(DowngradeGroup(bot))

# --- ヘルパーと設定用ビュー ---

def format_setting_status(guild, key, bot=None):
    if bot is None:
        global _bot_instance
        bot = _bot_instance
    val = config.get_setting(bot, key)
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
            discord.SelectOption(label="💰 通貨・経済", value="economy", description="通貨の付与・送金・お渡し等のログ"),
            discord.SelectOption(label="👔 面接官ログ", value="interviewer", description="面接官の入界手続きなどのアクションログ"),
            discord.SelectOption(label="📉 評価落ちログ", value="evaluation_failure", description="評価落ちロール付与および通貨マイナス時のログ"),
            discord.SelectOption(label="🛒 ショップログ", value="shop", description="ショップの商品追加・編集・削除・購入ログ")
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
            "economy": "通貨・経済",
            "interviewer": "面接官ログ",
            "evaluation_failure": "評価落ちログ",
            "shop": "ショップログ"
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
        "economy": "💰 通貨・経済",
        "interviewer": "👔 面接官ログ",
        "evaluation_failure": "📉 評価落ちログ",
        "shop": "🛒 ショップログ"
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
            "economy": "💰 通貨・経済",
            "interviewer": "👔 面接官ログ",
            "evaluation_failure": "📉 評価落ちログ",
            "shop": "🛒 ショップログ"
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
        view = BotSetupMainView(interaction.user, interaction.client)
        embed = await view.build_embed(interaction.guild)
        await interaction.edit_original_response(embed=embed, view=view)

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

# --- 荒らし対策設定UIコンポーネント ---
class AntigriefCategorySelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="対象に追加するカテゴリー...", channel_types=[discord.ChannelType.category], min_values=1, max_values=1, row=0)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        cat = self.values[0]
        await database.update_antigrief_settings_list(interaction.guild.id, "categories", cat.id, "add")
        await bot.fetch_and_cache_antigrief_config(interaction.guild.id)
        await update_antigrief_settings_config_view(interaction, bot)

class AntigriefChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="対象に追加するチャンネル...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=1)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        chan = self.values[0]
        await database.update_antigrief_settings_list(interaction.guild.id, "channels", chan.id, "add")
        await bot.fetch_and_cache_antigrief_config(interaction.guild.id)
        await update_antigrief_settings_config_view(interaction, bot)

class AntigriefExemptRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="免除に追加するロール...", min_values=1, max_values=1, row=2)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        role = self.values[0]
        await database.update_antigrief_settings_list(interaction.guild.id, "exempt_roles", role.id, "add")
        await bot.fetch_and_cache_antigrief_config(interaction.guild.id)
        await update_antigrief_settings_config_view(interaction, bot)

class ClearAntigriefCategoriesButton(discord.ui.Button):
    def __init__(self): super().__init__(label="対象カテゴリ消去", style=discord.ButtonStyle.danger, row=3)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await database.clear_antigrief_settings_field(interaction.guild.id, "target_category_ids")
        await bot.fetch_and_cache_antigrief_config(interaction.guild.id)
        await update_antigrief_settings_config_view(interaction, bot)

class ClearAntigriefChannelsButton(discord.ui.Button):
    def __init__(self): super().__init__(label="対象チャンネル消去", style=discord.ButtonStyle.danger, row=3)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await database.clear_antigrief_settings_field(interaction.guild.id, "target_channel_ids")
        await bot.fetch_and_cache_antigrief_config(interaction.guild.id)
        await update_antigrief_settings_config_view(interaction, bot)

class ClearAntigriefExemptRolesButton(discord.ui.Button):
    def __init__(self): super().__init__(label="免除ロール消去", style=discord.ButtonStyle.danger, row=3)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await database.clear_antigrief_settings_field(interaction.guild.id, "exempt_role_ids")
        await bot.fetch_and_cache_antigrief_config(interaction.guild.id)
        await update_antigrief_settings_config_view(interaction, bot)

class AntigriefSettingsConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(AntigriefCategorySelect())
        self.add_item(AntigriefChannelSelect())
        self.add_item(AntigriefExemptRoleSelect())
        self.add_item(ClearAntigriefCategoriesButton())
        self.add_item(ClearAntigriefChannelsButton())
        self.add_item(ClearAntigriefExemptRolesButton())
        self.add_item(BackToAdminPanelButton(row=4))

async def update_antigrief_settings_config_view(interaction: discord.Interaction, bot):
    guild = interaction.guild
    cfg = await database.get_antigrief_settings(guild.id)
    embed = discord.Embed(
        title="⚙️ 荒らし対策 対象・免除設定",
        description="荒らし対策システムを適用する対象（カテゴリー/チャンネル）および免除するロールを設定します。\n"
                    "・対象を設定しない場合、**サーバー全体（すべてのチャンネル）が保護対象**となります。\n"
                    "・対象を設定した場合、設定されたカテゴリー/チャンネルのみで検知が有効化されます。\n"
                    "・免除ロールに指定されたメンバーは、検知チェックをバイパス（無視）します。",
        color=discord.Color.blue()
    )
    
    target_cats = [guild.get_channel(cid).name for cid in cfg.get("categories", []) if guild.get_channel(cid)]
    target_chs = [guild.get_channel(cid).mention for cid in cfg.get("channels", []) if guild.get_channel(cid)]
    exempt_roles = [guild.get_role(rid).mention for rid in cfg.get("exempt_roles", []) if guild.get_role(rid)]
    
    embed.add_field(name="対象カテゴリー", value=", ".join(target_cats) if target_cats else "サーバー全体 (全カテゴリー)", inline=False)
    embed.add_field(name="対象チャンネル", value=", ".join(target_chs) if target_chs else "サーバー全体 (全チャンネル)", inline=False)
    embed.add_field(name="免除ロール", value=", ".join(exempt_roles) if exempt_roles else "なし", inline=False)
    
    view = AntigriefSettingsConfigView()
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

class ManageAntigriefSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="荒らし対策を設定",
            style=discord.ButtonStyle.secondary,
            emoji="🚨",
            custom_id="persistent_admin_manage_antigrief_settings_btn"
        )

    async def callback(self, interaction: discord.Interaction):
        if not config.has_admin_role(interaction.client, interaction.user) and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)
        bot = interaction.client
        await update_antigrief_settings_config_view(interaction, bot)

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
    if "❌" in confession_priest_str: confession_priest_str = "名前一致: " + config.CONFESSION_PRIEST_ROLE_NAME
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

    # 荒らし対策設定
    antigrief_cfg = bot.get_antigrief_config(interaction.guild_id)
    ag_categories = [interaction.guild.get_channel(cid).name for cid in antigrief_cfg.get("categories", []) if interaction.guild.get_channel(cid)]
    ag_channels = [interaction.guild.get_channel(cid).mention for cid in antigrief_cfg.get("channels", []) if interaction.guild.get_channel(cid)]
    ag_exempt_roles = [interaction.guild.get_role(rid).mention for rid in antigrief_cfg.get("exempt_roles", []) if interaction.guild.get_role(rid)]
    
    target_scope = ""
    if not ag_categories and not ag_channels:
        target_scope = "サーバー全体 (すべてのチャンネルとカテゴリー)"
    else:
        scopes = []
        if ag_categories:
            scopes.append(f"対象カテゴリー: {', '.join(ag_categories)}")
        if ag_channels:
            scopes.append(f"対象チャンネル: {', '.join(ag_channels)}")
        target_scope = "\n".join(scopes)

    antigrief_text = (
        f"・適用対象:\n{target_scope}\n"
        f"・免除ロール: {', '.join(ag_exempt_roles) if ag_exempt_roles else 'なし'}"
    )
    embed.add_field(name="🚨 荒らし対策設定", value=antigrief_text, inline=False)

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
            discord.SelectOption(label="匿名チャット", description="匿名チャットのパネルを設置します", emoji="💬", value="anonymous_chat"),
            discord.SelectOption(label="カスタムチケット", description="任意のタイトル・説明文・担当ロールを指定したチケットパネルを設置します", emoji="🎫", value="custom_ticket"),
            discord.SelectOption(label="任意ロール", description="任意のロールをリアクションで付与するパネルを設置します", emoji="🎭", value="custom_role_panel"),
            discord.SelectOption(label="VC作成トリガー設定", description="VC作成トリガーの管理パネルを設置します", emoji="🎙️", value="vc_trigger"),
            discord.SelectOption(label="ショップ", description="ショップ機能のパネルを設置します", emoji="🛒", value="shop")
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
        elif val == "vc_trigger":
            embed = discord.Embed(
                title="🎙️ VC作成トリガー設定パネル",
                description=(
                    "ユーザーが参加した際に一時部屋を自動作成するチャンネルを設定できます。\n\n"
                    "下のボタンから設定メニューを開いてください。"
                ),
                color=discord.Color.blue()
            )
            await channel.send(embed=embed, view=VCTriggerPanelView())
            await interaction.response.send_message("✅ VC作成トリガー設定パネルを設置しました。", ephemeral=True)
        elif val == "anonymous_chat":
            view = AnonymousChatSetupView()
            await interaction.response.send_message("匿名チャットパネルの設定を行います。設置先と送信先のチャンネルをそれぞれ選択してください。", view=view, ephemeral=True)
        elif val == "shop":
            from cogs.shop import ShopPanelView
            embed = discord.Embed(
                title="🛒 ショップフロント",
                description="鯖内の通行証を買うことができる。\n気になることや何か問題等を発見した際にはお問い合わせボタンを押してください",
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=ShopPanelView(bot))
            await interaction.response.send_message("✅ ショップパネルを設置しました。", ephemeral=True)

class VCTriggerPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ManageVCTriggersButton())

class PanelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PanelSelect())


# --- Bot初期設定インタラクティブUI ---

class BotSetupMainSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👥 管理者ロール", value="ADMIN_ROLE_IDS", description="管理者のロールを設定します"),
            discord.SelectOption(label="👥 見習い・初級評価員", value="EVALUATOR_TIER1_ROLE_IDS", description="見習い・初級ランクの評価員ロール"),
            discord.SelectOption(label="👥 中級・上級評価員", value="EVALUATOR_TIER2_ROLE_IDS", description="中級・上級ランクの評価員ロール"),
            discord.SelectOption(label="👥 特級・統括評価員", value="EVALUATOR_TIER3_ROLE_IDS", description="特級・統括ランクの評価員ロール"),
            discord.SelectOption(label="👥 評価落ちロール", value="EVALUATION_FAILED_ROLE_ID", description="通貨マイナスなどで付与される評価落ちロール"),
            discord.SelectOption(label="👥 新規メンバーロール", value="NEW_MEMBER_ROLE_ID", description="入界後の一般メンバーロール"),
            discord.SelectOption(label="👥 入界待機者ロール", value="PENDING_MEMBER_ROLE_ID", description="面接待ちメンバーのロール"),
            discord.SelectOption(label="👥 面接官ロール", value="INTERVIEWER_ROLE_IDS", description="面接を行える権限ロール"),
            discord.SelectOption(label="👥 本・準メンバーロール", value="MAIN_SUB_MEMBER_ROLE_IDS", description="一般宿を無料・無制限で利用できる本・準メンバーのロール"),
            discord.SelectOption(label="👥 スタンプ統括ロール", value="EMBLEM_MANAGER_ROLE_ID", description="スタンプ制作を管理するロール"),
            discord.SelectOption(label="👥 スタンプ制作ロール", value="EMBLEM_MASTER_ROLE_ID", description="スタンプを制作するロール"),
            discord.SelectOption(label="👥 告解司祭ロール", value="CONFESSION_PRIEST_ROLE_ID", description="告解を対応する司祭ロール"),
            discord.SelectOption(label="👥 司祭ロール", value="PRIEST_ROLE_ID", description="相談を対応する司祭ロール"),
            discord.SelectOption(label="👥 イベント管理ロール", value="EVENT_MANAGER_ROLE_IDS", description="イベント登録・編集・削除ができるロール"),
            discord.SelectOption(label="👥 通貨マイナス落ち対象ロール", value="MINUS_TARGET_ROLE_IDS", description="通貨マイナスで評価落ちさせる対象ロールを設定します"),
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

class ManageGambleSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🎰 ギャンブル設定", style=discord.ButtonStyle.secondary, custom_id="admin_manage_gamble_btn")

    async def callback(self, interaction: discord.Interaction):
        from cogs.gambling import GambleSettingsView
        view = GambleSettingsView(interaction.user)
        embed = await view.build_embed(interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)

class BotSetupMainView(discord.ui.View):
    def __init__(self, user, bot=None):
        super().__init__(timeout=300)
        self.user = user
        if bot is None:
            global _bot_instance
            bot = _bot_instance
        self.bot = bot
        
        self.add_item(BotSetupMainSelect())
        
        btn_log = ManageLogSettingsButton()
        btn_log.row = 1
        self.add_item(btn_log)
        
        btn_rank = ManageRankSettingsButton()
        btn_rank.row = 1
        self.add_item(btn_rank)
        
        btn_level = ManageLevelRolesButton()
        btn_level.row = 1
        self.add_item(btn_level)
        
        btn_price = ManageRoomPricesButton()
        btn_price.row = 1
        self.add_item(btn_price)
        
        btn_vc = ManageVCTriggersButton()
        btn_vc.row = 2
        self.add_item(btn_vc)
        
        btn_eval = ManageEvaluationSettingsButton()
        btn_eval.row = 2
        self.add_item(btn_eval)
        
        btn_antigrief = ManageAntigriefSettingsButton()
        btn_antigrief.row = 2
        self.add_item(btn_antigrief)

        
        btn_shop = ManageShopSettingsButton()
        btn_shop.row = 3
        self.add_item(btn_shop)

        btn_gamble = ManageGambleSettingsButton()
        btn_gamble.row = 3
        self.add_item(btn_gamble)

    async def build_embed(self, guild):
        bot = self.bot
        log_settings = await database.get_all_log_settings(guild.id)
        level_rewards = await database.get_level_role_rewards()
        room_prices = await database.get_all_room_prices()
        
        embed = discord.Embed(
            title="⚙️ ０番区bot 管理パネル",
            description="Botの設定状況を確認・変更できます。下のセレクトメニューやボタンから項目を選択してください。",
            color=discord.Color.blue()
        )
        
        roles_text = (
            f"・管理者ロール: {format_setting_status(guild, 'ADMIN_ROLE_IDS', bot)}\n"
            f"・仮(新規)メンバーロール: {format_setting_status(guild, 'NEW_MEMBER_ROLE_ID', bot)}\n"
            f"・入界待機者ロール: {format_setting_status(guild, 'PENDING_MEMBER_ROLE_ID', bot)}\n"
            f"・本/準メンバーロール: {format_setting_status(guild, 'MAIN_SUB_MEMBER_ROLE_IDS', bot)}\n"
            f"・通貨マイナス落ち対象ロール: {format_setting_status(guild, 'MINUS_TARGET_ROLE_IDS', bot)}\n"
            f"・面接官ロール: {format_setting_status(guild, 'INTERVIEWER_ROLE_IDS', bot)}\n"
        )
        embed.add_field(name="👥 基本・管理権限設定", value=roles_text, inline=False)
        
        other_roles_text = (
            f"・評価落ちロール: {format_setting_status(guild, 'EVALUATION_FAILED_ROLE_ID', bot)}\n"
            f"・見習い・初級評価員ロール: {format_setting_status(guild, 'EVALUATOR_TIER1_ROLE_IDS', bot)}\n"
            f"・中級・上級評価員ロール: {format_setting_status(guild, 'EVALUATOR_TIER2_ROLE_IDS', bot)}\n"
            f"・特級・統括評価員ロール: {format_setting_status(guild, 'EVALUATOR_TIER3_ROLE_IDS', bot)}\n"
            f"・スタンプ統括ロール: {format_setting_status(guild, 'EMBLEM_MANAGER_ROLE_ID', bot)}\n"
            f"・スタンプ制作ロール: {format_setting_status(guild, 'EMBLEM_MASTER_ROLE_ID', bot)}\n"
            f"・告解司祭 / 司祭ロール: {format_setting_status(guild, 'CONFESSION_PRIEST_ROLE_ID', bot)} / {format_setting_status(guild, 'PRIEST_ROLE_ID', bot)}\n"
            f"・イベント管理ロール: {format_setting_status(guild, 'EVENT_MANAGER_ROLE_IDS', bot)}\n"
        )
        embed.add_field(name="🏷️ その他役職・役割ロール設定", value=other_roles_text, inline=False)
        
        log_names = {
            "message_edit": "メッセージ編集",
            "message_delete": "メッセージ削除",
            "vc_join_leave": "VC参加・退出",
            "member_join_leave": "メンバー入退",
            "economy": "通貨・経済",
            "interviewer": "面接官ログ"
        }
        log_text = ""
        for log_type, ch_id in log_settings.items():
            ch = guild.get_channel(ch_id)
            mention = ch.mention if ch else f"未取得 (ID: {ch_id})"
            log_text += f"・{log_names.get(log_type, log_type)} ➔ {mention}\n"
        embed.add_field(name="📝 ログ出力設定", value=log_text or "設定されているログ出力はありません。", inline=False)
        
        rank_cfg = bot.get_rank_config(guild.id)
        wl_ch = [guild.get_channel(cid).mention for cid in rank_cfg.get("whitelist", []) if guild.get_channel(cid)]
        wl_cat = [guild.get_channel(cid).name for cid in rank_cfg.get("whitelist_categories", []) if guild.get_channel(cid)]
        bl_ch = [guild.get_channel(cid).mention for cid in rank_cfg.get("blacklist", []) if guild.get_channel(cid)]
        bl_cat = [guild.get_channel(cid).name for cid in rank_cfg.get("blacklist_categories", []) if guild.get_channel(cid)]
        rank_text = (
            f"・WL(対象)チャンネル: {', '.join(wl_ch) if wl_ch else 'なし'}\n"
            f"・WL(対象)カテゴリー: {', '.join(wl_cat) if wl_cat else 'なし'}\n"
            f"・BL(除外)チャンネル: {', '.join(bl_ch) if bl_ch else 'なし'}\n"
            f"・BL(除外)カテゴリー: {', '.join(bl_cat) if bl_cat else 'なし'}\n"
        )
        embed.add_field(name="🏆 ランク対象設定", value=rank_text, inline=False)
        
        tc_rewards = [r for r in level_rewards if r["level_type"] == "tc"]
        vc_rewards = [r for r in level_rewards if r["level_type"] == "vc"]
        level_text = "**[💬 テキスト (TC)]**\n"
        for r in sorted(tc_rewards, key=lambda x: x["level"]):
            role = guild.get_role(r["role_id"])
            mention = role.mention if role else f"未取得 (ID: {r['role_id']})"
            level_text += f" ・Lv.{r['level']} ➔ {mention}\n"
        if not tc_rewards: level_text += " ・設定なし\n"
        
        level_text += "**[🎙️ ボイス (VC)]**\n"
        for r in sorted(vc_rewards, key=lambda x: x["level"]):
            role = guild.get_role(r["role_id"])
            mention = role.mention if role else f"未取得 (ID: {r['role_id']})"
            level_text += f" ・Lv.{r['level']} ➔ {mention}\n"
        if not vc_rewards: level_text += " ・設定なし\n"
        embed.add_field(name="🎁 レベル到達ロール報酬設定", value=level_text, inline=False)
        
        cur_name = config.CURRENCY_NAME
        init_coins = config.INITIAL_COINS
        prices_text = (
            f"・通貨単位名: **{cur_name}**\n"
            f"・新規入界時発行額: **{init_coins:,} {cur_name}**\n"
        )
        for p in room_prices:
            prices_text += f"・{p['room_type']} ({p['duration']}時間) ➔ **{p['price']:,} {cur_name}**\n"
        embed.add_field(name="💰 経済・部屋価格設定", value=prices_text, inline=False)
        
        from cogs.gambling import get_win_rate_str
        chinchiro_exp = config.get_setting(bot, "GAMBLE_CHINCHIRO_EXPECTATION")
        if chinchiro_exp is None: chinchiro_exp = 0.95
        coinflip_exp = config.get_setting(bot, "GAMBLE_COINFLIP_EXPECTATION")
        if coinflip_exp is None: coinflip_exp = 0.95
        slot_exp = config.get_setting(bot, "GAMBLE_SLOT_EXPECTATION")
        if slot_exp is None: slot_exp = 0.95
        blackjack_exp = config.get_setting(bot, "GAMBLE_BLACKJACK_EXPECTATION")
        if blackjack_exp is None: blackjack_exp = 0.95
        roulette_exp = config.get_setting(bot, "GAMBLE_ROULETTE_EXPECTATION")
        if roulette_exp is None: roulette_exp = 0.95
        
        gamble_text = (
            f"・チンチロリン期待値: **{chinchiro_exp}**\n  ({get_win_rate_str('chinchiro', chinchiro_exp)})\n"
            f"・コイントス期待値: **{coinflip_exp}**\n  ({get_win_rate_str('coinflip', coinflip_exp)})\n"
            f"・スロット期待値: **{slot_exp}**\n  ({get_win_rate_str('slot', slot_exp)})\n"
            f"・ブラックジャック期待値: **{blackjack_exp}**\n  ({get_win_rate_str('blackjack', blackjack_exp)})\n"
            f"・ルーレット期待値: **{roulette_exp}**\n  ({get_win_rate_str('roulette', roulette_exp)})\n"
        )
        embed.add_field(name="🎰 ギャンブル期待値設定", value=gamble_text, inline=False)
        
        trigger_text = ""
        for tid in bot.auto_vc_triggers:
            ch = guild.get_channel(tid)
            mention = ch.mention if ch else f"未取得 (ID: {tid})"
            trigger_text += f"・{mention}\n"
        embed.add_field(name=f"🔊 自動VCトリガー設定 (登録数: {len(bot.auto_vc_triggers)}個)", value=trigger_text or "登録されているトリガーはありません。", inline=False)
        
        eval_cfg = bot.get_evaluation_config(guild.id)
        forums = [guild.get_channel(fid).mention for fid in eval_cfg["forum_channel_ids"] if guild.get_channel(fid)]
        intros = [guild.get_channel(cid).mention for cid in eval_cfg["self_intro_channel_ids"] if guild.get_channel(cid)]
        eval_text = (
            f"・評価フォーラム: {', '.join(forums) if forums else 'なし'}\n"
            f"・対象自己紹介チャンネル: {', '.join(intros) if intros else 'なし'}\n"
        )
        embed.add_field(name="📋 自己紹介・評価設定", value=eval_text, inline=False)
        
        antigrief_cfg = bot.get_antigrief_config(guild.id)
        ag_categories = [guild.get_channel(cid).name for cid in antigrief_cfg.get("categories", []) if guild.get_channel(cid)]
        ag_channels = [guild.get_channel(cid).mention for cid in antigrief_cfg.get("channels", []) if guild.get_channel(cid)]
        ag_exempt_roles = [guild.get_role(rid).mention for rid in antigrief_cfg.get("exempt_roles", []) if guild.get_role(rid)]
        
        target_scope = ""
        if not ag_categories and not ag_channels:
            target_scope = "サーバー全体 (すべてのチャンネルとカテゴリー)"
        else:
            scopes = []
            if ag_categories:
                scopes.append(f"対象カテゴリー: {', '.join(ag_categories)}")
            if ag_channels:
                scopes.append(f"対象チャンネル: {', '.join(ag_channels)}")
            target_scope = "\n".join(scopes)

        antigrief_text = (
            f"・適用対象:\n{target_scope}\n"
            f"・免除ロール: {', '.join(ag_exempt_roles) if ag_exempt_roles else 'なし'}"
        )
        embed.add_field(name="🚨 荒らし対策設定", value=antigrief_text, inline=False)
        
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
        await interaction.response.defer()
        view = BotSetupMainView(self.user, interaction.client)
        embed = await view.build_embed(interaction.guild)
        await interaction.edit_original_response(embed=embed, view=view)

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
