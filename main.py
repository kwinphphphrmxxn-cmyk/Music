import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import threading
import asyncio
from flask import Flask
from static_ffmpeg import add_paths

# --- ⚙️ ระบบหลังบ้านเพื่อให้รันบน Render ได้ 24 ชม. ---
add_paths() 
app = Flask('')
@app.route('/')
def home(): return "Music Bot is Online! 🎶"
def run_web(): app.run(host='0.0.0.0', port=8080)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True 
        intents.presences = True 
        super().__init__(command_prefix="!", intents=intents)
        self.queue = {} 
        self.loop_mode = {} 

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

# --- 🔊 ตั้งค่าระบบเสียง (FFMPEG) ---
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

# --- 📊 ระบบแสดงสถานะ Streaming สีม่วงหน้าบอท ---
async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        server_count = len(bot.guilds)
        # แสดงสถานะว่าอยู่กี่เซิร์ฟเวอร์เพื่อให้คนใช้มั่นใจ
        status_text = f"ให้บริการใน {server_count} เซิร์ฟเวอร์ | /play"
        await bot.change_presence(activity=discord.Streaming(
            name=status_text, 
            url="https://www.twitch.tv/directory"
        ))
        await asyncio.sleep(300) # อัปเดตทุก 5 นาที

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
    print(f'✅ บอท {bot.user.name} เริ่มทำงานแล้วครับ!')
    bot.loop.create_task(update_status())

# --- 🛠️ คำสั่งเพลง (Slash Commands) ---

@bot.tree.command(name="play", description="ค้นหาและเล่นเพลงจากชื่อเพลงหรือลิงก์")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ กรุณาเข้าห้องเสียงก่อนใช้งานคำสั่งครับ")

    with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
        try:
            # ค้นหาเพลงผ่านระบบ SoundCloud/YouTube
            info = ydl.extract_info(f"scsearch:{search}", download=False)
            if not info['entries']:
                info = ydl.extract_info(f"ytsearch:{search}", download=False)
            
            if 'entries' in info: info = info['entries'][0]
            song = {'url': info['url'], 'title': info['title']}

            vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()

            if vc.is_playing() or vc.is_paused():
                gid = interaction.guild.id
                if gid not in bot.queue: bot.queue[gid] = []
                bot.queue[gid].append(song)
                await interaction.followup.send(f"✅ เพิ่มเพลง **{song['title']}** ลงในคิวเรียบร้อยครับ")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, interaction.guild.id, song))
                await interaction.followup.send(f"🎶 กำลังเริ่มเล่นเพลง: **{song['title']}**")
        except Exception:
            await interaction.followup.send("❌ ขออภัยครับ ระบบไม่สามารถดึงข้อมูลเพลงนี้ได้")

@bot.tree.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงปัจจุบันเรียบร้อยครับ")
    else:
        await interaction.response.send_message("ไม่มีเพลงที่กำลังเล่นอยู่ขณะนี้ครับ")

@bot.tree.command(name="stop", description="หยุดเล่นเพลงและให้บอทออกจากห้องเสียง")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ ปิดเพลงและออกจากห้องเสียงเรียบร้อยครับ")
    else:
        await interaction.response.send_message("บอทไม่ได้อยู่ในห้องเสียงครับ")

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(os.getenv('TOKEN'))

