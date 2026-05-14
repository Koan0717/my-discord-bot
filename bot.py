import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

# .envファイルから環境変数を読み込む
load_dotenv()

# トークンの取得
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# intentsの構成（Server Members IntentとMessage Content Intentを有効にする必要があります）
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# チャンネルIDの設定
WELCOME_CHANNEL_ID = 1407976271069057137
INTRO_CHANNEL_ID = 1413106917676552225

@bot.event
async def on_ready():
    print('=================================')
    print(f'ログイン成功: {bot.user}')
    print('Botの準備が完了しました！')
    print('=================================')

@bot.event
async def on_member_join(member):
    welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        # メンション付きで挨拶メッセージを送信
        message_content = f"{member.mention} さん、サーバーへようこそ！\n" \
                          f"以下のテンプレートを使って、<#{INTRO_CHANNEL_ID}> チャンネルで自己紹介をお願いします！\n\n" \
                          f"```\n" \
                          f"【名前】\n" \
                          f"【年齢】\n" \
                          f"【趣味】\n" \
                          f"【希望ロール】\n" \
                          f"【誰の紹介orどこから】\n" \
                          f"```"
        await welcome_channel.send(message_content)

@bot.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author == bot.user:
        return

    # 自己紹介チャンネルでの投稿かチェック
    if message.channel.id == INTRO_CHANNEL_ID:
        # メッセージに【名前】が含まれているかチェック
        if "【名前】" in message.content:
            # メンバーに付与するロールを取得
            role = discord.utils.get(message.guild.roles, name="会員")
            if role:
                try:
                    await message.author.add_roles(role)
                    
                    # 挨拶チャンネルの元の案内メッセージを削除する処理
                    welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
                    if welcome_channel:
                        # 直近100件のメッセージ履歴から、Botが送信した該当ユーザーへのメンションメッセージを探す
                        async for msg in welcome_channel.history(limit=100):
                            if msg.author == bot.user and message.author in msg.mentions:
                                await msg.delete()
                                break
                except discord.Forbidden:
                    print("権限が不足しているため、ロールを付与できませんでした。Botのロール位置を確認してください。")
                except discord.HTTPException as e:
                    print(f"ロールの付与中にエラーが発生しました: {e}")
            else:
                print("「会員」という名前のロールが見つかりませんでした。")

    # 他のコマンドも処理できるようにする
    await bot.process_commands(message)

# Flaskサーバーを起動して24時間稼働を維持する
keep_alive()

if __name__ == '__main__':
    if DISCORD_TOKEN and DISCORD_TOKEN != "ここにBotのトークンを貼り付けてください":
        bot.run(DISCORD_TOKEN)
    else:
        print("エラー: DISCORD_TOKENが設定されていません。.envファイルを確認してください。")
