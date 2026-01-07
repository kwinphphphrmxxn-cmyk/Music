import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import threading
import asyncio
from flask import Flask
from static_ffmpeg import add_paths

# --- เตรียมระบบเสียง ---
add_paths() 

app = Flask('')
@app.route('/')
def home(): return "บอทออนไลน์พร้อมแสดงสถานะแล้วครับ! 🎶"
def run_web(): app.run(host='0.0.0.0', port=8080)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True # สำหรับนับจำนวนเซิร์ฟเวอร์
        intents.presences = True # สำหรับแสดงสถานะสตรีมมิ่ง
        super().__init__(command_prefix="!", intents=intents)
        self.queue = {} 
        self.loop_mode = {} 

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

# --- ตั้งค่าเสียง ---
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

# ฟังก์ชันอัปเดตสถานะหน้าบอท
async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        server_count = len(bot.guilds)
        # แสดงสถานะ Streaming สีม่วง พร้อมจำนวนเซิร์ฟเวอร์
        await bot.change_presence(activity=discord.Streaming(
            name=f"ให้บริการใน {server_count} เซิร์ฟเวอร์ | /play", 
            url="https://www.twitch.tv/directory"
        ))
        await asyncio.sleep(300) # อัปเดตทุกๆ 5 นาที

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
    print(f'✅ บอท {bot.user.name} ออนไลน์เรียบร้อยครับ!')
    bot.loop.create_task(update_status()) # เริ่มทำงานฟังก์ชันอัปเดตสถานะ

# --- คำสั่ง Slash Commands (สุภาพ) ---

@bot.tree.command(name="play", description="ค้นหาและเล่นเพลงจากชื่อเพลงหรือลิงก์")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    if not interaction.user.voice:
        return await interaction.followup.send("❌ กรุณาเข้าห้องเสียงก่อนใช้งานครับ")

    with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
        try:
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
                await interaction.followup.send(f"✅ เพิ่มเพลง **{song['title']}** ลงในคิวแล้วครับ")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, interaction.guild.id, song))
                await interaction.followup.send(f"🎶 กำลังเล่นเพลง: **{song['title']}**")
        except:
            await interaction.followup.send("❌ ไม่สามารถดึงข้อมูลเพลงได้ในขณะนี้ครับ")

@bot.tree.command(name="queue", description="แสดงรายการเพลงทั้งหมดในคิว")
async def queue(interaction: discord.Interaction):
    gid = interaction.guild.id
    if gid not in bot.queue or not bot.queue[gid]:
        return await interaction.response.send_message("ไม่มีเพลงในคิวครับ")
    msg = "**🎶 รายการคิวเพลง:**\n" + "\n".join([f"{i+1}. {s['title']}" for i, s in enumerate(bot.queue[gid][:10])])
    await interaction.response.send_message(msg)

@bot.tree.command(name="loop", description="เปิด/ปิด การเล่นวนซ้ำ")
async def loop(interaction: discord.Interaction):
    gid = interaction.guild.id
    bot.loop_mode[gid] = not bot.loop_mode.get(gid, False)
    await interaction.response.send_message(f"🔄 ระบบเล่นวนซ้ำ: **{'เปิด' if bot.loop_mode[gid] else 'ปิด'}** เรียบร้อยครับ")

@bot.tree.command(name="skip", description="ข้ามเพลงปัจจุบัน")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงเรียบร้อยครับ")

@bot.tree.command(name="stop", description="หยุดเล่นเพลงและออกจากห้องเสียง")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ ปิดเพลงและล้างคิวเรียบร้อยครับ")

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(os.getenv('TOKEN'))
