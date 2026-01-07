import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import threading
import asyncio
from flask import Flask
from static_ffmpeg import add_paths

# --- ตั้งค่าระบบเสียงสำหรับ Render ---
add_paths() 

app = Flask('')
@app.route('/')
def home(): return "บอทออนไลน์พร้อมใช้งานแล้วครับ 🎶"
def run_web(): app.run(host='0.0.0.0', port=8080)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.queue = {} 
        self.loop_mode = {} 

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

# การตั้งค่าเสียง FFmpeg
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def get_ydl_opts():
    return {
        'format': 'bestaudio/best',
        'default_search': 'scsearch',
        'noplaylist': True,
        'quiet': True,
        'nocheckcertificate': True,
    }

def play_next(interaction, guild_id, last_song):
    vc = interaction.guild.voice_client
    if not vc: return

    if bot.loop_mode.get(guild_id, False) and last_song:
        if guild_id not in bot.queue: bot.queue[guild_id] = []
        bot.queue[guild_id].append(last_song)

    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        next_song = bot.queue[guild_id].pop(0)
        source = discord.FFmpegOpusAudio.from_probe(next_song['url'], **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: play_next(interaction, guild_id, next_song))
        
        coro = interaction.channel.send(f"⏭️ **เพลงถัดไป:** {next_song['title']}")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    else:
        coro = interaction.channel.send("🎵 รายการเพลงในคิวหมดแล้วครับ")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/play"))
    print(f'✅ ระบบเริ่มทำงาน: {bot.user.name}')

# --- คำสั่ง Slash Commands (ฉบับสุภาพ) ---

@bot.tree.command(name="play", description="ค้นหาและเล่นเพลงจากชื่อเพลงหรือลิงก์")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ กรุณาเข้าห้องเสียงก่อนใช้งานคำสั่งครับ")

    with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
        try:
            info = ydl.extract_info(f"scsearch:{search}", download=False)
            if not info['entries']:
                info = ydl.extract_info(f"ytsearch:{search}", download=False)
            
            if 'entries' in info: info = info['entries'][0]
            song = {'url': info['url'], 'title': info['title']}

            vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()

            if vc.is_playing() or vc.is_paused():
                guild_id = interaction.guild.id
                if guild_id not in bot.queue: bot.queue[guild_id] = []
                bot.queue[guild_id].append(song)
                await interaction.followup.send(f"✅ เพิ่มเพลง **{song['title']}** ลงในคิวเรียบร้อยครับ")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, interaction.guild.id, song))
                await interaction.followup.send(f"🎶 กำลังเริ่มเล่นเพลง: **{song['title']}**")
        except Exception:
            await interaction.followup.send("❌ ขออภัยครับ ไม่สามารถดึงข้อมูลเพลงได้ในขณะนี้")

@bot.tree.command(name="queue", description="แสดงรายการเพลงทั้งหมดที่อยู่ในคิว")
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in bot.queue or len(bot.queue[guild_id]) == 0:
        return await interaction.response.send_message("ไม่มีรายการเพลงในคิวขณะนี้ครับ")
    
    msg = "**🎶 รายการเพลงในคิว:**\n"
    for i, s in enumerate(bot.queue[guild_id][:10], 1):
        msg += f"{i}. {s['title']}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="loop", description="เปิดหรือปิดระบบเล่นเพลงวนซ้ำ")
async def loop(interaction: discord.Interaction):
    gid = interaction.guild.id
    bot.loop_mode[gid] = not bot.loop_mode.get(gid, False)
    status = "เปิดใช้งาน" if bot.loop_mode[gid] else "ปิดใช้งาน"
    await interaction.response.send_message(f"🔄 ระบบเล่นวนซ้ำ: **{status}** เรียบร้อยครับ")

@bot.tree.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่ไปยังเพลงถัดไป")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงปัจจุบันเรียบร้อยครับ")
    else:
        await interaction.response.send_message("ไม่มีเพลงที่กำลังเล่นอยู่ครับ")

@bot.tree.command(name="stop", description="หยุดเล่นเพลงและให้บอทออกจากห้องเสียง")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    bot.loop_mode[interaction.guild.id] = False
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ หยุดเล่นเพลงและออกจากห้องเสียงเรียบร้อยครับ")
    else:
        await interaction.response.send_message("บอทไม่ได้อยู่ในห้องเสียงครับ")

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(os.getenv('TOKEN'))
