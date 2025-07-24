import certifi
import os

os.environ['SSL_CERT_FILE'] = certifi.where()

import uuid
from datetime import datetime, timedelta
import asyncio
import logging
from aiohttp import web, ClientSession
import discord
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient

# Load environment variables

load_dotenv()

# Discord & OAuth credentials
BOT_TOKEN     = os.getenv("DISCORD_TOKEN")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI  = os.getenv("REDIRECT_URI")  # e.g. http://localhost:8080/callback
GUILD_ID      = os.getenv("GUILD_ID")
INVITE_URL    = os.getenv("INVITE_URL")      # post-role-assign redirect
MONGO_URI     = os.getenv("MONGO_URI")

# Cohort → Discord role ID map
ROLE_MAP = {
    "lbtcl":     os.getenv("ROLE_LBTCL_ID"),
    "bpd":       os.getenv("ROLE_BPD_ID"),
    "mb": os.getenv("ROLE_MASTER_ID"),
    "pb": os.getenv("ROLE_PB_ID"),
}

# MongoDB setup
MONGO_DB         = os.getenv("MONGO_DB")   # e.g. "Demon"
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")  # e.g. "C1"
if not MONGO_DB:
    raise RuntimeError("Environment variable MONGO_DB must be set to your database name")
if not MONGO_COLLECTION:
    raise RuntimeError("Environment variable MONGO_COLLECTION must be set to your collection name")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]
tokens_col = db[MONGO_COLLECTION]  # use your specified collection

# Token management with MongoDB
def create_token(role_key: str, valid_minutes: int = 60) -> str:
    token = uuid.uuid4().hex
    # expires_at = datetime.utcnow() + timedelta(minutes=valid_minutes)
    tokens_col.insert_one({
        "token": token,
        "role_key": role_key,
        # "expires_at": expires_at,
        "used": False
    })
    return token


def validate_and_mark(token: str) -> str | None:
    # atomically find unused, unexpired token and mark it used
    now = datetime.utcnow()
    result = tokens_col.find_one_and_update(
        {"token": token, "used": False},
        {"$set": {"used": True}},
        return_document=True
    )
    if not result:
        return None
    return result["role_key"]

# Discord bot setup
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
logging.basicConfig(level=logging.INFO)

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user} ({bot.user.id})")

# HTTP server for invite & callback
routes = web.RouteTableDef()

# To generate the OAuth2 authorization URL for a given cohort, make a GET request to /invite/{cohort}
# e.g. requesting GET http://localhost:8080/invite/lbtcl will redirect you to the constructed Discord OAuth URL
@routes.get("/invite/{cohort}")
async def invite(request):
    cohort = request.match_info["cohort"]
    if cohort not in ROLE_MAP:
        return web.Response(text="Invalid cohort", status=400)

    token = create_token(cohort)
    params = {
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "identify guilds.join",
        "state":         token
    }
    import urllib.parse
    oauth_url = "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    raise web.HTTPFound(location=oauth_url)

@routes.get("/callback")
async def oauth_callback(request):
    code  = request.query.get("code")
    state = request.query.get("state")
    role_key = validate_and_mark(state)

    if not code or not role_key:
        return web.Response(text="Invalid, expired, or already-used link", status=400)

    # Exchange code for access token
    token_data = {
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with ClientSession() as session:
        async with session.post("https://discord.com/api/oauth2/token", data=token_data, headers=headers) as resp:
            token_json = await resp.json()
    access_token = token_json.get("access_token")
    if not access_token:
        return web.Response(text="Token exchange failed", status=400)

    # Fetch user ID
    async with ClientSession() as session:
        async with session.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"}
        ) as resp:
            user_json = await resp.json()
    user_id = user_json.get("id")

    # Add user to guild & assign role
    bot_headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    async with ClientSession() as session:
        await session.put(
            f"https://discord.com/api/guilds/{GUILD_ID}/members/{user_id}",
            json={"access_token": access_token},
            headers=bot_headers
        )
        role_id = ROLE_MAP[role_key]
        await session.put(
            f"https://discord.com/api/guilds/{GUILD_ID}/members/{user_id}/roles/{role_id}",
            headers=bot_headers
        )

    # Final redirect back into Discord
    raise web.HTTPFound(location=INVITE_URL)

# App setup
app = web.Application()
app.add_routes(routes)

async def main():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8129)
    await site.start()
    print("OAuth server listening on http://172.81.178.3:8129")
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
