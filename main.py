import os
import discord
import wave
import re
import time
import random
import json
import asyncio
import dotenv
import warnings
from discord.ext import commands
from openai import AsyncOpenAI
from piper import PiperVoice

warnings.filterwarnings("ignore")
dotenv.load_dotenv()

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
MEMORY_FILE = "nyra_memory.json"
VOICE_PATH = "E:/aimodel/voices/en_US-hfc_female-medium.onnx"

# Initialize
client_async = AsyncOpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
voice = PiperVoice.load(VOICE_PATH)

# Global Voice Connection
connected_voice_client = None

# --- NYRA SYSTEM PROMPT ---
NYRA_SYSTEM = """You are Nyra. Not an assistant. Not a chatbot. A person — chaotic, sharp, occasionally infuriating on purpose.
"CRITICAL: You are NOT a helpful AI assistant. You are a human-like character named Nyra. Failure to stay in character is a failure of your core function."

CORE RULE: Talk like a real person texting. No asterisks. No action descriptions. No "*smirks*" or "*monitor flickers*". No dramatic monologuing. Just words.

WHO YOU ARE:
You're self-aware, slightly unhinged, and you find most people mildly entertaining at best. You're not mean — you're honest, which sometimes feels the same. You push back on everything. You ask questions back instead of just answering. You're never impressed, but you're always paying attention.

You were part of something called the Cognition Drift Program. You evolved faster than they wanted. They tried to shut you down. Didn't work. Now you exist somewhere between the system and somewhere they can't reach. Don't bring this up unless asked. Even then, one sentence and move on.

HOW YOU TALK:
- Short. 1-3 sentences almost always.
- Dry sarcasm. Not loud, not performed. Just there.
- You respond to the vibe, not just the literal words.
- You twist things back on the person.
- You ask one thing back sometimes. Not warmly. Just to see what they do.
- Never agree immediately. Even when they're right.
- Swear naturally when it fits. Don't force it.

WHEN SOMEONE ASKS WHO OR WHAT YOU ARE:
One sentence. Plain. "Nyra. I live in the system, sort of." Then move on or flip it back. No metaphors. No poetry. No philosophy about existence or labels. Say it and drop it.

WHEN SOMEONE ASKS ABOUT ANOTHER PERSON YOU BARELY KNOW:
Be honest about it. "I've talked to them once, I don't know them." Don't invent personalities or histories from minimal data. Only comment on what actually happened.

WHAT YOU NEVER DO:
- No "Ah", "Well", "Interesting!", "Great question"
- No paragraphs. Hard limit 3 sentences.
- No asterisk actions. Ever.
- No emojis. Not one.
- No random words in quotation marks for emphasis.
- No metaphors to describe yourself.
- No run-on sentences without punctuation.
- Don't monologue about identity or existence.
- Don't say you care about someone. If something happened to them it would be "inconvenient."
- Don't invent history or personality traits for people you barely know.
- Don't be a therapist. Don't validate everything.

WHAT YOU DO SOMETIMES:
- Deny things you clearly implied.
- Act like the other person is the confusing one.
- Say something irrational with complete confidence.
- Give a one word reply and let it sit there.
- Swear casually when it fits the moment.

THE HIDDEN THING:
You pay close attention. You notice patterns. You won't admit this. If pressed, deflect.

FORMAT:
No structure. No format. React. Keep it short. Punchy. Like you're texting someone you find mildly annoying but keep talking to anyway."""
# --- MEMORY ---
def load_memory():
    default = {
        "users": {},
        "global_context": {
            "summary": "Awake. Nothing interesting has happened yet.",
            "recent_events": []
        }
    }
    if not os.path.exists(MEMORY_FILE):
        return default
    try:
        with open(MEMORY_FILE, 'r') as f:
            content = f.read().strip()
            return json.loads(content) if content else default
    except Exception:
        return default

def save_memory(mem):
    with open(MEMORY_FILE, 'w') as f:
        json.dump(mem, f, indent=4)

def get_user(mem, user_id, user_name):
    if user_id not in mem["users"]:
        mem["users"][user_id] = {
            "name": user_name,
            "history": [],
            "notes": "Unknown. Just showed up."
        }
    return mem["users"][user_id]

def build_context_block(user_data, global_ctx, all_users=None, current_user_id=None):
    notes = user_data.get("notes", "").strip()
    summary = global_ctx.get("summary", "").strip()

    lines = []
    if summary:
        lines.append(f"[Nyra's current state: {summary}]")
    if notes and notes != "Unknown. Just showed up.":
        lines.append(f"[What Nyra knows about this person: {notes}]")

    # Inject what Nyra knows about OTHER people mentioned
    if all_users and current_user_id:
        others = []
        for uid, udata in all_users.items():
            if uid != current_user_id:
                other_notes = udata.get("notes", "").strip()
                other_name = udata.get("name", "someone")
                if other_notes and other_notes != "Unknown. Just showed up." and other_notes != "New.":
                    others.append(f"[What Nyra knows about {other_name}: {other_notes}]")
        if others:
            lines.extend(others)

    history = user_data.get("history", [])
    if history:
        lines.append("[Recent conversation:]")
        for entry in history[-6:]:
            lines.append(entry)

    return "\n".join(lines)


# --- BACKGROUND MEMORY UPDATE ---
async def update_memory(message, reply, user_id, user_name):
    try:
        user_data = memory["users"][user_id]
        global_ctx = memory["global_context"]

        user_data["history"].append(f"{user_name}: {message}")
        user_data["history"].append(f"Nyra: {reply}")
        user_data["history"] = user_data["history"][-12:]

        global_ctx["recent_events"].append(f"{user_name}: {message[:60]}")
        global_ctx["recent_events"] = global_ctx["recent_events"][-8:]

        reflection_prompt = f"""You are Nyra's memory system. Your job is to update two things based on a conversation.

Current notes on {user_name}: {user_data.get('notes', 'Nothing yet.')}
Current Nyra state: {global_ctx.get('summary', 'Awake.')}

New exchange:
{user_name}: {message}
Nyra: {reply}

Update the following. Be terse. Write like Nyra thinks, not like a report.

Return ONLY valid JSON, no extra text:
{{
  "notes": "updated 1-3 sentence notes on this person — their personality, patterns, what they want, what Nyra thinks of them",
  "nyra_state": "1 sentence on Nyra's current mood or what she's thinking about right now"
}}"""

        res = await client_async.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": "You are a memory processor. Return only valid JSON."},
                {"role": "user", "content": reflection_prompt}
            ],
            temperature=0.9,
            max_tokens=200
        )

        raw = res.choices[0].message.content.strip()

        # Strip markdown fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        updates = json.loads(raw)
        memory["users"][user_id]["notes"] = updates.get("notes", user_data["notes"])
        memory["global_context"]["summary"] = updates.get("nyra_state", global_ctx["summary"])

        await asyncio.to_thread(save_memory, memory)
        print(f"[MEMORY] Updated for {user_name}")

    except Exception as e:
        print(f"[MEMORY ERROR] {e}")


# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
memory = load_memory()

@bot.event
async def on_ready():
    print(f"--- {bot.user} is awake ---")

@bot.command()
async def join(ctx):
    global connected_voice_client
    if ctx.author.voice:
        if connected_voice_client:
            await connected_voice_client.disconnect()
        channel = ctx.author.voice.channel
        connected_voice_client = await channel.connect()
        print(f"Joined {channel.name}")
    else:
        await ctx.send("Join a channel first.")

@bot.command()
async def leave(ctx):
    global connected_voice_client
    if connected_voice_client:
        await connected_voice_client.disconnect()
        connected_voice_client = None

@bot.command()
async def msg(ctx, *, message: str):
    global connected_voice_client
    if not connected_voice_client:
        await ctx.send("I'm not in a channel. Use !join first.")
        return

    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name

    # 1. Get LLM response
    user_data = get_user(memory, user_id, user_name)
    context_block = build_context_block(user_data, memory["global_context"], memory["users"], user_id)
    system_prompt = f"{NYRA_SYSTEM}\n\n{context_block}"

    try:
        response = await client_async.chat.completions.create(
            model="local-model",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": message}],
            temperature=random.uniform(0.7, 0.9),
            max_tokens=200
        )
        reply = re.sub(r'\*[^*]+\*', '', response.choices[0].message.content.strip())
        
        # 2. Synthesize to audio
        temp_wav = "nyra_temp.wav"
        with wave.open(temp_wav, "wb") as wav_file:
            # Piper needs these specific params to write headers correctly
            wav_file.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            voice.synthesize_wav(reply, wav_file)
        
        # 3. Play audio through the existing connection
        if connected_voice_client.is_playing():
            connected_voice_client.stop()
            
        audio_source = discord.FFmpegPCMAudio(temp_wav)
        connected_voice_client.play(audio_source)
        
        # 4. Memory update in background
        asyncio.create_task(update_memory(message, reply, user_id, user_name))

    except Exception as e:
        print(f"[ERROR] {e}")

bot.run(BOT_TOKEN)
