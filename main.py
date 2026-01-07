import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import threading
import asyncio
from flask import Flask

# --- ระบบป้องกัน Render หลับ (Web Server) ---
app = Flask('')
@app.route('/')
def home(): return "บอทออนไลน์แล้วจ้า! 🚀"
def run_web(): app.run(host='0.0.0.0', port=8080)

# --- ตั้งค่าบอท ---
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

# --- การตั้งค่าเสียง (เน้นเสถียรบนคลาวด์) ---
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def get_ydl_opts():
    return {
        'format': 'bestaudio/best',
        'default_search': 'scsearch', # ค้นหาใน SoundCloud ก่อนเพื่อเลี่ยงการโดนแบน
        'noplaylist': True,
        'quiet': True,
        'nocheckcertificate': True,
    }

# --- ฟังก์ชันจัดการคิวเพลง ---
def play_next(interaction, guild_id, last_song):
    vc = interaction.guild.voice_client
    if not vc: return

    # ถ้าเปิด Loop ให้เอาเพลงเก่ากลับเข้าคิว
    if bot.loop_mode.get(guild_id, False) and last_song:
        bot.queue[guild_id].append(last_song)

    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        next_song = bot.queue[guild_id].pop(0)
        source = discord.FFmpegOpusAudio.from_probe(next_song['url'], **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: play_next(interaction, guild_id, next_song))
        
        coro = interaction.channel.send(f"⏭️ เพลงถัดไป: **{next_song['title']}**")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    else:
        coro = interaction.channel.send("🎵 เพลงหมดคิวแล้ว (ใช้ /play เพิ่มเพลง)")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)

# --- สถานะบอท (สีม่วง) ---
@bot.event
async def on_ready():
    server_count = len(bot.guilds)
    await bot.change_presence(activity=discord.Streaming(
        name=f"อยู่ใน {server_count} เซิร์ฟเวอร์", 
        url="https://www.twitch.tv/directory"
    ))
    print(f'✅ บอท {bot.user.name} พร้อมใช้งาน!')

# --- คำสั่ง Slash Commands ---

@bot.tree.command(name="play", description="เปิดเพลง")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ เข้าห้องเสียงก่อนนะ!")

    with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
        try:
            # ค้นหาเพลง
            info = ydl.extract_info(f"scsearch:{search}", download=False)
            if not info['entries']:
                # ถ้า SoundCloud ไม่มี ให้ลองหาใน YouTube (แบบ Search)
                info = ydl.extract_info(f"ytsearch:{search}", download=False)
            
            if 'entries' in info: info = info['entries'][0]
            song = {'url': info['url'], 'title': info['title']}

            vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
            guild_id = interaction.guild.id

            if vc.is_playing() or vc.is_paused():
                if guild_id not in bot.queue: bot.queue[guild_id] = []
                bot.queue[guild_id].append(song)
                await interaction.followup.send(f"✅ เพิ่มลงคิว: **{song['title']}**")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, guild_id, song))
                await interaction.followup.send(f"🎶 กำลังเล่น: **{song['title']}**")
        except:
            await interaction.followup.send("❌ หาเพลงไม่เจอหรือระบบขัดข้องครับ")

@bot.tree.command(name="queue", description="ดูคิว")
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    loop_status = " (เปิดวนเพลง 🔄)" if bot.loop_mode.get(guild_id, False) else ""
    if guild_id not in bot.queue or len(bot.queue[guild_id]) == 0:
        return await interaction.response.send_message(f"คิวว่างเปล่า{loop_status}")
    
    msg = f"**🎶 รายการในคิว{loop_status}:**\n"
    for i, s in enumerate(bot.queue[guild_id][:10], 1):
        msg += f"{i}. {s['title']}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="loop", description="เปิด/ปิด เล่นวน")
async def loop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    bot.loop_mode[guild_id] = not bot.loop_mode.get(guild_id, False)
    status = "เปิด ✅" if bot.loop_mode[guild_id] else "ปิด ❌"
    await interaction.response.send_message(f"ระบบเล่นวนเพลง: {status}")

@bot.tree.command(name="skip", description="ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามให้แล้ว")

@bot.tree.command(name="stop", description="หยุดเพลง")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    bot.loop_mode[interaction.guild.id] = False
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ ปิดเพลงเรียบร้อย")

# --- รันบอท ---
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    # ใส่ Token บอทของคุณตรงนี้ หรือใช้ Environment Variable
    bot.run(os.getenv('TOKEN')) 

