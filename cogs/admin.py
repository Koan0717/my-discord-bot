import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio
import database
from helpers import (
    JST, get_setting, get_role_by_setting, has_admin_role, is_admin, is_admin_or_interviewer, send_log,
    NEW_MEMBER_ROLE_NAME, INTERVIEWER_ROLE_NAMES, FREE_INN_ROLE_NAMES,
    EMBLEM_MANAGER_ROLE_NAME, EMBLEM_MASTER_ROLE_NAME, CONFESSION_PRIEST_ROLE_NAME,
    PRIEST_ROLE_NAME, ADMIN_ROLE_NAMES, EVALUATOR_ROLE_NAMES, DEFAULT_SETTINGS,
    format_setting_status, circled_to_int, get_circled_number
)
# 注意: bot.pyの245行目あたりにあった bot_settings や triggers のキャッシュは bot 側にある。

# --- UIクラス (ヘルパーのダミーインポート等も利用) ---
# 他のUIインポートや定義
from cogs.rooms import VCRenamePanelView, RoomView, CustomRoomView, LuxuryRoomView
from cogs.gambling import ChinchiroView, CoinflipView, SlotView, BlackjackView, RouletteView
from cogs.interview import InterviewPanelView
from cogs.utility import EmblemRequestPanelView, ConfessionRequestPanelView, InquiryRequestPanelView, AnonymousChatPanelView, CustomTicketPanelView

# --- コア設定パネル更新関数 ---
async def create_admin_panel_embed(bot, guild: discord.Guild) -> discord.Embed:
    import asyncio
    # データベースから設定項目を非同期ロード
    log_chans_task = database.get_all_log_settings(guild.id)
    rank_settings_task = database.get_rank_settings(guild.id)
    level_rewards_task = database.get_level_role_rewards()
    room_prices_task = database.get_all_room_prices()
    vc_triggers_task = database.get_auto_vc_triggers()
    eval_settings_task = database.get_evaluation_settings(guild.id)
    role_room_prices_task = database.get_all_role_room_prices()
    
    log_chans_dict, rank_settings, level_rewards, room_prices, vc_triggers, eval_settings, role_room_prices = await asyncio.gather(
        log_chans_task, rank_settings_task, level_rewards_task, room_prices_task, vc_triggers_task, eval_settings_task, role_room_prices_task
    )
    
    log_chans = [{"log_type": k, "channel_id": v} for k, v in log_chans_dict.items()]
    
    embed = discord.Embed(
        title="⚙️ ０番区bot 管理パネル",
        description="Botの設定状況を確認・変更できます。下のセレクトメニューやボタンから項目を選択してください。",
        color=discord.Color.blue()
    )
    
    # helpersからインポートした format_setting_status などの定義
    from helpers import format_setting_status
    
    lv_status = format_setting_status(bot, guild, "LEVEL_UP_CHANNEL_ID")
    eval_cat_status = format_setting_status(bot, guild, "EVALUATION_CATEGORY_ID")
    new_mem_status = format_setting_status(bot, guild, "NEW_MEMBER_ROLE_ID")
    downgrade_role_status = format_setting_status(bot, guild, "DOWNGRADE_ROLE_ID")
    pending_mem_status = format_setting_status(bot, guild, "PENDING_MEMBER_ROLE_ID")
    admin_status = format_setting_status(bot, guild, "ADMIN_ROLE_IDS")
    interviewer_status = format_setting_status(bot, guild, "INTERVIEWER_ROLE_IDS")
    free_inn_status = format_setting_status(bot, guild, "FREE_INN_ROLE_IDS")
    main_sub_status = format_setting_status(bot, guild, "MAIN_SUB_MEMBER_ROLE_IDS")
    
    emblem_manager_status = format_setting_status(bot, guild, "EMBLEM_MANAGER_ROLE_ID")
    emblem_master_status = format_setting_status(bot, guild, "EMBLEM_MASTER_ROLE_ID")
    confession_status = format_setting_status(bot, guild, "CONFESSION_PRIEST_ROLE_ID")
    priest_status = format_setting_status(bot, guild, "PRIEST_ROLE_ID")
    event_manager_status = format_setting_status(bot, guild, "EVENT_MANAGER_ROLE_IDS")
    gamble_employee_status = format_setting_status(bot, guild, "GAMBLE_EMPLOYEE_ROLE_IDS")
    
    evaluator_status = format_setting_status(bot, guild, "EVALUATOR_ROLE_IDS")
    evaluator2_status = format_setting_status(bot, guild, "EVALUATOR_TIER2_ROLE_IDS")
    evaluator3_status = format_setting_status(bot, guild, "EVALUATOR_TIER3_ROLE_IDS")
    
    basic_text = (
        f"・レベルアップ通知: {lv_status}\n"
        f"・評価対象カテゴリー: **{eval_cat_status}**\n"
        f"・仮(新規)メンバーロール: {new_mem_status}\n"
        f"・評価落ちロール: {downgrade_role_status}\n"
        f"・入界待機者ロール: {pending_mem_status}\n"
        f"・本/準メンバーロール: {main_sub_status}\n"
        f"・運営管理者ロール: {admin_status}\n"
        f"・面接官ロール: {interviewer_status}\n"
        f"・無料宿ロール: {free_inn_status}\n"
    )
    embed.add_field(name="👥 基本・管理権限設定", value=basic_text, inline=False)
    
    other_roles_text = (
        f"・初級評価員ロール: {evaluator_status}\n"
        f"・中級評価員ロール: {evaluator2_status}\n"
        f"・上級評価員ロール: {evaluator3_status}\n"
        f"・スタンプ統括ロール: {emblem_manager_status}\n"
        f"・スタンプ制作ロール: {emblem_master_status}\n"
        f"・告解司祭 / 司祭ロール: {confession_status} / {priest_status}\n"
        f"・イベント管理ロール: {event_manager_status}\n"
        f"・賭博従業員ロール: {gamble_employee_status}\n"
    )
    embed.add_field(name="🏷️ その他役職・役割ロール設定", value=other_roles_text, inline=False)
    
    # 2. ログ設定
    log_names = {
        "message_edit_delete": "メッセージ編集・削除",
        "member_join_leave": "入退室ログ",
        "vc_join_leave": "VC入退室",
        "currency": "通貨ログ",
        "gambling": "ギャンブルログ",
        "interviewer": "面接官ログ"
    }
    log_text = ""
    for s in log_chans:
        chan = bot.get_channel(s["channel_id"])
        mention = chan.mention if chan else f"未取得 (ID: {s['channel_id']})"
        log_text += f"・{log_names.get(s['log_type'], s['log_type'])} ➔ {mention}\n"
    embed.add_field(name="📝 ログ出力設定", value=log_text or "設定されているログ出力はありません。", inline=False)
    
    # 3. ランク除外設定
    wl_ch = [guild.get_channel(cid).mention for cid in rank_settings.get("whitelist", []) if guild.get_channel(cid)]
    wl_cat = [guild.get_channel(cid).name for cid in rank_settings.get("categories", []) if guild.get_channel(cid)]
    bl_ch = [guild.get_channel(cid).mention for cid in rank_settings.get("blacklist", []) if guild.get_channel(cid)]
    bl_cat = [guild.get_channel(cid).name for cid in rank_settings.get("blacklist_categories", []) if guild.get_channel(cid)]
    rank_text = (
        f"・WL(対象)チャンネル: {', '.join(wl_ch) if wl_ch else 'なし'}\n"
        f"・WL(対象)カテゴリー: {', '.join(wl_cat) if wl_cat else 'なし'}\n"
        f"・BL(除外)チャンネル: {', '.join(bl_ch) if bl_ch else 'なし'}\n"
        f"・BL(除外)カテゴリー: {', '.join(bl_cat) if bl_cat else 'なし'}\n"
    )
    embed.add_field(name="🏆 ランク対象チャンネル設定", value=rank_text, inline=False)
    
    # 4. レベルロール設定
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
    
    # 5. 経済＆部屋価格設定
    cur_name = get_setting(bot, "CURRENCY_NAME") or "コイン"
    init_coins = get_setting(bot, "INITIAL_COINS") or 30000
    prices_text = (
        f"・通貨単位名: **{cur_name}**\n"
        f"・新規入界時発行額: **{init_coins:,} {cur_name}**\n"
    )
    for p in room_prices:
        prices_text += f"・{p['room_type']} ({p['duration']}時間) ➔ **{p['price']:,} {cur_name}**\n"
    
    if role_room_prices:
        role_key_names = {
            "DOWNGRADE_ROLE": "評価落ち",
            "NEW_MEMBER_ROLE": "仮メンバー"
        }
        prices_text += "**[ロール別特別価格]**\n"
        for rp in role_room_prices:
            role_label = role_key_names.get(rp["role_key"], rp["role_key"])
            prices_text += f" ・{role_label}用 {rp['room_type']} ({rp['duration']}時間) ➔ **{rp['price']:,} {cur_name}**\n"
            
    embed.add_field(name="💰 経済・部屋価格設定", value=prices_text, inline=False)
    
    # 6. 自動VCトリガー設定
    trigger_text = ""
    for tid in vc_triggers:
        ch = bot.get_channel(tid)
        mention = ch.mention if ch else f"未取得 (ID: {tid})"
        cfg = bot.auto_vc_configs.get(tid, {})
        base = cfg.get("base_name") or "（デフォルト）"
        trigger_text += f"・{mention} [ベース名: {base}]\n"
    embed.add_field(name=f"🔊 自動VCトリガー設定 (登録数: {len(vc_triggers)}個)", value=trigger_text or "登録されているトリガーはありません。", inline=False)
    
    # 7. 自己紹介評価設定
    forums = [bot.get_channel(fid).mention for fid in eval_settings["forum_channel_ids"] if bot.get_channel(fid)]
    intros = [bot.get_channel(cid).mention for cid in eval_settings["self_intro_channel_ids"] if bot.get_channel(cid)]
    eval_text = (
        f"・評価フォーラム: {', '.join(forums) if forums else 'なし'}\n"
        f"・対象自己紹介チャンネル: {', '.join(intros) if intros else 'なし'}\n"
    )
    embed.add_field(name="📝 自己紹介評価設定", value=eval_text, inline=False)
    
    return embed

async def update_main_admin_panel(interaction: discord.Interaction):
    bot = interaction.client
    guild = interaction.guild
    embed = await create_admin_panel_embed(bot, guild)
    view = BotSetupMainView()
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

# --- 永続Views & Modals (管理者設定用) ---
class EconomySettingsModal(discord.ui.Modal, title='経済設定の変更'):
    def __init__(self):
        super().__init__()
        self.cur_name = discord.ui.TextInput(label='通貨名 (デフォルト: コイン)', default='コイン', max_length=10, required=True)
        self.init_coins = discord.ui.TextInput(label='新規登録時の発行額', default='30000', max_length=9, required=True)
        self.add_item(self.cur_name)
        self.add_item(self.init_coins)
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bot = interaction.client
            coins = int(self.init_coins.value)
            if coins < 0: raise ValueError
            
            await database.save_setting("CURRENCY_NAME", self.cur_name.value)
            await database.save_setting("INITIAL_COINS", coins)
            
            bot.bot_settings["CURRENCY_NAME"] = self.cur_name.value
            bot.bot_settings["INITIAL_COINS"] = coins
            
            await interaction.response.send_message("✅ 経済設定を更新しました！", ephemeral=True)
            await update_main_admin_panel(interaction)
        except:
            await interaction.response.send_message("正の整数を入力してください。", ephemeral=True)

class ManageEconomySettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="経済設定変更", style=discord.ButtonStyle.secondary, row=2)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EconomySettingsModal())

class LogTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="メッセージ編集・削除", value="message_edit_delete", description="メッセージの編集・削除ログ"),
            discord.SelectOption(label="入退室ログ", value="member_join_leave", description="メンバーのサーバー参加・退出ログ"),
            discord.SelectOption(label="VC入退室", value="vc_join_leave", description="ボイスチャンネルの接続・切断・移動ログ"),
            discord.SelectOption(label="通貨ログ", value="currency", description="通貨の送金や給与などのログ"),
            discord.SelectOption(label="ギャンブルログ", value="gambling", description="ギャンブルの勝敗や配当などのログ"),
            discord.SelectOption(label="面接官ログ", value="interviewer", description="面接官の入界許可などのアクションログ")
        ]
        super().__init__(placeholder="ログ種別を選択...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_log_type = self.values[0]
        await interaction.response.defer(ephemeral=True)

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="送信先チャンネルを選択...", channel_types=[discord.ChannelType.text], row=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_channel = self.values[0]
        await interaction.response.defer(ephemeral=True)

class SaveLogSettingButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="設定を保存", style=discord.ButtonStyle.success, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not view.selected_log_type or not view.selected_channel:
            return await interaction.response.send_message("❌ ログ種別とチャンネルを両方選択してください。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        await database.save_log_channel(interaction.guild.id, view.selected_log_type, view.selected_channel.id)
        
        # ログ種別の日本語化
        log_names = {
            "message_edit_delete": "メッセージ編集・削除",
            "member_join_leave": "入退室ログ",
            "vc_join_leave": "VC入退室",
            "currency": "通貨ログ",
            "gambling": "ギャンブルログ",
            "interviewer": "面接官ログ"
        }
        name = log_names.get(view.selected_log_type, view.selected_log_type)
        
        await update_log_settings_config_view(interaction)
        await interaction.followup.send(f"✅ 「{name}」の送信先を {view.selected_channel.mention} に設定しました。", ephemeral=True)

class RemoveLogSettingSelect(discord.ui.Select):
    def __init__(self, active_settings):
        log_names = {
            "message_edit_delete": "メッセージ編集・削除",
            "member_join_leave": "入退室ログ",
            "vc_join_leave": "VC入退室",
            "currency": "通貨ログ",
            "gambling": "ギャンブルログ",
            "interviewer": "面接官ログ"
        }
        options = [
            discord.SelectOption(label=f"削除: {log_names.get(s, s)}", value=s)
            for s in active_settings
        ]
        super().__init__(placeholder="設定を削除するログ種別を選択...", options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        log_type = self.values[0]
        await database.remove_log_channel(interaction.guild.id, log_type)
        await update_log_settings_config_view(interaction)
        await interaction.followup.send("✅ ログ設定を解除しました。", ephemeral=True)

class LogSettingsConfigView(discord.ui.View):
    def __init__(self, settings=None):
        super().__init__(timeout=180)
        self.selected_log_type = None
        self.selected_channel = None
        self.add_item(LogTypeSelect())
        self.add_item(LogChannelSelect())
        self.add_item(SaveLogSettingButton())
        
        if settings:
            active_log_types = [s["log_type"] for s in settings]
            self.add_item(RemoveLogSettingSelect(active_log_types))
            
        self.add_item(BackToAdminPanelButton(row=4))

async def update_log_settings_config_view(interaction: discord.Interaction):
    bot = interaction.client
    guild = interaction.guild
    raw_settings = await database.get_all_log_settings(guild.id)
    settings = [{"log_type": k, "channel_id": v} for k, v in raw_settings.items()]
    embed = discord.Embed(title="⚙️ ログ出力設定", description="各種イベントの通知用ログチャンネルを設定します。", color=discord.Color.blue())
    
    log_names = {
        "message_edit": "メッセージ編集",
        "message_delete": "メッセージ削除",
        "message_edit_delete": "メッセージ編集・削除",
        "member_join_leave": "入退室ログ",
        "vc_join_leave": "VC入退室",
        "currency": "通貨ログ",
        "gambling": "ギャンブルログ",
        "interviewer": "面接官ログ"
    }
    
    status_text = ""
    for s in settings:
        chan = bot.get_channel(s["channel_id"])
        mention = chan.mention if chan else f"未取得 (ID: {s['channel_id']})"
        status_text += f"・{log_names.get(s['log_type'], s['log_type'])} ➔ {mention}\n"
        
    if not status_text:
        status_text = "設定されているログ出力はありません。"
        
    embed.add_field(name="現在の設定一覧", value=status_text, inline=False)
    view = LogSettingsConfigView(settings)
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

class ManageLogSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="ログ設定管理", style=discord.ButtonStyle.primary, row=1)
    async def callback(self, interaction: discord.Interaction):
        await update_log_settings_config_view(interaction)

# --- ランク除外設定 ---
class WhitelistChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="ホワイトリストに追加するチャンネル...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=0)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        chan = self.values[0]
        await database.update_rank_settings_list(interaction.guild.id, "whitelist_channels", chan.id, "add")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class WhitelistCategorySelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="ホワイトリストに追加するカテゴリー...", channel_types=[discord.ChannelType.category], min_values=1, max_values=1, row=1)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        cat = self.values[0]
        await database.update_rank_settings_list(interaction.guild.id, "whitelist_categories", cat.id, "add")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class BlacklistChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="ブラックリストに追加するチャンネル...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=2)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        chan = self.values[0]
        await database.update_rank_settings_list(interaction.guild.id, "blacklist_channels", chan.id, "add")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class BlacklistCategorySelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="ブラックリストに追加するカテゴリー...", channel_types=[discord.ChannelType.category], min_values=1, max_values=1, row=3)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        cat = self.values[0]
        await database.update_rank_settings_list(interaction.guild.id, "blacklist_categories", cat.id, "add")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class ClearWhitelistCHButton(discord.ui.Button):
    def __init__(self): super().__init__(label="WLチャンネル消去", style=discord.ButtonStyle.danger, row=4)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await database.clear_rank_settings_field(interaction.guild.id, "whitelist_channel_ids")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class ClearWhitelistCatButton(discord.ui.Button):
    def __init__(self): super().__init__(label="WLカテゴリ消去", style=discord.ButtonStyle.danger, row=4)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await database.clear_rank_settings_field(interaction.guild.id, "whitelist_category_ids")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class ClearBlacklistCHButton(discord.ui.Button):
    def __init__(self): super().__init__(label="BLチャンネル消去", style=discord.ButtonStyle.danger, row=4)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await database.clear_rank_settings_field(interaction.guild.id, "blacklist_channel_ids")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class ClearBlacklistCatButton(discord.ui.Button):
    def __init__(self): super().__init__(label="BLカテゴリ消去", style=discord.ButtonStyle.danger, row=4)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        await database.clear_rank_settings_field(interaction.guild.id, "blacklist_category_ids")
        await bot.fetch_and_cache_rank_config(interaction.guild.id)
        await update_rank_settings_config_view(interaction)

class RankSettingsConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(WhitelistChannelSelect())
        self.add_item(WhitelistCategorySelect())
        self.add_item(BlacklistChannelSelect())
        self.add_item(BlacklistCategorySelect())
        self.add_item(ClearWhitelistCHButton())
        self.add_item(ClearWhitelistCatButton())
        self.add_item(ClearBlacklistCHButton())
        self.add_item(ClearBlacklistCatButton())
        self.add_item(BackToAdminPanelButton(row=4))

async def update_rank_settings_config_view(interaction: discord.Interaction):
    bot = interaction.client
    guild = interaction.guild
    cfg = await database.get_rank_settings(guild.id)
    embed = discord.Embed(
        title="⚙️ ランク対象チャンネル設定",
        description="XP獲得が有効なチャンネルをカテゴリーまたは個別チャンネルで制御します。\n"
                    "・ホワイトリスト(WL)が設定されている場合、WLのみが対象になります。\n"
                    "・ブラックリスト(BL)が設定されている場合、BLは除外されます。",
        color=discord.Color.blue()
    )
    
    wl_ch = [guild.get_channel(cid).mention for cid in cfg.get("whitelist", []) if guild.get_channel(cid)]
    wl_cat = [guild.get_channel(cid).name for cid in cfg.get("categories", []) if guild.get_channel(cid)]
    bl_ch = [guild.get_channel(cid).mention for cid in cfg.get("blacklist", []) if guild.get_channel(cid)]
    bl_cat = [guild.get_channel(cid).name for cid in cfg.get("blacklist_categories", []) if guild.get_channel(cid)]
    
    embed.add_field(name="WL（対象）チャンネル", value=", ".join(wl_ch) if wl_ch else "なし", inline=False)
    embed.add_field(name="WL（対象）カテゴリー", value=", ".join(wl_cat) if wl_cat else "なし", inline=False)
    embed.add_field(name="BL（除外）チャンネル", value=", ".join(bl_ch) if bl_ch else "なし", inline=False)
    embed.add_field(name="BL（除外）カテゴリー", value=", ".join(bl_cat) if bl_cat else "なし", inline=False)
    
    view = RankSettingsConfigView()
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

class ManageRankSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="ランク対象設定", style=discord.ButtonStyle.primary, row=1)
    async def callback(self, interaction: discord.Interaction):
        await update_rank_settings_config_view(interaction)

# --- レベル到達ロール設定 ---
class LevelTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="テキスト (TC) レベル報酬", value="tc"),
            discord.SelectOption(label="ボイス (VC) レベル報酬", value="vc")
        ]
        super().__init__(placeholder="レベル種別を選択...", options=options, row=0)
    async def callback(self, interaction: discord.Interaction):
        self.view.level_type = self.values[0]
        await interaction.response.defer(ephemeral=True)

class LevelRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="付与するロールを選択...", min_values=1, max_values=1, row=1)
    async def callback(self, interaction: discord.Interaction):
        self.view.role = self.values[0]
        await interaction.response.defer(ephemeral=True)

class LevelInputModal(discord.ui.Modal, title='必要レベルの入力'):
    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref
        self.level_input = discord.ui.TextInput(label='必要レベル (正の整数)', placeholder='例: 5', max_length=4, required=True)
        self.add_item(self.level_input)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.level_input.value)
            if val <= 0: raise ValueError
            await database.add_level_role_reward(self.view_ref.level_type, val, self.view_ref.role.id)
            await interaction.response.send_message(f"✅ 設定しました: {self.view_ref.level_type.upper()} Lv.{val} ➔ {self.view_ref.role.mention}", ephemeral=True)
            await update_level_roles_config_view(interaction)
        except:
            await interaction.response.send_message("正の整数を入力してください。", ephemeral=True)

class AddLevelRoleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="レベルを決定して追加", style=discord.ButtonStyle.success, row=2)
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not view.level_type or not view.role:
            return await interaction.response.send_message("レベル種別とロールを選択してください。", ephemeral=True)
        await interaction.response.send_modal(LevelInputModal(view))

class RemoveLevelRoleSelect(discord.ui.Select):
    def __init__(self, rewards, guild):
        options = []
        for r in rewards:
            role = guild.get_role(r["role_id"])
            role_name = role.name if role else f"不明 (ID: {r['role_id']})"
            options.append(discord.SelectOption(
                label=f"削除: {r['level_type'].upper()} Lv.{r['level']} ➔ {role_name}",
                value=f"{r['level_type']}:{r['level']}:{r['role_id']}"
            ))
        super().__init__(placeholder="削除する報酬設定を選択...", options=options, row=3)
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        parts = self.values[0].split(":")
        ltype, level, rid = parts[0], int(parts[1]), int(parts[2])
        await database.remove_level_role_reward(ltype, level, rid)
        await update_level_roles_config_view(interaction)
        await interaction.followup.send("✅ 報酬設定を削除しました。", ephemeral=True)

class LevelRolesConfigView(discord.ui.View):
    def __init__(self, rewards=None, guild=None):
        super().__init__(timeout=180)
        self.level_type = None
        self.role = None
        self.add_item(LevelTypeSelect())
        self.add_item(LevelRoleSelect())
        self.add_item(AddLevelRoleButton())
        
        if rewards and guild:
            self.add_item(RemoveLevelRoleSelect(rewards[:25], guild))
            
        self.add_item(BackToAdminPanelButton(row=4))

async def update_level_roles_config_view(interaction: discord.Interaction):
    guild = interaction.guild
    rewards = await database.get_level_role_rewards()
    embed = discord.Embed(title="⚙️ レベル到達ロール報酬設定", description="特定のレベルに達したメンバーに自動付与するロールを管理します。", color=discord.Color.blue())
    
    tc_rewards = [r for r in rewards if r["level_type"] == "tc"]
    vc_rewards = [r for r in rewards if r["level_type"] == "vc"]
    
    tc_text = ""
    for r in sorted(tc_rewards, key=lambda x: x["level"]):
        role = guild.get_role(r["role_id"])
        mention = role.mention if role else f"未取得 (ID: {r['role_id']})"
        tc_text += f"・Lv.{r['level']} ➔ {mention}\n"
        
    vc_text = ""
    for r in sorted(vc_rewards, key=lambda x: x["level"]):
        role = guild.get_role(r["role_id"])
        mention = role.mention if role else f"未取得 (ID: {r['role_id']})"
        vc_text += f"・Lv.{r['level']} ➔ {mention}\n"
        
    embed.add_field(name="💬 テキスト (TC) レベル報酬", value=tc_text or "設定なし", inline=False)
    embed.add_field(name="🎙️ ボイス (VC) レベル報酬", value=vc_text or "設定なし", inline=False)
    
    view = LevelRolesConfigView(rewards, guild)
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

class ManageLevelRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="レベルロール設定", style=discord.ButtonStyle.primary, row=1)
    async def callback(self, interaction: discord.Interaction):
        await update_level_roles_config_view(interaction)

# --- 部屋の価格設定 ---
# --- 部屋の価格設定 ---
class RoomPriceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="一般宿 (12時間)", value="宿:12"),
            discord.SelectOption(label="一般宿 (24時間)", value="宿:24"),
            discord.SelectOption(label="高級宿 (12時間)", value="高級宿:12"),
            discord.SelectOption(label="高級宿 (24時間)", value="高級宿:24"),
            discord.SelectOption(label="カスタムVC (24時間)", value="カスタムVC:24"),
            discord.SelectOption(label="評価落ち用 高級宿 (12時間)", value="role:DOWNGRADE_ROLE:高級宿:12"),
            discord.SelectOption(label="評価落ち用 高級宿 (24時間)", value="role:DOWNGRADE_ROLE:高級宿:24"),
            discord.SelectOption(label="仮メンバー用 高級宿 (12時間)", value="role:NEW_MEMBER_ROLE:高級宿:12"),
            discord.SelectOption(label="仮メンバー用 高級宿 (24時間)", value="role:NEW_MEMBER_ROLE:高級宿:24")
        ]
        super().__init__(placeholder="価格を変更する部屋種別を選択...", options=options, row=0)
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_item = self.values[0]
        await interaction.response.defer(ephemeral=True)

class PriceInputModal(discord.ui.Modal, title='新しい価格の入力'):
    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref
        self.price_input = discord.ui.TextInput(label='新しい価格', placeholder='例: 15000', max_length=9, required=True)
        self.add_item(self.price_input)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bot = interaction.client
            price = int(self.price_input.value)
            if price < 0: raise ValueError
            parts = self.view_ref.selected_item.split(":")
            
            currency_name = get_setting(bot, "CURRENCY_NAME") or "コイン"
            
            if parts[0] == "role":
                role_key = parts[1]
                rtype = parts[2]
                dur = int(parts[3])
                await database.save_role_room_price(role_key, rtype, dur, price)
                bot.role_room_prices[(role_key, rtype, dur)] = price
                
                role_label = "評価落ち" if role_key == "DOWNGRADE_ROLE" else "仮メンバー"
                await interaction.response.send_message(f"✅ 更新しました: {role_label}用 {rtype} ({dur}時間) ➔ {price:,} {currency_name}", ephemeral=True)
            else:
                rtype, dur = parts[0], int(parts[1])
                await database.save_room_price(rtype, dur, price)
                if rtype in ROOM_SETTINGS and dur in ROOM_SETTINGS[rtype]:
                    ROOM_SETTINGS[rtype][dur]["price"] = price
                await interaction.response.send_message(f"✅ 更新しました: {rtype} ({dur}時間) ➔ {price:,} {currency_name}", ephemeral=True)
                
            await update_room_prices_config_view(interaction)
        except Exception as e:
            print(f"[ERROR] PriceInputModal submission error: {e}")
            await interaction.response.send_message("正の整数を入力してください。", ephemeral=True)

class RoomPricesConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.selected_item = None
        self.add_item(RoomPriceSelect())
        self.add_item(BackToAdminPanelButton(row=2))

    @discord.ui.button(label="価格を入力する", style=discord.ButtonStyle.success, row=1)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_item:
            return await interaction.response.send_message("部屋種別を選択してください。", ephemeral=True)
        await interaction.response.send_modal(PriceInputModal(self))

async def update_room_prices_config_view(interaction: discord.Interaction):
    bot = interaction.client
    prices = await database.get_all_room_prices()
    role_prices = await database.get_all_role_room_prices()
    
    embed = discord.Embed(title="⚙️ 部屋の価格設定", description="宿やカスタムVCのレンタル料金を管理します。", color=discord.Color.blue())
    
    currency_name = get_setting(bot, "CURRENCY_NAME") or "コイン"
    text = ""
    for p in prices:
        text += f"・{p['room_type']} ({p['duration']}時間) ➔ **{p['price']:,} {currency_name}**\n"
        
    if role_prices:
        role_key_names = {
            "DOWNGRADE_ROLE": "評価落ち",
            "NEW_MEMBER_ROLE": "仮メンバー"
        }
        text += "\n**[ロール別特別価格]**\n"
        for rp in role_prices:
            role_label = role_key_names.get(rp["role_key"], rp["role_key"])
            text += f" ・{role_label}用 {rp['room_type']} ({rp['duration']}時間) ➔ **{rp['price']:,} {currency_name}**\n"
        
    embed.add_field(name="現在の価格設定一覧", value=text or "設定なし", inline=False)
    view = RoomPricesConfigView()
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

class ManageRoomPricesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="部屋価格設定", style=discord.ButtonStyle.primary, row=1)
    async def callback(self, interaction: discord.Interaction):
        await update_room_prices_config_view(interaction)

# --- VC自動作成トリガー設定 ---
class VCTriggerNameModal(discord.ui.Modal, title='ベースチャンネル名の設定'):
    def __init__(self, channel_id, cfg):
        super().__init__()
        self.channel_id = channel_id
        self.cfg = cfg
        self.name_input = discord.ui.TextInput(
            label='部屋のベース名 (空白で「🔊│メンバー名の部屋」)',
            placeholder='例: 雑談部屋',
            default=cfg.get("base_name", ""),
            required=False,
            max_length=50
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        bot = interaction.client
        base_name = self.name_input.value
        c = self.cfg
        await database.save_auto_vc_config(
            self.channel_id,
            base_name,
            c.get("allow_rename", True),
            c.get("include_owner_name", True),
            c.get("use_numbering", False),
            c.get("allow_limit_change", True),
            c.get("show_panel", True)
        )
        
        # キャッシュ更新
        bot.auto_vc_configs[self.channel_id] = {
            "channel_id": self.channel_id,
            "base_name": base_name,
            "allow_rename": c.get("allow_rename", True),
            "include_owner_name": c.get("include_owner_name", True),
            "use_numbering": c.get("use_numbering", False),
            "allow_limit_change": c.get("allow_limit_change", True),
            "show_panel": c.get("show_panel", True)
        }
        
        await interaction.response.send_message("✅ ベースチャンネル名を更新しました！", ephemeral=True)
        await update_config_view(interaction)

class VCTriggerOptionsView(discord.ui.View):
    def __init__(self, channel_id, cfg):
        super().__init__(timeout=120)
        self.channel_id = channel_id
        self.cfg = cfg
        self.update_buttons()

    def update_buttons(self):
        c = self.cfg
        self.rename_btn.label = f"名前変更の許可: {'⭕' if c.get('allow_rename', True) else '❌'}"
        self.owner_btn.label = f"所有者名の付与: {'⭕' if c.get('include_owner_name', True) else '❌'}"
        self.num_btn.label = f"連番（①②...）の付与: {'⭕' if c.get('use_numbering', False) else '❌'}"
        self.limit_btn.label = f"人数制限変更の許可: {'⭕' if c.get('allow_limit_change', True) else '❌'}"
        self.show_panel_btn.label = f"設定パネルの送信: {'⭕' if c.get('show_panel', True) else '❌'}"

    async def save(self, interaction):
        bot = interaction.client
        c = self.cfg
        await database.save_auto_vc_config(
            self.channel_id,
            c.get("base_name", ""),
            c.get("allow_rename", True),
            c.get("include_owner_name", True),
            c.get("use_numbering", False),
            c.get("allow_limit_change", True),
            c.get("show_panel", True)
        )
        bot.auto_vc_configs[self.channel_id] = c
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, row=0)
    async def rename_btn(self, interaction, button):
        self.cfg["allow_rename"] = not self.cfg.get("allow_rename", True)
        await self.save(interaction)

    @discord.ui.button(style=discord.ButtonStyle.secondary, row=0)
    async def owner_btn(self, interaction, button):
        self.cfg["include_owner_name"] = not self.cfg.get("include_owner_name", True)
        await self.save(interaction)

    @discord.ui.button(style=discord.ButtonStyle.secondary, row=0)
    async def num_btn(self, interaction, button):
        self.cfg["use_numbering"] = not self.cfg.get("use_numbering", False)
        await self.save(interaction)

    @discord.ui.button(style=discord.ButtonStyle.secondary, row=1)
    async def limit_btn(self, interaction, button):
        self.cfg["allow_limit_change"] = not self.cfg.get("allow_limit_change", True)
        await self.save(interaction)

    @discord.ui.button(style=discord.ButtonStyle.secondary, row=1)
    async def show_panel_btn(self, interaction, button):
        self.cfg["show_panel"] = not self.cfg.get("show_panel", True)
        await self.save(interaction)

    @discord.ui.button(label="名前の編集...", style=discord.ButtonStyle.primary, row=2)
    async def edit_name_btn(self, interaction, button):
        await interaction.response.send_modal(VCTriggerNameModal(self.channel_id, self.cfg))

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        await update_config_view(interaction)

async def update_config_view(interaction):
    # helpers等ではなくここで呼ぶ
    await update_config_view_impl(interaction)

async def update_config_view_impl(interaction: discord.Interaction):
    bot = interaction.client
    triggers = await database.get_auto_vc_triggers()
    bot.auto_vc_triggers = set(triggers)
    
    embed = discord.Embed(
        title="⚙️ 自動VC作成トリガー設定",
        description="特定のボイスチャンネルに入室した際、自動的に一時部屋を作成するトリガーを管理します。",
        color=discord.Color.blue()
    )
    
    text = ""
    for tid in triggers:
        ch = bot.get_channel(tid)
        mention = ch.mention if ch else f"未取得 (ID: {tid})"
        cfg = bot.auto_vc_configs.get(tid, {})
        base = cfg.get("base_name") or "（デフォルト）"
        text += f"・{mention} [ベース名: {base}]\n"
        
    embed.add_field(name="現在の登録トリガー一覧", value=text or "登録されているトリガーはありません。", inline=False)
    view = VCTriggersConfigView(triggers, bot)
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

class AddVCTriggerSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="トリガーにするボイスチャンネルを選択...", channel_types=[discord.ChannelType.voice], row=0)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        ch = self.values[0]
        if ch.id in bot.auto_vc_triggers:
            return await interaction.followup.send("⚠️ このチャンネルは既にトリガーに登録されています。", ephemeral=True)
            
        await database.add_auto_vc_trigger(ch.id)
        bot.auto_vc_triggers.add(ch.id)
        
        # デフォルト設定保存
        await database.save_auto_vc_config(ch.id, "", True, True, False, True, True)
        bot.auto_vc_configs[ch.id] = {
            "channel_id": ch.id, "base_name": "", "allow_rename": True,
            "include_owner_name": True, "use_numbering": False, "allow_limit_change": True, "show_panel": True
        }
        
        await update_config_view(interaction)

class RemoveVCTriggerSelect(discord.ui.Select):
    def __init__(self, triggers, bot):
        options = []
        for tid in triggers:
            ch = bot.get_channel(tid)
            name = ch.name if ch else f"不明 (ID: {tid})"
            options.append(discord.SelectOption(label=f"解除: {name}", value=str(tid)))
        super().__init__(placeholder="トリガー設定を解除するチャンネル...", options=options, row=1)
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        tid = int(self.values[0])
        await database.remove_auto_vc_trigger(tid)
        bot.auto_vc_triggers.discard(tid)
        bot.auto_vc_configs.pop(tid, None)
        await update_config_view(interaction)

class BotSetupConfigureView(discord.ui.Select):
    def __init__(self, triggers, bot):
        options = []
        for tid in triggers:
            ch = bot.get_channel(tid)
            name = ch.name if ch else f"不明 (ID: {tid})"
            options.append(discord.SelectOption(label=f"詳細設定: {name}", value=str(tid)))
        super().__init__(placeholder="詳細設定をするトリガーを選択...", options=options, row=2)
        
    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        tid = int(self.values[0])
        cfg = bot.auto_vc_configs.get(tid)
        if not cfg:
            cfg = {
                "channel_id": tid, "base_name": "", "allow_rename": True,
                "include_owner_name": True, "use_numbering": False, "allow_limit_change": True, "show_panel": True
            }
            
        ch = bot.get_channel(tid)
        name = ch.name if ch else f"ID: {tid}"
        
        embed = discord.Embed(
            title=f"⚙️ 詳細設定: {name}",
            description="自動作成される一時部屋の挙動を設定できます。",
            color=discord.Color.blue()
        )
        
        view = VCTriggerOptionsView(tid, cfg)
        await interaction.response.edit_message(embed=embed, view=view)

class VCTriggersConfigView(discord.ui.View):
    def __init__(self, triggers, bot):
        super().__init__(timeout=180)
        self.add_item(AddVCTriggerSelect())
        if triggers:
            self.add_item(RemoveVCTriggerSelect(triggers, bot))
            self.add_item(BotSetupConfigureView(triggers, bot))
        self.add_item(BackToAdminPanelButton(row=3))

class ManageVCTriggersButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="自動VCトリガー設定", style=discord.ButtonStyle.primary, row=1)
    async def callback(self, interaction: discord.Interaction):
        await update_config_view_impl(interaction)

# --- 評価管理設定 ---
class AddEvaluationForumSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="評価フォーラムを追加...", channel_types=[discord.ChannelType.forum], row=0)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        ch = self.values[0]
        cfg = bot.get_evaluation_config(interaction.guild.id)
        cfg["forum_channel_ids"].add(ch.id)
        await database.set_evaluation_settings(interaction.guild.id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        await update_evaluation_settings_config_view(interaction)

class RemoveEvaluationForumSelect(discord.ui.Select):
    def __init__(self, forum_ids, bot):
        options = []
        for fid in forum_ids:
            ch = bot.get_channel(fid)
            name = ch.name if ch else f"不明 (ID: {fid})"
            options.append(discord.SelectOption(label=f"削除: {name}", value=str(fid)))
        super().__init__(placeholder="評価フォーラムを削除...", options=options, row=1)
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        fid = int(self.values[0])
        cfg = bot.get_evaluation_config(interaction.guild.id)
        cfg["forum_channel_ids"].discard(fid)
        await database.set_evaluation_settings(interaction.guild.id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        await update_evaluation_settings_config_view(interaction)

class AddSelfIntroChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="自己紹介チャンネルを追加...", channel_types=[discord.ChannelType.text], row=2)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        ch = self.values[0]
        cfg = bot.get_evaluation_config(interaction.guild.id)
        cfg["self_intro_channel_ids"].add(ch.id)
        await database.set_evaluation_settings(interaction.guild.id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        await update_evaluation_settings_config_view(interaction)

class RemoveSelfIntroChannelSelect(discord.ui.Select):
    def __init__(self, channel_ids, bot):
        options = []
        for cid in channel_ids:
            ch = bot.get_channel(cid)
            name = ch.name if ch else f"不明 (ID: {cid})"
            options.append(discord.SelectOption(label=f"削除: {name}", value=str(cid)))
        super().__init__(placeholder="自己紹介チャンネルを削除...", options=options, row=3)
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        cid = int(self.values[0])
        cfg = bot.get_evaluation_config(interaction.guild.id)
        cfg["self_intro_channel_ids"].discard(cid)
        await database.set_evaluation_settings(interaction.guild.id, list(cfg["forum_channel_ids"]), list(cfg["self_intro_channel_ids"]))
        await update_evaluation_settings_config_view(interaction)

class EvaluationSettingsConfigView(discord.ui.View):
    def __init__(self, cfg, bot):
        super().__init__(timeout=180)
        self.add_item(AddEvaluationForumSelect())
        if cfg["forum_channel_ids"]:
            self.add_item(RemoveEvaluationForumSelect(list(cfg["forum_channel_ids"]), bot))
            
        self.add_item(AddSelfIntroChannelSelect())
        if cfg["self_intro_channel_ids"]:
            self.add_item(RemoveSelfIntroChannelSelect(list(cfg["self_intro_channel_ids"]), bot))
            
        self.add_item(BackToAdminPanelButton(row=4))

async def update_evaluation_settings_config_view(interaction: discord.Interaction):
    bot = interaction.client
    guild = interaction.guild
    cfg = bot.get_evaluation_config(guild.id)
    embed = discord.Embed(title="⚙️ 評価スレッド作成設定", description="自己紹介が投稿された際に自動で評価スレッドを作成する設定を管理します。", color=discord.Color.blue())
    
    forums = [bot.get_channel(fid).mention for fid in cfg["forum_channel_ids"] if bot.get_channel(fid)]
    embed.add_field(name="評価フォーラム一覧", value=", ".join(forums) if forums else "なし", inline=False)
    
    intros = [bot.get_channel(cid).mention for cid in cfg["self_intro_channel_ids"] if bot.get_channel(cid)]
    embed.add_field(name="対象自己紹介チャンネル一覧", value=", ".join(intros) if intros else "なし", inline=False)
    
    view = EvaluationSettingsConfigView(cfg, bot)
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, view=view)

class ManageEvaluationSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="自己紹介評価設定", style=discord.ButtonStyle.primary, row=2)
    async def callback(self, interaction: discord.Interaction):
        await update_evaluation_settings_config_view(interaction)

# --- 基本設定 (BotSetup) ---
class BotSetupRoleSelect(discord.ui.RoleSelect):
    def __init__(self, key, label):
        super().__init__(placeholder=label, min_values=1, max_values=10 if "IDS" in key else 1)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        val = self.values
        
        if "IDS" in self.key:
            ids = [r.id for r in val]
            await database.save_setting(self.key, ids)
            bot.bot_settings[self.key] = ids
        else:
            rid = val[0].id
            await database.save_setting(self.key, rid)
            bot.bot_settings[self.key] = rid
            
        await update_main_admin_panel(interaction)

class BotSetupChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, key, label, ctype):
        super().__init__(placeholder=label, channel_types=[ctype])
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        chan = self.values[0]
        await database.save_setting(self.key, chan.id)
        bot.bot_settings[self.key] = chan.id
        await update_main_admin_panel(interaction)

class BotSetupMainSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="レベル通知チャンネル", value="LEVEL_UP_CHANNEL_ID"),
            discord.SelectOption(label="評価対象カテゴリー", value="EVALUATION_CATEGORY_ID"),
            discord.SelectOption(label="仮（新規）メンバーロール", value="NEW_MEMBER_ROLE_ID"),
            discord.SelectOption(label="評価落ちロール", value="DOWNGRADE_ROLE_ID"),
            discord.SelectOption(label="入界待機者ロール", value="PENDING_MEMBER_ROLE_ID"),
            discord.SelectOption(label="スタンプ統括ロール", value="EMBLEM_MANAGER_ROLE_ID"),
            discord.SelectOption(label="スタンプ制作ロール", value="EMBLEM_MASTER_ROLE_ID"),
            discord.SelectOption(label="告解司祭ロール", value="CONFESSION_PRIEST_ROLE_ID"),
            discord.SelectOption(label="司祭ロール", value="PRIEST_ROLE_ID"),
            discord.SelectOption(label="運営管理者ロール (複数可)", value="ADMIN_ROLE_IDS"),
            discord.SelectOption(label="面接官ロール (複数可)", value="INTERVIEWER_ROLE_IDS"),
            discord.SelectOption(label="初級評価員ロール (複数可)", value="EVALUATOR_ROLE_IDS"),
            discord.SelectOption(label="中級評価員ロール (複数可)", value="EVALUATOR_TIER2_ROLE_IDS"),
            discord.SelectOption(label="上級評価員ロール (複数可)", value="EVALUATOR_TIER3_ROLE_IDS"),
            discord.SelectOption(label="無料宿ロール (複数可)", value="FREE_INN_ROLE_IDS"),
            discord.SelectOption(label="本・準メンバーロール (複数可)", value="MAIN_SUB_MEMBER_ROLE_IDS"),
            discord.SelectOption(label="イベントマネージャーロール (複数可)", value="EVENT_MANAGER_ROLE_IDS"),
            discord.SelectOption(label="賭博従業員ロール (複数可)", value="GAMBLE_EMPLOYEE_ROLE_IDS")
        ]
        super().__init__(placeholder="設定する項目を選択...", options=options, custom_id="admin_bot_setup_main_select")

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        bot = interaction.client
        view = discord.ui.View()
        
        # チャンネルかロールかを判別
        role_items = [
            "NEW_MEMBER_ROLE_ID", "DOWNGRADE_ROLE_ID", "PENDING_MEMBER_ROLE_ID", "EMBLEM_MANAGER_ROLE_ID", "EMBLEM_MASTER_ROLE_ID",
            "CONFESSION_PRIEST_ROLE_ID", "PRIEST_ROLE_ID", "ADMIN_ROLE_IDS", "INTERVIEWER_ROLE_IDS",
            "EVALUATOR_ROLE_IDS", "EVALUATOR_TIER2_ROLE_IDS", "EVALUATOR_TIER3_ROLE_IDS", "FREE_INN_ROLE_IDS",
            "MAIN_SUB_MEMBER_ROLE_IDS", "EVENT_MANAGER_ROLE_IDS", "GAMBLE_EMPLOYEE_ROLE_IDS"
        ]
        
        if val in role_items:
            view.add_item(BotSetupRoleSelect(val, f"対象ロールを選択 ({self.placeholder})"))
        elif val == "LEVEL_UP_CHANNEL_ID":
            view.add_item(BotSetupChannelSelect(val, "通知するテキストチャンネルを選択...", discord.ChannelType.text))
        elif val == "EVALUATION_CATEGORY_ID":
            view.add_item(BotSetupChannelSelect(val, "評価対象のボイスカテゴリーを選択...", discord.ChannelType.category))
            
        view.add_item(BackToAdminPanelButton())
        
        # 現在の設定値を取得して表示
        current_val = get_setting(bot, val)
        guild = interaction.guild
        current_status = "未設定"
        if current_val:
            if isinstance(current_val, list):
                mentions = []
                for item_id in current_val:
                    role = guild.get_role(item_id)
                    if role:
                        mentions.append(role.mention)
                    else:
                        chan = bot.get_channel(item_id)
                        if chan:
                            mentions.append(chan.mention)
                        else:
                            mentions.append(f"不明 (ID: {item_id})")
                if mentions:
                    current_status = "、".join(mentions)
            else:
                role = guild.get_role(current_val)
                if role:
                    current_status = role.mention
                else:
                    chan = bot.get_channel(current_val)
                    if chan:
                        current_status = chan.mention
                    else:
                        current_status = str(current_val)

        embed = discord.Embed(title=f"⚙️ 設定変更: {val}", description="下の選択メニューから値を選択してください。", color=discord.Color.blue())
        embed.add_field(name="現在の設定", value=current_status, inline=False)
        await interaction.response.edit_message(embed=embed, view=view)

class BotSetupMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BotSetupMainSelect())
        self.add_item(ManageLogSettingsButton())
        self.add_item(ManageRankSettingsButton())
        self.add_item(ManageLevelRolesButton())
        self.add_item(ManageRoomPricesButton())
        self.add_item(ManageVCTriggersButton())
        self.add_item(ManageEvaluationSettingsButton())
        self.add_item(ManageEconomySettingsButton())

class BackToAdminPanelButton(discord.ui.Button):
    def __init__(self, row=None):
        super().__init__(label="◀ 管理パネルに戻る", style=discord.ButtonStyle.secondary, row=row)
    async def callback(self, interaction: discord.Interaction):
        await update_main_admin_panel(interaction)

# --- パネル設置 ---
class PanelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="チンチロリン", description="チンチロリンゲームのパネルを設置します", emoji="🎲", value="chinchiro"),
            discord.SelectOption(label="コイントス", description="コイントスゲームのパネルを設置します", emoji="🪙", value="coinflip"),
            discord.SelectOption(label="スロット", description="スロットゲームのパネルを設置します", emoji="🎰", value="slot"),
            discord.SelectOption(label="ブラックジャック", description="ブラックジャックゲームのパネルを設置します", emoji="🃏", value="blackjack"),
            discord.SelectOption(label="ルーレット", description="ルーレットゲームのパネルを設置します", emoji="🎡", value="roulette"),
            discord.SelectOption(label="一般宿", description="一般宿の購入パネルを設置します", emoji="🛖", value="general_inn"),
            discord.SelectOption(label="高級宿", description="高級宿の購入パネルを設置します", emoji="🏰", value="luxury_inn"),
            discord.SelectOption(label="カスタムVC", description="カスタムVCの作成パネルを設置します", emoji="✨", value="custom_vc"),
            discord.SelectOption(label="スタンプ依頼", description="スタンプ制作依頼のパネルを設置します", emoji="🎨", value="stamp"),
            discord.SelectOption(label="告解・相談室", description="告解・相談依頼のパネルを設置します", emoji="⛪", value="confession"),
            discord.SelectOption(label="VC管理", description="VC名・人数制限変更のパネルを設置します", emoji="⚙️", value="vc_manage"),
            discord.SelectOption(label="入界手続き", description="新規メンバーの入界手続きパネルを設置します", emoji="📝", value="interview"),
            discord.SelectOption(label="お問い合わせ", description="お問い合わせ作成パネルを設置します", emoji="✉️", value="inquiry"),
            discord.SelectOption(label="匿名チャット", description="匿名チャットのパネルを設置します", emoji="💬", value="anonymous_chat"),
            discord.SelectOption(label="カスタムチケット", description="任意のタイトル・説明文・担当ロールを指定したチケットパネルを設置します", emoji="🎫", value="custom_ticket")
        ]
        super().__init__(placeholder="設置するパネルを選択してください...", min_values=1, max_values=1, options=options, custom_id="admin_panel_setup_select")

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        bot = interaction.client
        channel = interaction.channel
        
        # 権限チェック
        if not has_admin_role(bot, interaction.user) and not interaction.user.guild_permissions.administrator:
            if val == "interview":
                user_role_names = [r.name for r in interaction.user.roles]
                is_interviewer = any(r in INTERVIEWER_ROLE_NAMES for r in user_role_names)
                if not is_interviewer:
                    return await interaction.response.send_message("この操作を実行する権限がありません。", ephemeral=True)
            else:
                return await interaction.response.send_message("この操作を実行する権限がありません（運営専用）。", ephemeral=True)

        currency_name = get_setting(bot, "CURRENCY_NAME") or "コイン"
        
        if val == "chinchiro":
            embed = discord.Embed(title="🎲 チンチロリン", description="カジノへようこそ！", color=discord.Color.dark_green())
            await channel.send(embed=embed, view=ChinchiroView())
            await interaction.response.send_message("✅ チンチロリンパネルを設置しました。", ephemeral=True)
        elif val == "coinflip":
            embed = discord.Embed(title="🪙 コイントス", description="表か裏か！", color=discord.Color.blue())
            await channel.send(embed=embed, view=CoinflipView())
            await interaction.response.send_message("✅ コイントスパネルを設置しました。", ephemeral=True)
        elif val == "slot":
            embed = discord.Embed(title="🎰 スロット", description="絵柄を揃えろ！", color=discord.Color.orange())
            await channel.send(embed=embed, view=SlotView())
            await interaction.response.send_message("✅ スロットパネルを設置しました。", ephemeral=True)
        elif val == "blackjack":
            embed = discord.Embed(
                title="🃏 ブラックジャック",
                description=(
                    "カジノへようこそ！ディーラーと勝負して21を目指そう！\n\n"
                    "**【基本ルール】**\n"
                    "- 配られたカードの合計値が **21** に近い方が勝利となります。\n"
                    "- 合計値が **21 を超えると敗北 (Bust)** となります。\n\n"
                    "**【カードの数え方】**\n"
                    "- `2`〜`10`: そのままの数字で計算します。\n"
                    "- `J`, `Q`, `K`: すべて `10` として計算します。\n"
                    "- `A`: `1` または `11` の都合が良い方の値で自動計算されます。\n\n"
                    "**【操作方法】**\n"
                    "- **「カードを引く (Hit)」**: 手札にカードを1枚追加します。\n"
                    "- **「勝負する (Stand)」**: 現在の手札でディーラーと勝負します。\n"
                    "- ※ディーラーは手札の合計が **17 以上になるまで** 自動でカードを引き続けます。\n\n"
                    "**【配当と制限】**\n"
                    "- 勝利時: 賭け金の **2.0倍**\n"
                    "- ブラックジャック勝利時 (初期手札で21点): 賭け金の **2.5倍**\n"
                    "- 引き分け時: 賭け金を払い戻し (1.0倍)\n"
                    f"- 1プレイあたり **1 〜 100,000 {currency_name}** までベット可能。\n"
                    "- ※他のゲームと共通で1日10回の回数制限があります。"
                ),
                color=discord.Color.dark_purple()
            )
            await channel.send(embed=embed, view=BlackjackView())
            await interaction.response.send_message("✅ ブラックジャックパネルを設置しました。", ephemeral=True)
        elif val == "roulette":
            embed = discord.Embed(
                title="🎡 ルーレット",
                description=(
                    f"カジノへようこそ！ルーレットの出目を予想して{currency_name}を増やそう！\n\n"
                    "**【基本ルール】**\n"
                    "- 0〜36の計37個の数字からなるホイールが回転し、ボールが落ちた箇所が当選番号となります。\n\n"
                    "**【賭け方と配当】**\n"
                    "- **2.0倍配当**: 🔴赤 / ⚫黒 / 🔢偶数 / 🔣奇数 / ⬇️ロー (1-18) / ⬆️ハイ (19-36)\n"
                    "- **3.0倍配当**: ダズン (1-12 / 13-24 / 25-36)\n"
                    "- **36.0倍配当**: 🎯数字1点賭け (0〜36の特定の数字)\n\n"
                    "**【注意事項】**\n"
                    "- ※当選番号が `0`（緑色）の場合、数字の0への1点賭けを除き、すべての賭け（赤黒、偶奇など）はハズレとなります。\n"
                    f"- 1プレイあたり **1 〜 100,000 {currency_name}** までベット可能。\n"
                    "- ※他のゲームと共通で1日10回の回数制限があります。"
                ),
                color=discord.Color.dark_red()
            )
            await channel.send(embed=embed, view=RouletteView())
            await interaction.response.send_message("✅ ルーレットパネルを設置しました。", ephemeral=True)
        elif val == "general_inn":
            # 無料対象ロールを動的取得
            free_inn_ids = get_setting(bot, "FREE_INN_ROLE_IDS") or []
            free_inn_roles = [guild.get_role(rid).mention for rid in free_inn_ids if guild.get_role(rid)]
            
            # 互換用の旧ロール名リストも検索
            for name in FREE_INN_ROLE_NAMES:
                role = discord.utils.get(guild.roles, name=name)
                if role and role.mention not in free_inn_roles:
                    free_inn_roles.append(role.mention)
            
            role_mention_str = "、".join(free_inn_roles) if free_inn_roles else "未設定"
            
            embed = discord.Embed(
                title="🛖 一般宿", 
                description=(
                    "「一般宿」を借りることができます。\n"
                    "ボタンを押して、利用期間を選択してください。\n\n"
                    f"**🎁 無料対象ロール:**\n{role_mention_str}\n"
                    "※上記のロールをお持ちの方は **無料** で一般宿を作成可能です。"
                ), 
                color=discord.Color.gold()
            )
            await channel.send(embed=embed, view=RoomView())
            await interaction.response.send_message("✅ 一般宿パネルを設置しました。", ephemeral=True)
        elif val == "luxury_inn":
            embed = discord.Embed(
                title="🏰 高級宿", 
                description=(
                    "「高級宿」を借りることができます。\n"
                    "ボタンを押して、利用期間を選択してください。\n"
                    "※高級宿は無料化ロールの対象外です。"
                ), 
                color=discord.Color.purple()
            )
            await channel.send(embed=embed, view=LuxuryRoomView())
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
                    "※相談内容や告解の秘密は、担当司祭および運営管理者のみが閲覧可能なチケットチャンネルで厳重に保護されます。"
                ),
                color=discord.Color.purple()
            )
            await channel.send(embed=embed, view=ConfessionRequestPanelView())
            await interaction.response.send_message("✅ 告解パネルを設置しました。", ephemeral=True)
        elif val == "vc_manage":
            embed = discord.Embed(title="⚙️ VCコントロール", description="このパネルから、自分が参加している一時部屋の名前変更や制限人数の設定を行えます。", color=discord.Color.blue())
            await channel.send(embed=embed, view=VCRenamePanelView())
            await interaction.response.send_message("✅ VC管理パネルを設置しました。", ephemeral=True)
        elif val == "interview":
            embed = discord.Embed(title="📝 入界手続き窓口", description="仮入界（面接）を通過された方は、こちらのボタンを押して手続きを行ってください。\n名前を設定し、初期通貨が発行されます。", color=discord.Color.green())
            await channel.send(embed=embed, view=InterviewPanelView())
            await interaction.response.send_message("✅ 入界パネルを設置しました。", ephemeral=True)
        elif val == "inquiry":
            view = InquirySetupView()
            await interaction.response.send_message("設置するお問い合わせ窓口パネルの、**通知先（メンション先）となる担当者ロール**を選択してください。", view=view, ephemeral=True)
        elif val == "anonymous_chat":
            view = AnonymousChatSetupView()
            await interaction.response.send_message("匿名チャットパネルの設定を行います。設置先と送信先のチャンネルをそれぞれ選択してください。", view=view, ephemeral=True)
        elif val == "custom_ticket":
            await interaction.response.send_modal(CustomTicketSetupModal())

class PanelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PanelSelect())

# --- リアクションロール ---
class StickyTemplateModal(discord.ui.Modal, title="固定テンプレートの作成"):
    content_input = discord.ui.TextInput(
        label="固定するテキスト内容",
        style=discord.TextStyle.paragraph,
        placeholder="メッセージの最後に常に表示される内容を入力してください。",
        max_length=2000,
        required=True
    )
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # 以前表示されていた jump_url 等を考慮せず、シンプルなコンテンツの送信
        await database.save_sticky_template(interaction.channel.id, self.content_input.value)
        
        # 新しいメッセージを送信
        new_msg = await interaction.channel.send(content=self.content_input.value)
        await database.update_sticky_last_message(interaction.channel.id, new_msg.id, None)
        await interaction.followup.send("✅ 固定テンプレートを設定しました。", ephemeral=True)

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

# --- コマンドグループ ---
class AdminGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="運営", description="運営管理者専用コマンド")
        self.bot = bot

    @app_commands.command(name="設定パネル", description="【運営専用】Botの基本設定パネルを表示します")
    @is_admin()
    async def bot_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            embed = await create_admin_panel_embed(self.bot, interaction.guild)
            view = BotSetupMainView()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            print(f"[ERROR] bot_setup: {e}")
            await interaction.followup.send("⚠️ 設定パネルの生成中にエラーが発生しました。", ephemeral=True)

    @app_commands.command(name="パネル設置", description="【運営専用】各種コントロールパネル（カジノ、部屋作成など）を設置します")
    @is_admin()
    async def panel_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚙️ パネル設置メニュー", description="設置したい機能を選択肢から選んでください。\n（現在のテキストチャンネルに設置用Embedが送信されます）", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=PanelSetupView(), ephemeral=True)

    @app_commands.command(name="任意ロールパネル設置", description="【運営専用】ユーザーがリアクションを押すことで自由に付与・剥奪できるロールパネルを設置します")
    @is_admin()
    async def reaction_role_setup(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CustomRolePanelSetupModal())

    @app_commands.command(name="固定テンプレート設定", description="【運営専用】このチャンネルのチャットテンプレートを固定し、常に最新の発言として自動更新します")
    @is_admin()
    async def sticky_template_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StickyTemplateModal())

    @app_commands.command(name="固定テンプレート削除", description="【運営専用】このチャンネルに設定されている固定テンプレートを削除します")
    @is_admin()
    async def sticky_template_delete(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        sticky_data = await database.get_sticky_template(interaction.channel.id)
        if not sticky_data:
            return await interaction.followup.send("⚠️ このチャンネルには固定テンプレートが設定されていません。", ephemeral=True)
            
        if sticky_data["last_message_id"]:
            try:
                old_msg = await interaction.channel.fetch_message(sticky_data["last_message_id"])
                await old_msg.delete()
            except:
                pass
                
        await database.remove_sticky_template(interaction.channel.id)
        await interaction.followup.send("🗑️ 固定テンプレートの設定を削除しました。", ephemeral=True)

    @app_commands.command(name="チャット消去", description="【運営・面接官専用】チャンネル内のメッセージを指定された件数分、一括削除します")
    @is_admin_or_interviewer()
    async def clear_chat(self, interaction: discord.Interaction, count: int):
        if count <= 0:
            return await interaction.response.send_message("1以上の件数を指定してください。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=count)
        await interaction.followup.send(f"🧹 メッセージを {len(deleted)} 件削除しました。", ephemeral=True)

    @app_commands.command(name="手動給与", description="【運営専用】指定したユーザーに通貨を直接発行して付与します")
    @is_admin()
    @app_commands.describe(user="付与するユーザー", amount="金額")
    async def manual_issue(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer(ephemeral=True)
        await database.add_balance(user.id, amount)
        cur_name = get_setting(self.bot, "CURRENCY_NAME") or "コイン"
        await interaction.followup.send(f"💵 {user.mention} に **{amount} {cur_name}** を付与しました。", ephemeral=True)

        # 通貨ログの送信
        embed = discord.Embed(
            title="💵 手動給与 (運営)",
            description="運営による手動給与が行われました。",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="実行者", value=f"{interaction.user.mention} ({interaction.user.id})", inline=True)
        embed.add_field(name="対象者", value=f"{user.mention} ({user.id})", inline=True)
        embed.add_field(name="付与額", value=f"{amount:,} {cur_name}", inline=True)
        await send_log(self.bot, interaction.guild, "currency", embed)

    @app_commands.command(name="一括初期給与", description="【運営専用】まだ初期給与（30000コイン）を受け取っていない全員に一括で発行します")
    @is_admin()
    async def batch_initial_issue(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        bot = self.bot
        new_role = get_role_by_setting(bot, guild, "NEW_MEMBER_ROLE_ID", NEW_MEMBER_ROLE_NAME)
        if not new_role:
            return await interaction.followup.send(f"❌ 仮メンバー（新規メンバー）ロールが設定されていないか見つかりません。", ephemeral=True)
            
        initial_coins = get_setting(bot, "INITIAL_COINS") or 30000
        cur_name = get_setting(bot, "CURRENCY_NAME") or "コイン"
        
        issued_count = 0
        issued_members = []
        for member in new_role.members:
            if member.bot: continue
            
            # DBの users から initial_issued を確認
            user_data = await database.get_user(member.id)
            if not user_data.get("initial_issued", False):
                await database.add_balance(member.id, initial_coins)
                await database.mark_initial_issued(member.id)
                issued_count += 1
                issued_members.append(f"{member.mention} (ID: {member.id})")
                
        await interaction.followup.send(f"✅ 未受け取り of {issued_count} 名に初期給与 **{initial_coins} {cur_name}** を発行しました！", ephemeral=True)

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
            
            await send_log(self.bot, interaction.guild, "currency", embed)

    @app_commands.command(name="デバッグ用vc強制退室", description="【運営専用】指定したユーザーのVC接続セッションを強制的に終了させます（時間測定 of バグ修正用）")
    @is_admin()
    @app_commands.describe(user="強制退室させるユーザー")
    async def debug_vc(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        session = self.bot.vc_sessions.pop(user.id, None)
        if session:
            await interaction.followup.send(f"✅ {user.display_name} のVCセッションを破棄しました。", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ {user.display_name} はVCセッションを保持していませんでした。", ephemeral=True)

# --- Cogの定義 ---
class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelSetupView())
        
        # コマンドグループの追加
        self.bot.tree.add_command(AdminGroup(self.bot))

    async def cog_unload(self):
        self.bot.tree.remove_command("運営")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # 荒らし対策: 連続同じメッセージ、@everyone/メンションスパム、招待URL連投
        if isinstance(message.author, discord.Member):
            user_id = message.author.id
            now = datetime.datetime.now(JST)

            if not hasattr(self.bot, 'spam_tracker'):
                self.bot.spam_tracker = {}

            user_tracker = self.bot.spam_tracker.setdefault(user_id, {
                "last_content": None,
                "content_count": 0,
                "everyone_count": 0,
                "invite_count": 0,
                "mention_count": 0,
                "last_time": now
            })

            # 3秒以上経過していればリセット
            if (now - user_tracker["last_time"]).total_seconds() > 3:
                user_tracker["content_count"] = 0
                user_tracker["everyone_count"] = 0
                user_tracker["invite_count"] = 0
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

            # @everyone or @here の検知 (他のメッセージを挟んでも3秒以内の累計でカウント)
            if message.mention_everyone:
                user_tracker["everyone_count"] += 1
                if user_tracker["everyone_count"] >= 5:
                    timeout_reason = "短時間に@everyoneメンションを複数回送信したため"

            # Discord招待URLの検知 (discord.gg/ などの招待リンク)
            import re
            DISCORD_INVITE_PATTERN = re.compile(
                r'(?:https?://)?(?:www\.)?(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)/[a-zA-Z0-9-]+',
                re.IGNORECASE
            )
            if DISCORD_INVITE_PATTERN.search(message.content):
                user_tracker["invite_count"] += 1
                if user_tracker["invite_count"] >= 5:
                    timeout_reason = "連続でDiscordの招待リンクを送信したため"

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
                    user_tracker["everyone_count"] = 0
                    user_tracker["invite_count"] = 0
                    user_tracker["mention_count"] = 0
                    return # スパムなら処理終了
                except Exception as e:
                    print(f"[ERROR] Timeout failed for {message.author.display_name}: {e}")

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
                        old_text_msg = await message.channel.fetch_message(sticky_data.get("last_text_message_id"))
                        await old_text_msg.delete()
                    except:
                        pass

                text_content = sticky_data['content']
                new_msg = await message.channel.send(content=text_content)
                await database.update_sticky_last_message(message.channel.id, new_msg.id, None)


    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot: return
        if before.content == after.content: return
        
        guild = before.guild
        if not guild: return
        
        embed = discord.Embed(title="📝 メッセージ編集", color=discord.Color.orange(), timestamp=datetime.datetime.now(JST))
        embed.set_author(name=f"{before.author} (ID: {before.author.id})", icon_url=before.author.display_avatar.url)
        embed.add_field(name="チャンネル", value=before.channel.mention, inline=True)
        embed.add_field(name="メッセージID", value=before.id, inline=True)
        
        before_content = before.content or "*メッセージ内容なし*"
        after_content = after.content or "*メッセージ内容なし*"
        
        if len(before_content) > 1024: before_content = before_content[:1020] + "..."
        if len(after_content) > 1024: after_content = after_content[:1020] + "..."
            
        embed.add_field(name="変更前", value=before_content, inline=False)
        embed.add_field(name="変更後", value=after_content, inline=False)
        embed.set_footer(text=f"編集者: {before.author.display_name}")
        
        await send_log(self.bot, guild, "message_edit", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot: return
        guild = message.guild
        if not guild: return
        
        embed = discord.Embed(title="🗑️ メッセージ削除", color=discord.Color.red(), timestamp=datetime.datetime.now(JST))
        embed.set_author(name=f"{message.author} (ID: {message.author.id})", icon_url=message.author.display_avatar.url)
        embed.add_field(name="チャンネル", value=message.channel.mention, inline=True)
        embed.add_field(name="メッセージID", value=message.id, inline=True)
        
        content = message.content or "*メッセージ内容なし*"
        if len(content) > 1024: content = content[:1020] + "..."
        embed.add_field(name="内容", value=content, inline=False)
        
        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            if len(attachment_urls) > 1024: attachment_urls = attachment_urls[:1020] + "..."
            embed.add_field(name="添付ファイル", value=attachment_urls, inline=False)
            
        embed.set_footer(text=f"作成者: {message.author.display_name}")
        await send_log(self.bot, guild, "message_delete", embed)

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
        dt_jst = dt.astimezone(JST)
        weekday_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"][dt_jst.weekday()]
        return f"{dt_jst.year}年{dt_jst.month}月{dt_jst.day}日 {weekday_ja} {dt_jst.hour}:{dt_jst.minute:02d}"

    def format_footer_time(self, dt: datetime.datetime) -> str:
        dt_jst = dt.astimezone(JST)
        now_jst = datetime.datetime.now(JST)
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
            self.bot.invite_cache[guild.id] = {
                invite.code: {
                    "uses": invite.uses,
                    "inviter": invite.inviter
                } for invite in invites
            }
            if guild.vanity_url_code:
                try:
                    vanity = await guild.vanity_invite()
                    self.bot.invite_cache[guild.id]["vanity"] = {
                        "uses": vanity.uses,
                        "inviter": None
                    }
                except:
                    pass
        except Exception as e:
            print(f"[Invite Cache] Failed to update cache for guild {guild.id}: {e}")

    async def find_used_invite(self, guild: discord.Guild):
        if not guild.me.guild_permissions.manage_guild:
            return "NO_PERMISSION"

        if guild.id not in self.bot.invite_cache:
            await self.update_invite_cache(guild)
            return None
            
        old_cache = self.bot.invite_cache[guild.id]
        new_invites = {}
        used_invite = None
        
        try:
            invites = await guild.invites()
            for invite in invites:
                new_invites[invite.code] = {
                    "uses": invite.uses,
                    "inviter": invite.inviter
                }
                
                old_info = old_cache.get(invite.code)
                if old_info and invite.uses > old_info.get("uses", 0):
                    used_invite = invite
            
            if guild.vanity_url_code:
                try:
                    vanity = await guild.vanity_invite()
                    new_invites["vanity"] = {
                        "uses": vanity.uses,
                        "inviter": None
                    }
                    old_vanity = old_cache.get("vanity")
                    if old_vanity and vanity.uses > old_vanity.get("uses", 0):
                        class VanityInvite:
                            code = guild.vanity_url_code
                            uses = vanity.uses
                            inviter = None
                        used_invite = VanityInvite()
                except:
                    pass

            # もし見つからず、古いキャッシュにあって新しい招待リストにないもの（使い捨て消滅リンク）があればそれを特定
            if not used_invite:
                for code, old_info in old_cache.items():
                    if code != "vanity" and code not in new_invites:
                        class TempInvite:
                            def __init__(self, code, uses, inviter):
                                self.code = code
                                self.uses = uses + 1
                                self.inviter = inviter
                        used_invite = TempInvite(code, old_info.get("uses", 0), old_info.get("inviter"))
                        break
            
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
        self.bot.invite_cache[guild.id][invite.code] = {
            "uses": invite.uses,
            "inviter": invite.inviter
        }

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
        
        if invite == "NO_PERMISSION":
            invite_code_val = "取得不可 (Botに『サーバーの管理』権限がありません)"
            inviter_val = "取得不可 (Botに『サーバーの管理』権限がありません)"
        elif invite:
            invite_code_val = f"https://discord.gg/{invite.code}\n(コード: `{invite.code}` / 使用回数: {invite.uses}回)"
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
        
        now = datetime.datetime.now(JST)
        embed.set_footer(text=f"🟢 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        
        await send_log(self.bot, guild, "member_join_leave", embed)

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
        
        now = datetime.datetime.now(JST)
        embed.set_footer(text=f"🔴 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        
        await send_log(self.bot, guild, "member_join_leave", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild
        if before.timed_out_until != after.timed_out_until:
            now = datetime.datetime.now(JST)
            
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
                await send_log(self.bot, guild, "member_join_leave", embed)
            
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
                await send_log(self.bot, guild, "member_join_leave", embed)

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
        
        now = datetime.datetime.now(JST)
        embed.set_footer(text=f"🔴 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        await send_log(self.bot, guild, "member_join_leave", embed)

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
        
        now = datetime.datetime.now(JST)
        embed.set_footer(text=f"🟢 {guild.name} • {self.format_footer_time(now)}")
        embed.timestamp = now
        await send_log(self.bot, guild, "member_join_leave", embed)


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id: return
        
        emoji_str = str(payload.emoji)
        role_id = await database.get_reaction_role(payload.message_id, emoji_str)
        if not role_id: return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        
        member = guild.get_member(payload.user_id)
        if not member: return
        
        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id: return
        
        emoji_str = str(payload.emoji)
        role_id = await database.get_reaction_role(payload.message_id, emoji_str)
        if not role_id: return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        
        member = guild.get_member(payload.user_id)
        if not member: return
        
        role = guild.get_role(role_id)
        if role:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass

async def setup(bot):
    await bot.add_cog(Admin(bot))
