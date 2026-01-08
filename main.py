import discord
from discord import app_commands
from discord.ext import commands, tasks
import yt_dlp
import os
import threading
import asyncio
import requests
import random
import datetime
from flask import Flask
from static_ffmpeg import add_paths

# --- 🛠️ ระบบหลังบ้านสำหรับรันบน Render ---
add_paths() 
app = Flask('')
@app.route('/')
def home(): return "Bot is Online with Thai Proxy System! 🇹🇭"
def run_web(): app.run(host='0.0.0.0', port=8080)

TOKEN = os.getenv('TOKEN')

# --- 🔊 ตั้งค่า FFMPEG แบบตุนข้อมูลหนัก (สู้ Proxy ฟรีที่ช้า) ---
FFMPEG_OPTIONS = {
    'before_options': (
        '-reconnect 1 '
        '-reconnect_streamed 1 '
        '-reconnect_delay_max 5 '
        '-probesize 100M '         # ตุนข้อมูลล่วงหน้า 100MB
        '-analyzeduration 100M'
    ),
    'options': (
        '-vn '
        '-b:a 96k '               # ลดบิตเรตลงเล็กน้อยเพื่อให้โหลดผ่าน Proxy ได้ลื่นขึ้น
        '-buffer_size 10M'        # เพิ่ม Buffer ในแรมเป็น 10MB
    )
}

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True 
        super().__init__(command_prefix="!", intents=intents)
        self.queue = {} 
        self.loop_mode = {} 

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

# --- 🛰️ ระบบดึง Proxy ไทยอัตโนมัติ (กรองเฉพาะ TH) ---
def get_random_proxy():
    # ดึงจาก API ที่รวม Proxy ไทยไว้ให้
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=TH&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
    ]
    for url in sources:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                proxies = response.text.splitlines()
                if proxies:
                    selected = random.choice(proxies[:30]) # เลือกตัวต้นๆ ที่มักจะใหม่กว่า
                    print(f"📡 ใช้ Proxy: {selected}")
                    return selected
        except:
            continue
    return None

def get_ydl_opts():
    proxy = get_random_proxy()
    return {
        'format': 'bestaudio/best',
        'default_search': 'ytsearch',
        'noplaylist': True,
        'quiet': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'proxy': f"http://{proxy}" if proxy else None,
        'source_address': '0.0.0.0'
    }

# --- 📡 ระบบอัปเดตสถานะหน้าโปรไฟล์ ---
async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await bot.change_presence(activity=discord.Streaming(
            name=f"ใน {len(bot.guilds)} เซิร์ฟเวอร์ | /play", 
            url="https://www.twitch.tv/directory"
        ))
        await asyncio.sleep(300)

# --- ⏰ ระบบรีเซ็ตตอน 00:00 น. ---
@tasks.loop(minutes=1)
async def check_midnight():
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
    if now.hour == 0 and now.minute == 0:
        print("♻️ รีเซ็ตระบบประจำวัน...")
        bot.queue.clear()
        bot.loop_mode.clear()
        for vc in bot.voice_clients:
            await vc.disconnect()
        await asyncio.sleep(60)

@bot.event
async def on_ready():
    print(f'✅ บอท {bot.user.name} พร้อมลุยด้วย Proxy ไทย!')
    bot.loop.create_task(update_status())
    check_midnight.start()

# --- ⌨️ คำสั่ง Slash Commands ---

@bot.tree.command(name="play", description="เล่นเพลง (ดึง Proxy ไทยอัตโนมัติ)")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    if not interaction.user.voice:
        return await interaction.followup.send("❌ เข้าห้องเสียงก่อนนะจ๊ะ")

    max_retries = 3
    song_info = None
    for i in range(max_retries):
        try:
            with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
                info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]
                song_info = {'url': info['url'], 'title': info['title'], 'link': info.get('webpage_url')}
                break
        except:
            if i == max_retries - 1:
                return await interaction.followup.send("❌ หาเพลงไม่เจอ ลองใหม่อีกครั้งนะ")
            continue

    if song_info:
        vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
        if vc.is_playing() or vc.is_paused():
            gid = interaction.guild.id
            if gid not in bot.queue: bot.queue[gid] = []
            bot.queue[gid].append(song_info)
            await interaction.followup.send(f"✅ เพิ่มเข้าคิว: **{song_info['title']}**")
        else:
            source = await discord.FFmpegOpusAudio.from_probe(song_info['url'], **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: play_next(interaction, interaction.guild.id, song_info))
            await interaction.followup.send(f"🎶 กำลังเล่น: **{song_info['title']}** (ไทยพรอ็กซี)")

def play_next(interaction, guild_id, last_song):
    vc = interaction.guild.voice_client
    if not vc: return
    if bot.loop_mode.get(guild_id, False) and last_song:
        if guild_id not in bot.queue: bot.queue[guild_id] = []
        bot.queue[guild_id].insert(0, last_song)
    if guild_id in bot.queue and len(bot.queue[guild_id]) > 0:
        next_song = bot.queue[guild_id].pop(0)
        source = discord.FFmpegOpusAudio.from_probe(next_song['url'], **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: play_next(interaction, guild_id, next_song))

@bot.tree.command(name="skip", description="ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามให้แล้ว!")

@bot.tree.command(name="stop", description="หยุดและล้างคิว")
async def stop(interaction: discord.Interaction):
    bot.queue[interaction.guild.id] = []
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ ปิดเพลงและแยกย้าย")

@bot.tree.command(name="queue", description="ดูคิวเพลง")
async def queue(interaction: discord.Interaction):
    gid = interaction.guild.id
    if gid in bot.queue and len(bot.queue[gid]) > 0:
        msg = "**📜 คิวเพลง:**\n" + "\n".join([f"{i+1}. {s['title']}" for i, s in enumerate(bot.queue[gid][:10])])
        await interaction.response.send_message(msg)
    else: await interaction.response.send_message("ไม่มีคิวเพลงจ้า")

@bot.tree.command(name="loop", description="เปิด/ปิด การวนเพลง")
async def loop(interaction: discord.Interaction):
    gid = interaction.guild.id
    bot.loop_mode[gid] = not bot.loop_mode.get(gid, False)
    await interaction.response.send_message(f"🔁 โหมดวนเพลง: {'เปิด' if bot.loop_mode[gid] else 'ปิด'}")

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(TOKEN)

