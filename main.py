import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import sys
import threading
import asyncio
import random
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Web Server ---
app = Flask('')
@app.route('/')
def home(): return "Extreme Stealth Bot is Online! 🕵️"
def run_web(): app.run(host='0.0.0.0', port=8080)

# --- Bot Class ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True 
        super().__init__(command_prefix="!", intents=intents)
        self.queue = {} 

    async def setup_hook(self):
        await self.tree.sync()

    async def restart_bot(self):
        await self.close()
        sys.exit(0)

bot = MyBot()

# --- รายชื่อ User-Agent แบบเจาะจงที่ YouTube ไม่ค่อยบล็อก ---
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
]

def get_ydl_options():
    return {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch',
        'user_agent': random.choice(USER_AGENTS),
        'nocheckcertificate': True,
        'source_address': '0.0.0.0',
        'extract_flat': False, # บังคับให้ดึงข้อมูลเต็ม เพื่อเลี่ยงการโดนเช็คว่าเป็นบอทแบบเบา
        # เพิ่ม headers เลียนแบบคนคลิกมาจากเว็บอื่น
        'http_headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        }
    }

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -buffer_size 30M' # เพิ่มบัฟเฟอร์ให้เพลงรีมิกซ์ยาวๆ ไม่กระตุก
}

def play_next(interaction, guild_id):
    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        next_song = bot.queue[guild_id].pop(0)
        vc = interaction.guild.voice_client
        if vc:
            source = discord.FFmpegOpusAudio.from_probe(next_song['url'], **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: play_next(interaction, guild_id))
            coro = interaction.channel.send(f"⏭️ เพลงต่อไปมาแล้ว: **{next_song['title']}**")
            asyncio.run_coroutine_threadsafe(coro, bot.loop)

@bot.event
async def on_ready():
    server_count = len(bot.guilds)
    await bot.change_presence(activity=discord.Streaming(
        name=f"อยู่ใน {server_count} เซิร์ฟเวอร์ | /play", 
        url="https://www.twitch.tv/directory" 
    ))
    scheduler = AsyncIOScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(bot.restart_bot, CronTrigger(hour=0, minute=0))
    scheduler.start()

@bot.tree.command(name="play", description="เล่นเพลง")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ เข้าห้องเสียงก่อนนะ!")
    
    vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
    guild_id = interaction.guild.id
    if guild_id not in bot.queue: bot.queue[guild_id] = []

    # เน้นหาจาก YouTube เป็นหลัก (สำหรับรีมิกซ์)
    with yt_dlp.YoutubeDL(get_ydl_options()) as ydl:
        try:
            info = ydl.extract_info(search, download=False)
            if 'entries' in info: info = info['entries'][0]
            
            song = {'url': info['url'], 'title': info['title']}
            if vc.is_playing() or vc.is_paused():
                bot.queue[guild_id].append(song)
                await interaction.followup.send(f"✅ คิวเพลงรีมิกซ์: **{info['title']}**")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, guild_id))
                await interaction.followup.send(f"🎶 กำลังเล่นเพลงรีมิกซ์: **{info['title']}**")
        except Exception as e:
            # ถ้า YT บล็อกจริงๆ ถึงค่อยไปหา SC (ซึ่งรีมิกซ์อาจไม่มี)
            await interaction.followup.send("❌ โดน YouTube บล็อกชั่วคราว ลองกดอีกทีนะ")

@bot.tree.command(name="skip", description="ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงรีมิกซ์ให้แล้ว!")

@bot.tree.command(name="stop", description="หยุดเล่น")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ ปิดเพลงเรียบร้อย!")

# ... (Pause / Resume ใส่เพิ่มได้เหมือนโค้ดเก่า)

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(os.getenv('TOKEN'))

