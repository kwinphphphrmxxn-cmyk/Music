
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import threading
import asyncio
from flask import Flask
from static_ffmpeg import add_paths # สำคัญ: ช่วยให้บอทมีเสียงบน Render

# --- เตรียมระบบเสียง ---
add_paths() 

app = Flask('')
@app.route('/')
def home(): return "Music Bot is Ready! 🎶"
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

    # ถ้าเปิด Loop ให้เอาเพลงเก่ากลับเข้าคิวใหม่
    if bot.loop_mode.get(guild_id, False) and last_song:
        if guild_id not in bot.queue: bot.queue[guild_id] = []
        bot.queue[guild_id].append(last_song)

    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        next_song = bot.queue[guild_id].pop(0)
        source = discord.FFmpegOpusAudio.from_probe(next_song['url'], **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: play_next(interaction, guild_id, next_song))
        
        coro = interaction.channel.send(f"⏭️ เพลงถัดไป: **{next_song['title']}**")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    else:
        # กรณีคิวหมดจริงๆ
        coro = interaction.channel.send("🎵 เพลงหมดคิวแล้วจ้า")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Streaming(name="เปิดเพลงนะ", url="https://www.twitch.tv/directory"))
    print(f'✅ {bot.user.name} ออนไลน์พร้อมเสียง!')

# --- Commands ---

@bot.tree.command(name="play", description="เปิดเพลงนะ")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ เข้าห้องเสียงก่อนนะ!")

    with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
        try:
            # ค้นหาเพลงจาก SoundCloud (เลี่ยงการโดน YouTube บล็อก)
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
                await interaction.followup.send(f"✅ เพิ่มลงคิว: **{song['title']}**")
            else:
                source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(interaction, interaction.guild.id, song))
                await interaction.followup.send(f"🎶 กำลังเล่น: **{song['title']}**")
        except Exception as e:
            print(f"Error: {e}")
            await interaction.followup.send("❌ หาเพลงไม่เจอหรือระบบเสียงมีปัญหา")

@bot.tree.command(name="loop", description="เปิดเพลงนะ")
async def loop(interaction: discord.Interaction):
    gid = interaction.guild.id
    bot.loop_mode[gid] = not bot.loop_mode.get(gid, False)
    status = "เปิด ✅" if bot.loop_mode[gid] else "ปิด ❌"
    await interaction.response.send_message(f"ระบบเล่นวนคิว: {status}")

@bot.tree.command(name="skip", description="เปิดเพลงนะ")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงให้แล้ว")
    else:
        await interaction.response.send_message("ไม่มีเพลงให้ข้าม")

@bot.tree.command(name="stop", description="เปิดเพลงนะ")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    bot.loop_mode[interaction.guild.id] = False
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ ปิดเพลงและล้างคิวเรียบร้อย")

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(os.getenv('TOKEN'))
