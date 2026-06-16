import discord
from discord.ext import commands
import random
import datetime
import asyncio
import database
import config

class Gambling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(Gambling(bot))

class ChinchiroBetModal(discord.ui.Modal, title='チンチロリン：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000: return await interaction.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(config.JST)
            today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str); count = 0
            if count >= 10: return await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
            if await database.get_balance(interaction.user.id) < bet: return await interaction.followup.send("残高不足です。", ephemeral=True)
            await database.remove_balance(interaction.user.id, bet)
            await database.increment_gambling_count(interaction.user.id)
            await config.send_gambling_log(interaction.guild, interaction.user, "チンチロリン", bet, count + 1)
            view = ChinchiroGameView(interaction.user, bet)
            await interaction.followup.send(f"🎲 **チンチロリン開始！** (本日 {count+1}/10回目)\n賭け金: **{bet} {config.CURRENCY_NAME}**", view=view, ephemeral=True)
        except Exception as e:
            print(f"[ERROR] ChinchiroBetModal: {e}")
            await interaction.response.send_message("数字を入力してください。", ephemeral=True)

class ChinchiroGameView(discord.ui.View):
    def __init__(self, user, bet): super().__init__(timeout=60); self.user, self.bet = user, bet
    @discord.ui.button(label="🎲 サイコロを振る！", style=discord.ButtonStyle.success)
    async def roll(self, interaction, button):
        if interaction.user != self.user: return
        def get_rank(d):
            d.sort()
            if d == [1,1,1]: return "ピンゾロ", 1000
            if d[0]==d[1]==d[2]: return f"アラシ({d[0]})", 900+d[0]
            if d == [4,5,6]: return "シゴロ", 800
            if d == [1,2,3]: return "ヒフミ", -100
            if d[0]==d[1]: return f"出目{d[2]}", 100+d[2]
            if d[1]==d[2]: return f"出目{d[0]}", 100+d[0]
            if d[0]==d[2]: return f"出目{d[1]}", 100+d[1]
            return "役なし", 0
        bd, pd = [random.randint(1,6) for _ in range(3)], [random.randint(1,6) for _ in range(3)]
        bh, br = get_rank(bd); ph, pr = get_rank(pd)
        if pr > br:
            mul = 9 if ph=="ピンゾロ" else (4 if "アラシ" in ph else (2 if ph=="シゴロ" else (1 if "出目" in ph else 0)))
            await database.add_balance(self.user.id, int(self.bet*(1+mul))); await config.send_economy_log(interaction.guild, "🎲 カジノ(チンチロ)", f"{self.user.mention} がチンチロで {int(self.bet*mul)} {config.CURRENCY_NAME} 獲得しました。", user=self.user)
            res, color = f"🏆 勝ち！ {int(self.bet*mul)} {config.CURRENCY_NAME} 獲得", discord.Color.gold()
        elif pr < br: res, color = "💀 負け…", discord.Color.red()
        else: await database.add_balance(self.user.id, self.bet); await config.send_economy_log(interaction.guild, "🎲 カジノ(チンチロ)", f"{self.user.mention} がチンチロで引き分け、{self.bet} {config.CURRENCY_NAME} 返還されました。", user=self.user); res, color = "🤝 引き分け", discord.Color.light_grey()
        embed = discord.Embed(title="🎲 チンチロリン結果", color=color)
        embed.add_field(name="🤖 Bot", value=f"{bd} {bh}"); embed.add_field(name="👤 あなた", value=f"{pd} {ph}")
        embed.add_field(name="結果", value=res, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

class ChinchiroView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎲 チンチロリンで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_chinchiro_btn")
    async def play(self, it, btn): await it.response.send_modal(ChinchiroBetModal())

class CoinflipBetModal(discord.ui.Modal, title='コイントス：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, it: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000: return await it.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await it.response.defer(ephemeral=True)
            user_data = await database.get_user(it.user.id)
            now = datetime.datetime.now(config.JST); today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(it.user.id, today_str); count = 0
            if count >= 10: return await it.followup.send("本日の上限に達しました。", ephemeral=True)
            if await database.get_balance(it.user.id) < bet: return await it.followup.send("残高不足です。", ephemeral=True)
            await it.followup.send(f"🪙 **コイントス！** (本日 {count+1}/10回目)\n「表」か「裏」か？", view=CoinflipGameView(it.user, bet, count), ephemeral=True)
        except Exception as e:
            print(f"[ERROR] CoinflipBetModal: {e}")
            await it.response.send_message("数字を入力してください。", ephemeral=True)

class CoinflipGameView(discord.ui.View):
    def __init__(self, user, bet, count): super().__init__(timeout=60); self.user, self.bet, self.count = user, bet, count
    async def process(self, it, choice):
        if it.user != self.user: return
        if not await database.remove_balance(self.user.id, self.bet): return await it.response.edit_message(content="残高不足", view=None)
        await database.increment_gambling_count(self.user.id)
        await config.send_gambling_log(it.guild, self.user, "コイントス", self.bet, self.count + 1)
        res = random.choice(["heads", "tails"])
        if choice == res:
            await database.add_balance(self.user.id, int(self.bet*2.0)); await config.send_economy_log(it.guild, "🎲 カジノ(コイントス)", f"{self.user.mention} がコイントスで {int(self.bet*1.0)} {config.CURRENCY_NAME} 獲得しました。", user=self.user)
            msg, color = f"🏆 当たり！ {int(self.bet*2.0)} {config.CURRENCY_NAME} 獲得", discord.Color.gold()
        else: msg, color = f"💀 外れ… {self.bet} {config.CURRENCY_NAME} 没収", discord.Color.red()
        await it.response.edit_message(content=None, embed=discord.Embed(title="🪙 結果", description=f"結果: {'表' if res=='heads' else '裏'}\n{msg}", color=color), view=None)
    @discord.ui.button(label="表", emoji="⚪")
    async def heads(self, it, btn): await self.process(it, "heads")
    @discord.ui.button(label="裏", emoji="⚫")
    async def tails(self, it, btn): await self.process(it, "tails")

class CoinflipView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🪙 コイントスで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_coinflip_btn")
    async def play(self, it, btn): await it.response.send_modal(CoinflipBetModal())

class SlotBetModal(discord.ui.Modal, title='スロット：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, it: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000: return await it.response.send_message("不正な金額です。", ephemeral=True)
            await it.response.defer(ephemeral=True)
            user_data = await database.get_user(it.user.id)
            now = datetime.datetime.now(config.JST); today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(it.user.id, today_str); count = 0
            if count >= 10: return await it.followup.send("回数制限です。", ephemeral=True)
            if not await database.remove_balance(it.user.id, bet): return await it.followup.send("残高不足です。", ephemeral=True)
            await database.increment_gambling_count(it.user.id)
            await config.send_gambling_log(it.guild, it.user, "スロット", bet, count + 1)
            emo = ["🍒", "🍋", "🍉", "🔔", "⭐", "7️⃣", "💎", "🍀"]
            r = [random.choice(emo) for _ in range(3)]
            mul = 10 if r[0]==r[1]==r[2]=="7️⃣" else (5 if r[0]==r[1]==r[2]=="⭐" else (3 if r[0]==r[1]==r[2] else (1.5 if len(set(r))<3 else 0)))
            win = int(bet * mul)
            if win > 0:
                await database.add_balance(it.user.id, win)
                await config.send_economy_log(it.guild, "🎲 カジノ(スロット)", f"{it.user.mention} がスロットで {win} {config.CURRENCY_NAME} 獲得しました。", user=it.user)
            embed = discord.Embed(title="🎰 スロット結果", description=f"{r}\n{'🏆 当たり！' if win>0 else '💀 ハズレ'} {win} 獲得", color=discord.Color.gold() if win>0 else discord.Color.red())
            await it.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"[ERROR] SlotBetModal: {e}")
            await it.response.send_message("エラー", ephemeral=True)

class SlotView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎰 スロットで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_slot_btn")
    async def play(self, it, btn): await it.response.send_modal(SlotBetModal())

def create_blackjack_deck():
    suits = ["♠️", "♥️", "♦️", "♣️"]
    values = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    deck = [{"suit": suit, "value": val} for suit in suits for val in values]
    random.shuffle(deck)
    return deck

def calculate_blackjack_score(hand):
    score = 0
    aces = 0
    for card in hand:
        val = card["value"]
        if val in ["J", "Q", "K"]:
            score += 10
        elif val == "A":
            score += 11
            aces += 1
        else:
            score += int(val)
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

class BlackjackBetModal(discord.ui.Modal, title='ブラックジャック：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000:
                return await interaction.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(config.JST)
            today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str); count = 0
            if count >= 10:
                return await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
            if await database.get_balance(interaction.user.id) < bet:
                return await interaction.followup.send("残高不足です。", ephemeral=True)
            
            await database.remove_balance(interaction.user.id, bet)
            await database.increment_gambling_count(interaction.user.id)
            await config.send_gambling_log(interaction.guild, interaction.user, "ブラックジャック", bet, count + 1)
            
            view = BlackjackGameView(interaction.user, bet)
            initial_blackjack_embed = await view.check_initial_blackjack()
            if initial_blackjack_embed:
                await interaction.followup.send(f"🃏 **ブラックジャック開始！** (本日 {count+1}/10回目)\n賭け金: **{bet} {config.CURRENCY_NAME}**", embed=initial_blackjack_embed, ephemeral=True)
            else:
                embed = view.build_embed(description="カードが配られました。どうしますか？")
                msg = await interaction.followup.send(f"🃏 **ブラックジャック開始！** (本日 {count+1}/10回目)\n賭け金: **{bet} {config.CURRENCY_NAME}**", embed=embed, view=view, ephemeral=True)
                view.message = msg
        except ValueError:
            try:
                await interaction.followup.send("金額は半角数字で入力してください。", ephemeral=True)
            except Exception:
                await interaction.response.send_message("金額は半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] BlackjackBetModal: {e}")
            try:
                await interaction.followup.send("エラーが発生しました。", ephemeral=True)
            except Exception:
                await interaction.response.send_message("エラーが発生しました。", ephemeral=True)

class BlackjackGameView(discord.ui.View):
    def __init__(self, user, bet):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet
        self.deck = create_blackjack_deck()
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.message = None

    def format_hand(self, hand, hide_second=False):
        if hide_second:
            return f"{hand[0]['suit']} **{hand[0]['value']}**,  ❓ **?**"
        return ", ".join(f"{card['suit']} **{card['value']}**" for card in hand)

    def get_visible_score(self, hand, hide_second=False):
        if hide_second:
            return calculate_blackjack_score([hand[0]])
        return calculate_blackjack_score(hand)

    def build_embed(self, title="🃏 ブラックジャック", color=0x3498db, description="", is_final=False):
        embed = discord.Embed(title=title, color=color, description=description)
        
        dealer_cards = self.format_hand(self.dealer_hand, hide_second=not is_final)
        dealer_score = self.get_visible_score(self.dealer_hand, hide_second=not is_final)
        embed.add_field(
            name=f"🤖 ディーラー (Score: {dealer_score}{' + ?' if not is_final else ''})",
            value=dealer_cards,
            inline=False
        )
        
        player_cards = self.format_hand(self.player_hand)
        player_score = calculate_blackjack_score(self.player_hand)
        embed.add_field(
            name=f"👤 あなた (Score: {player_score})",
            value=player_cards,
            inline=False
        )
        return embed

    async def check_initial_blackjack(self):
        player_score = calculate_blackjack_score(self.player_hand)
        if player_score == 21:
            dealer_score = calculate_blackjack_score(self.dealer_hand)
            if dealer_score == 21:
                win_amount = self.bet
                await database.add_balance(self.user.id, win_amount)
                title = "🤝 引き分け"
                color = discord.Color.light_grey()
                description = f"双方ブラックジャック！引き分け（プッシュ）です。\n**{win_amount} {config.CURRENCY_NAME}** が戻ります。"
            else:
                win_amount = int(self.bet * 2.5)
                await database.add_balance(self.user.id, win_amount)
                title = "🃏 ブラックジャック！"
                color = discord.Color.gold()
                description = f"ブラックジャック達成！\n**{win_amount} {config.CURRENCY_NAME}** 獲得！"
            return self.build_embed(title=title, color=color, description=description, is_final=True)
        return None

    async def on_timeout(self):
        for child in self.children:
            if not child.disabled:
                break
        else:
            return
        await self.resolve_stand(None)

    @discord.ui.button(label="カードを引く (Hit)", style=discord.ButtonStyle.success, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        
        self.player_hand.append(self.deck.pop())
        score = calculate_blackjack_score(self.player_hand)
        
        if score > 21:
            await self.resolve_bust(interaction)
        elif score == 21:
            await self.resolve_stand(interaction)
        else:
            embed = self.build_embed(description="どうしますか？")
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="勝負する (Stand)", style=discord.ButtonStyle.danger, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        
        await self.resolve_stand(interaction)

    async def resolve_bust(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        embed = self.build_embed(
            title="💀 バスト！",
            color=discord.Color.red(),
            description=f"合計が21を超えました！\n**{self.bet} {config.CURRENCY_NAME}** 没収...",
            is_final=True
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def resolve_stand(self, interaction: discord.Interaction = None):
        for child in self.children:
            child.disabled = True
            
        player_score = calculate_blackjack_score(self.player_hand)
        while calculate_blackjack_score(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
            
        dealer_score = calculate_blackjack_score(self.dealer_hand)
        
        win_amount = 0
        if dealer_score > 21:
            win_amount = self.bet * 2
            title = "🏆 勝ち！"
            color = discord.Color.gold()
            description = f"ディーラーがバストしました！\n**{win_amount} {config.CURRENCY_NAME}** 獲得！"
        elif player_score > dealer_score:
            win_amount = self.bet * 2
            title = "🏆 勝ち！"
            color = discord.Color.gold()
            description = f"ディーラーを上回りました！\n**{win_amount} {config.CURRENCY_NAME}** 獲得！"
        elif player_score < dealer_score:
            title = "💀 負け…"
            color = discord.Color.red()
            description = f"ディーラーに敗北しました...\n**{self.bet} {config.CURRENCY_NAME}** 没収..."
        else:
            win_amount = self.bet
            title = "🤝 引き分け"
            color = discord.Color.light_grey()
            description = f"引き分け（プッシュ）です。\n**{win_amount} {config.CURRENCY_NAME}** が戻ります。"
            
        if win_amount > 0:
            await database.add_balance(self.user.id, win_amount)
            
        embed = self.build_embed(title=title, color=color, description=description, is_final=True)
        
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass

class BlackjackView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🃏 ブラックジャックで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_blackjack_btn")
    async def play(self, it, btn):
        await it.response.send_modal(BlackjackBetModal())

def check_roulette_win(number, bet_type, target_val=None):
    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    black_numbers = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
    
    if number == 0:
        if bet_type == "number" and target_val == 0:
            return True, 36
        return False, 0

    if bet_type == "red":
        is_win = number in red_numbers
        return is_win, 2 if is_win else 0
    elif bet_type == "black":
        is_win = number in black_numbers
        return is_win, 2 if is_win else 0
    elif bet_type == "even":
        is_win = number % 2 == 0
        return is_win, 2 if is_win else 0
    elif bet_type == "odd":
        is_win = number % 2 != 0
        return is_win, 2 if is_win else 0
    elif bet_type == "low":
        is_win = 1 <= number <= 18
        return is_win, 2 if is_win else 0
    elif bet_type == "high":
        is_win = 19 <= number <= 36
        return is_win, 2 if is_win else 0
    elif bet_type == "dozen1":
        is_win = 1 <= number <= 12
        return is_win, 3 if is_win else 0
    elif bet_type == "dozen2":
        is_win = 13 <= number <= 24
        return is_win, 3 if is_win else 0
    elif bet_type == "dozen3":
        is_win = 25 <= number <= 36
        return is_win, 3 if is_win else 0
    elif bet_type == "number":
        is_win = number == target_val
        return is_win, 36 if is_win else 0
        
    return False, 0

def format_bet_type(bet_type, target_num=None):
    names = {
        "red": "🔴 赤 (Red)",
        "black": "⚫ 黒 (Black)",
        "even": "🔢 偶数 (Even)",
        "odd": "🔣 奇数 (Odd)",
        "low": "⬇️ ロー (Low: 1-18)",
        "high": "⬆️ ハイ (High: 19-36)",
        "dozen1": "1️⃣ 第1ダズン (1-12)",
        "dozen2": "2️⃣ 第2ダズン (13-24)",
        "dozen3": "3️⃣ 第3ダズン (25-36)",
    }
    if bet_type == "number":
        return f"🎯 数字 1点賭け: {target_num}"
    return names.get(bet_type, bet_type)

class RouletteBetModal(discord.ui.Modal, title='ルーレット：賭け金入力'):
    bet_input = discord.ui.TextInput(label='賭ける金額', placeholder='例: 1000', max_length=10, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value)
            if bet <= 0 or bet > 100000:
                return await interaction.response.send_message("1〜100,000の間で入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            
            user_data = await database.get_user(interaction.user.id)
            now = datetime.datetime.now(config.JST)
            today_str = now.strftime("%Y-%m-%d")
            count = user_data.get("chinchiro_count", 0)
            
            if user_data.get("chinchiro_last_date") != today_str:
                await database.reset_gambling_count(interaction.user.id, today_str)
                count = 0
                
            if count >= 10:
                return await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
                
            if await database.get_balance(interaction.user.id) < bet:
                return await interaction.followup.send("残高不足です。", ephemeral=True)
            
            view = RouletteBetTypeView(interaction.user, bet, count)
            embed = discord.Embed(
                title="🎡 ルーレット",
                description=(
                    f"**現在のベット額**: {bet} {config.CURRENCY_NAME}\n\n"
                    "賭け先を以下から選択してください。\n"
                    "- 赤 / 黒 / 偶数 / 奇数 / ロー / ハイ: **配当2.0倍**\n"
                    "- ダズン (1-12, 13-24, 25-36): **配当3.0倍**\n"
                    "- 数字1点賭け (0-36): **配当36.0倍**"
                ),
                color=0x3498db
            )
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.message = msg
        except ValueError:
            await interaction.followup.send("金額は半角数字で入力してください。", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] RouletteBetModal: {e}")

class RouletteBetTypeView(discord.ui.View):
    def __init__(self, user, bet, count):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet
        self.count = count
        self.message = None
        self.add_item(RouletteTypeSelect())

    @discord.ui.button(label="🎯 数字1点賭け (0-36)", style=discord.ButtonStyle.secondary, row=1)
    async def bet_number_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        await interaction.response.send_modal(RouletteNumberModal(self.bet, self.count, self.message))

class RouletteTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="🔴 赤に賭ける", description="配当 2.0倍", value="red"),
            discord.SelectOption(label="⚫ 黒に賭ける", description="配当 2.0倍", value="black"),
            discord.SelectOption(label="🔢 偶数に賭ける", description="配当 2.0倍 (0は除く)", value="even"),
            discord.SelectOption(label="🔣 奇数に賭ける", description="配当 2.0倍", value="odd"),
            discord.SelectOption(label="⬇️ ローに賭ける (1-18)", description="配当 2.0倍", value="low"),
            discord.SelectOption(label="⬆️ ハイに賭ける (19-36)", description="配当 2.0倍", value="high"),
            discord.SelectOption(label="1️⃣ 第1ダズン (1-12)", description="配当 3.0倍", value="dozen1"),
            discord.SelectOption(label="2️⃣ 第2ダズン (13-24)", description="配当 3.0倍", value="dozen2"),
            discord.SelectOption(label="3️⃣ 第3ダズン (25-36)", description="配当 3.0倍", value="dozen3"),
        ]
        super().__init__(placeholder="賭け先を選択してください...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if interaction.user != view.user:
            return await interaction.response.send_message("これはあなたのゲームではありません。", ephemeral=True)
        await run_roulette_game(interaction, view.user, view.bet, view.count, self.values[0], None)

class RouletteNumberModal(discord.ui.Modal, title='ルーレット：数字1点賭け'):
    number_input = discord.ui.TextInput(label='賭ける数字 (0〜36)', placeholder='例: 7', max_length=2, required=True)
    def __init__(self, bet, count, game_msg):
        super().__init__()
        self.bet = bet
        self.count = count
        self.game_msg = game_msg

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_num = int(self.number_input.value)
            if target_num < 0 or target_num > 36:
                return await interaction.response.send_message("0から36の間の数字を入力してください。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            await run_roulette_game(interaction, interaction.user, self.bet, self.count, "number", target_num)
        except ValueError:
            await interaction.response.send_message("数字は半角で入力してください。", ephemeral=True)

async def run_roulette_game(interaction: discord.Interaction, user, bet, count, bet_type, target_num):
    user_data = await database.get_user(user.id)
    now = datetime.datetime.now(config.JST)
    today_str = now.strftime("%Y-%m-%d")
    current_count = user_data.get("chinchiro_count", 0)
    
    if user_data.get("chinchiro_last_date") != today_str:
        await database.reset_gambling_count(user.id, today_str)
        current_count = 0
        
    if current_count >= 10:
        try:
            await interaction.followup.send("本日の上限(10回)に達しました。", ephemeral=True)
        except Exception:
            await interaction.response.send_message("本日の上限(10回)に達しました。", ephemeral=True)
        return
        
    if not await database.remove_balance(user.id, bet):
        try:
            await interaction.followup.send("残高不足です。", ephemeral=True)
        except Exception:
            await interaction.response.send_message("残高不足です。", ephemeral=True)
        return
        
    await database.increment_gambling_count(user.id)
    await config.send_gambling_log(interaction.guild, user, "ルーレット", bet, current_count + 1)
    
    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    
    def get_color_emoji(n):
        if n == 0:
            return "🟢0"
        return f"🔴{n}" if n in red_numbers else f"⚫{n}"
        
    spin_sequence = []
    for _ in range(5):
        dummy_num = random.randint(0, 36)
        spin_sequence.append(get_color_emoji(dummy_num))
        
    final_number = random.randint(0, 36)
    
    embed = discord.Embed(
        title="🎡 ルーレット回転中...",
        description=f"賭け先: **{format_bet_type(bet_type, target_num)}**\n賭け金: **{bet} {config.CURRENCY_NAME}**\n\n"
                    f"spinning: [ {' ➔ '.join(spin_sequence[:3])} ]",
        color=0x3498db
    )
    
    if not interaction.is_expired():
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=None)
    else:
        await interaction.channel.send(embed=embed)
        
    await asyncio.sleep(1.2)
    
    embed.title = "🎡 ルーレット減速中..."
    embed.description = f"賭け先: **{format_bet_type(bet_type, target_num)}**\n賭け金: **{bet} {config.CURRENCY_NAME}**\n\n" \
                        f"spinning: [ {' ➔ '.join(spin_sequence[2:])} ➔ ??? ]"
    
    await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed)
    
    await asyncio.sleep(1.2)
    
    is_win, multiplier = check_roulette_win(final_number, bet_type, target_num)
    win_amount = int(bet * multiplier) if is_win else 0
    
    if win_amount > 0:
        await database.add_balance(user.id, win_amount)
        
    color_emoji = get_color_emoji(final_number)
    if is_win:
        title = "🏆 当たり！"
        color = discord.Color.gold()
        desc = f"結果: **{color_emoji}**\n賭け先: **{format_bet_type(bet_type, target_num)}**\n\n" \
               f"見事に的中しました！\n**{win_amount} {config.CURRENCY_NAME}** 獲得！"
    else:
        title = "💀 ハズレ…"
        color = discord.Color.red()
        desc = f"結果: **{color_emoji}**\n賭け先: **{format_bet_type(bet_type, target_num)}**\n\n" \
               f"残念、ハズレです...\n**{bet} {config.CURRENCY_NAME}** 没収。"
               
    embed = discord.Embed(title=title, description=desc, color=color)
    embed.set_footer(text=f"本日 {current_count+1}/10回目")
    
    await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed)

class RouletteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🎡 ルーレットで遊ぶ", style=discord.ButtonStyle.primary, custom_id="persistent_roulette_btn")
    async def play(self, it, btn):
        await it.response.send_modal(RouletteBetModal())
