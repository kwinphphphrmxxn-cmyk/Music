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

# --- Web Server (สำหรับ Render) ---
app = Flask('')
@app.route('/')
def home(): return "Music Bot is Active! 🚀"
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
        print("✅ Sync คำสั่งเรียบร้อย!")

    async def restart_bot(self):
        await self.close()
        sys.exit(0)

bot = MyBot()

# --- Stealth & Music Config ---
USER_AGENTS = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36']
def get_ydl_options():
    return {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch',
        'user_agent': random.choice(USER_AGENTS),
        'source_address': '0.0.0.0',
    }

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -buffer_size 20M'
}

# --- ระบบเล่นเพลงถัดไปอัตโนมัติ ---
def play_next(interaction, guild_id):
    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        next_song = bot.queue[guild_id].pop(0)
        vc = interaction.guild.voice_client
        if vc:
            source = discord.FFmpegOpusAudio.from_probe(next_song['url'], **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: play_next(interaction, guild_id))
            
            coro = interaction.channel.send(f"⏭️ มาแล้วๆ เพลงต่อไป: **{next_song['title']}**")
            fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
            try: fut.result()
            except: pass

# --- สถานะสตรีมเมอร์ (ม่วง) ---
@bot.event
async def on_ready():
    server_count = len(bot.guilds)
    # ใส่ลิงก์ Twitch ของคุณตรงนี้ (เพื่อให้ขึ้นสีม่วง)
    await bot.change_presence(activity=discord.Streaming(
        name=f"อยู่ใน {server_count} เซิร์ฟเวอร์ | /play", 
        url="https://www.twitch.tv/directory" 
    ))
    
    print(f'✅ บอท {bot.user.name} ออนไลน์แล้วใน {server_count} เซิร์ฟเวอร์')
    
    scheduler = AsyncIOScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(bot.restart_bot, CronTrigger(hour=0, minute=0))
    scheduler.start()

# --- Commands (เล่นเพลง/ข้าม/หยุด/พัก) ---
@bot.tree.command(name="play", description="เล่นเพลง")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    if not interaction.user.voice:
        return await interaction.followup.send("❌ เข้าห้องเสียงก่อนนะ เดี๋ยวหาว่าบอทหลอน")
    
    vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
    guild_id = interaction.guild.id
    if guild_id not in bot.queue: bot.queue[guild_id] = []

    with yt_dlp.YoutubeDL(get_ydl_options()) as ydl:
        try:
            info = ydl.extract_info(search, download=False)
            if 'entries' in info: info = info['entries'][0]
            song = {'url': info['url'], 'title': info['title']}

            if vc.is_playing() or vc.is_paused():
                bot.queue[guild_id].append(song)
                await interaction.followup.send(f"✅ เพิ่มลงคิวให้แล้ว: **{info['title']}**")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, guild_id))
                await interaction.followup.send(f"🎶 กำลังเริ่มเล่น: **{info['title']}** จ้า")
        except Exception:
            await interaction.followup.send(f"❌ เหมือน YouTube จะมีปัญหา ลองใหม่อีกทีนะ")

@bot.tree.command(name="skip", description="ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop() # หยุดเพลงนี้เพื่อให้ play_next ทำงานต่อทันที
        await interaction.response.send_message("⏭️ ข้ามให้แล้วจ้า!")
    else:
        await interaction.response.send_message("❌ ไม่มีเพลงให้ข้ามนะ")

@bot.tree.command(name="pause", description="พักเพลง")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ พักเพลงไว้แป๊บนึงนะ")
    else:
        await interaction.response.send_message("❌ ไม่มีเพลงเล่นอยู่จ้า")

@bot.tree.command(name="resume", description="เล่นต่อ")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ มาฟังต่อกันเลย!")
    else:
        await interaction.response.send_message("❌ เพลงไม่ได้พักอยู่นะ")

@bot.tree.command(name="stop", description="หยุดเล่น")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ ปิดเพลงให้แล้ว ไว้มาฟังใหม่นะ!")

# --- Start ---
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(os.getenv('TOKEN'))
