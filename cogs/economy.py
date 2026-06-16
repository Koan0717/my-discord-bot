import discord
from discord.ext import commands
from discord import app_commands
import database
import config

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="balance", description="自分の所持金を確認します（管理者は他のユーザーも確認可能）")
    async def balance(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        if target_user != interaction.user and not config.has_admin_role(self.bot, interaction.user):
            await interaction.response.send_message("他人の残高を確認する権限がありません。", ephemeral=True)
            return
        bal = await database.get_balance(target_user.id)
        if target_user == interaction.user:
            await interaction.response.send_message(f"あなたの所持金は **{bal} {config.CURRENCY_NAME}** です。", ephemeral=True)
        else:
            await interaction.response.send_message(f"{target_user.display_name} の所持金は **{bal} {config.CURRENCY_NAME}** です。", ephemeral=True)

    @app_commands.command(name="pay", description="他のユーザーに通貨を送ります（最大10人まで同時選択可能）")
    @app_commands.describe(
        target1="送金先1",
        amount="1人あたりの金額",
        target2="送金先2（任意）",
        target3="送金先3（任意）",
        target4="送金先4（任意）",
        target5="送金先5（任意）",
        target6="送金先6（任意）",
        target7="送金先7（任意）",
        target8="送金先8（任意）",
        target9="送金先9（任意）",
        target10="送金先10（任意）"
    )
    async def pay(
        self,
        interaction: discord.Interaction, 
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
        if amount <= 0:
            await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
            return
            
        targets = [t for t in [target1, target2, target3, target4, target5, target6, target7, target8, target9, target10] if t is not None]
        valid_targets = []
        
        for t in targets:
            if t.id == interaction.user.id:
                await interaction.response.send_message("自分自身は送金先に含めることができません。", ephemeral=True)
                return
            if t.bot:
                await interaction.response.send_message("Botは送金先に含めることができません。", ephemeral=True)
                return
            if t not in valid_targets:
                valid_targets.append(t)
                
        total_amount = amount * len(valid_targets)
        
        await interaction.response.defer()
        success = await database.remove_balance(interaction.user.id, total_amount)
        if not success:
            await interaction.followup.send(f"残高が不足しています。（合計 {total_amount} {config.CURRENCY_NAME} 必要です）", ephemeral=True)
            return
            
        for t in valid_targets:
            await database.add_balance(t.id, amount)
            await interaction.followup.send(f"{t.mention} に **{amount} {config.CURRENCY_NAME}** を送金しました！")
            await config.send_economy_log(
                interaction.guild, 
                "💸 送金・お渡し", 
                f"{interaction.user.mention} が {t.mention} に **{amount} {config.CURRENCY_NAME}** を送金しました。",
                user=interaction.user
            )

async def setup(bot):
    await bot.add_cog(Economy(bot))
