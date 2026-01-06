import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import sys
import threading
import asyncio
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- 1. Web Server (Keep-Alive) ---
app = Flask('')
@app.route('/')
def home():
    return "Bot is Online! 🚀"

def run_web():
    app.run(host='0.0.0.0', port=8080)

# --- 2. Setup Bot Class ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True  # สำหรับนับจำนวนเซิร์ฟเวอร์
        super().__init__(command_prefix="!", intents=intents)
        self.queue = {} # เก็บเพลงแยกแต่ละเซิร์ฟเวอร์

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Slash Commands Synced!")

    async def restart_bot(self):
        print("🔄 Restarting to clear RAM...")
        await self.close()
        sys.exit(0)

bot = MyBot()

# --- 3. Music Settings ---
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'ytsearch' # ค้นหาจากชื่อถ้าไม่ใช่ลิงก์
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -buffer_size 10M'
}

# ฟังก์ชันเล่นเพลงถัดไปในคิว
def play_next(interaction, guild_id):
    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        next_song = bot.queue[guild_id].pop(0)
        vc = interaction.guild.voice_client
        if vc:
            source = discord.FFmpegOpusAudio.from_probe(next_song['url'], **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: play_next(interaction, guild_id))
            asyncio.run_coroutine_threadsafe(
                interaction.channel.send(f"⏭️ **เพลงถัดไป:** {next_song['title']}"),
                bot.loop
            )

# --- 4. Events ---
@bot.event
async def on_ready():
    # แสดงจำนวนเซิร์ฟเวอร์บนโปรไฟล์
    server_count = len(bot.guilds)
    activity = discord.Activity(
        type=discord.ActivityType.listening, 
        name=f"{server_count} servers | /play"
    )
    await bot.change_presence(activity=activity)
    
    print(f'✅ Logged in as {bot.user.name}')
    
    # ระบบ Auto-Restart ตอนเที่ยงคืนไทย
    scheduler = AsyncIOScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(bot.restart_bot, CronTrigger(hour=0, minute=0))
    scheduler.start()

# --- 5. Commands ---

@bot.tree.command(name="play", description="เล่นเพลงจากชื่อหรือลิงก์ YouTube")
@app_commands.describe(search="พิมพ์ชื่อเพลงหรือวางลิงก์ที่นี่")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ คุณต้องเข้าห้องเสียงก่อน!")
    
    vc = interaction.guild.voice_client
    if not vc:
        vc = await interaction.user.voice.channel.connect()

    guild_id = interaction.guild.id
    if guild_id not in bot.queue:
        bot.queue[guild_id] = []

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = ydl.extract_info(search, download=False)
            if 'entries' in info: # ถ้าเป็นชื่อเพลง จะได้เป็น list
                info = info['entries'][0]
            
            song_data = {'url': info['url'], 'title': info['title']}
            
            if vc.is_playing() or vc.is_paused():
                bot.queue[guild_id].append(song_data)
                await interaction.followup.send(f"✅ เพิ่มลงคิว: **{info['title']}**")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song_data['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, guild_id))
                await interaction.followup.send(f"🎶 กำลังเล่น: **{info['title']}**")
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")

@bot.tree.command(name="skip", description="ข้ามเพลงปัจจุบัน")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงให้แล้วครับ!")
    else:
        await interaction.response.send_message("❌ ไม่มีเพลงเล่นอยู่")

@bot.tree.command(name="queue", description="ดูรายการเพลงในคิว")
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        text = "\n".join([f"{i+1}. {s['title']}" for i, s in enumerate(bot.queue[guild_id])])
        await interaction.response.send_message(f"📋 **คิวเพลง:**\n{text}")
    else:
        await interaction.response.send_message("📋 คิวว่างเปล่า")

@bot.tree.command(name="stop", description="หยุดเพลงและล้างคิว")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        await interaction.response.send_message("⏹️ หยุดเล่นและออกจากห้องแล้ว")
    else:
        await interaction.response.send_message("❌ บอทไม่ได้อยู่ในห้องเสียง")

# --- 6. Start Bot ---
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    token = os.getenv('TOKEN')
    bot.run(token)
