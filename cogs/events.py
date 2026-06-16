import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import datetime
import config

EVENTS_FILE = 'events.json'

def load_events():
    if not os.path.exists(EVENTS_FILE):
        return {}
    try:
        with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_events(data):
    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def parse_date(date_str):
    if not date_str or date_str == "未定":
        return datetime.datetime.max
    
    formats = [
        "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M",
        "%m/%d %H:%M", "%m-%d %H:%M",
        "%Y/%m/%d", "%Y-%m-%d",
        "%m/%d", "%m-%d",
        "%Y年%m月%d日 %H:%M", "%m月%d日 %H:%M",
        "%Y年%m月%d日", "%m月%d日"
    ]
    for fmt in formats:
        try:
            parsed = datetime.datetime.strptime(date_str, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.datetime.now().year)
            return parsed
        except ValueError:
            pass
            
    return datetime.datetime.max

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    EventGroup = app_commands.Group(name="イベント", description="イベントのスケジュール管理を行います")

    @EventGroup.command(name="help", description="イベント管理機能の使い方を表示します")
    async def show_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📅 イベントスケジュール管理機能の使い方",
            description="イベントや予定を簡単に登録・共有できます！",
            color=discord.Color.blue()
        )
        embed.add_field(name="1. /イベント 登録", value="新しいイベントを作成します。企画書のURLも登録可能です。", inline=False)
        embed.add_field(name="2. /イベント 一覧", value="登録されているイベントを一覧で表示します。リンクもクリックできます。", inline=False)
        embed.add_field(name="3. /イベント 修正", value="イベントの内容を修正したり、後から企画書を追加したりできます。", inline=False)
        embed.add_field(name="4. /イベント 削除", value="イベントを一覧から削除します。", inline=False)
        await interaction.response.send_message(embed=embed)

    @EventGroup.command(name="登録", description="新しいイベントをスケジュールに登録します")
    @app_commands.describe(name="イベント名", start_date="開始日 (例: 5/10 21:00)", end_date="終了日（任意）", detail="詳細（任意）", proposal_url="企画書のURL（任意）")
    async def add_event(self, interaction: discord.Interaction, name: str, start_date: str, end_date: str = "", detail: str = "", proposal_url: str = ""):
        events = load_events()
        new_id = 1
        existing_ids = set(int(k) for k in events.keys() if k.isdigit())
        while new_id in existing_ids:
            new_id += 1
        
        events[str(new_id)] = {
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "detail": detail,
            "proposal_url": proposal_url,
            "created_by": interaction.user.display_name
        }
        save_events(events)
        
        embed = discord.Embed(title="✅ イベントを登録しました", color=discord.Color.green())
        embed.add_field(name="ID", value=str(new_id), inline=False)
        embed.add_field(name="イベント名", value=name, inline=False)
        if end_date:
            embed.add_field(name="開始", value=start_date, inline=False)
            embed.add_field(name="終了", value=end_date, inline=False)
        else:
            embed.add_field(name="日時", value=f"{start_date}（1日のみ）", inline=False)
        if detail:
            embed.add_field(name="詳細", value=detail, inline=False)
        if proposal_url:
            embed.add_field(name="企画書", value=f"[リンク]({proposal_url})", inline=False)
            
        await interaction.response.send_message(embed=embed)

    @EventGroup.command(name="一覧", description="登録されているイベントの一覧を表示します")
    async def list_events(self, interaction: discord.Interaction):
        events = load_events()
        if not events:
            await interaction.response.send_message("現在登録されているイベントはありません。")
            return
            
        embed = discord.Embed(title="📅 イベント一覧", color=discord.Color.blue())
        
        sorted_events = sorted(
            events.items(), 
            key=lambda item: parse_date(item[1].get("start_date", item[1].get("time", "未定")))
        )
        
        for event_id, info in sorted_events:
            name = info.get("name", "未定")
            start_date = info.get("start_date", info.get("time", "未定"))
            end_date = info.get("end_date", "")
            detail = info.get("detail", "")
            proposal_url = info.get("proposal_url", "")
            
            if end_date:
                value = f"**開始**: {start_date}\n**終了**: {end_date}"
            else:
                value = f"**日時**: {start_date}（1日のみ）"
            if detail:
                value += f"\n**詳細**: {detail}"
            if proposal_url:
                value += f"\n**企画書**: [リンク]({proposal_url})"
                
            embed.add_field(name=f"[ID: {event_id}] {name}", value=value, inline=False)
            
        await interaction.response.send_message(embed=embed)

    @EventGroup.command(name="修正", description="登録済みのイベント内容を修正します")
    @app_commands.describe(event_id="修正するイベントのID", name="新しいイベント名（任意）", start_date="新しい開始日（任意）", end_date="新しい終了日（任意）", detail="新しい詳細（任意）", proposal_url="新しい企画書URL（任意）")
    async def edit_event(self, interaction: discord.Interaction, event_id: int, name: str = None, start_date: str = None, end_date: str = None, detail: str = None, proposal_url: str = None):
        if not config.has_event_manager_role(self.bot, interaction.user):
            await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
            return
        events = load_events()
        eid_str = str(event_id)
        if eid_str not in events:
            await interaction.response.send_message(f"ID: {event_id} のイベントは見つかりませんでした。", ephemeral=True)
            return
            
        if name:
            events[eid_str]["name"] = name
        if start_date:
            events[eid_str]["start_date"] = start_date
        if end_date:
            events[eid_str]["end_date"] = end_date
        if detail:
            events[eid_str]["detail"] = detail
        if proposal_url:
            events[eid_str]["proposal_url"] = proposal_url
            
        save_events(events)
        await interaction.response.send_message(f"✅ ID: {event_id} のイベントを修正しました。")

    @EventGroup.command(name="削除", description="登録済みのイベントを削除します")
    @app_commands.describe(event_id="削除するイベントのID")
    async def delete_event(self, interaction: discord.Interaction, event_id: int):
        if not config.has_event_manager_role(self.bot, interaction.user):
            await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
            return
        events = load_events()
        eid_str = str(event_id)
        if eid_str not in events:
            await interaction.response.send_message(f"ID: {event_id} のイベントは見つかりませんでした。", ephemeral=True)
            return
            
        deleted_name = events[eid_str].get("name", "")
        del events[eid_str]
        save_events(events)
        
        await interaction.response.send_message(f"🗑️ イベント「{deleted_name}」(ID: {event_id}) を削除しました。")

async def setup(bot):
    cog = Events(bot)
    await bot.add_cog(cog)
