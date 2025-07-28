import certifi
import os

os.environ['SSL_CERT_FILE'] = certifi.where()

import uuid
from datetime import datetime, timedelta
import asyncio
import logging
import sqlite3
from contextlib import contextmanager
from aiohttp import web, ClientSession
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Discord & OAuth credentials
BOT_TOKEN     = os.getenv("DISCORD_TOKEN")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI  = os.getenv("REDIRECT_URI")  # e.g. http://localhost:8080/callback
GUILD_ID      = os.getenv("GUILD_ID")
INVITE_URL    = os.getenv("INVITE_URL")      # post-role-assign redirect

# SQLite database path
DB_PATH = os.getenv("DB_PATH", "tokens.db")

# Cohort → Discord role ID map
ROLE_MAP = {
    "lbtcl":     os.getenv("ROLE_LBTCL_ID"),
    "bpd":       os.getenv("ROLE_BPD_ID"),
    "mb": os.getenv("ROLE_MASTER_ID"),
    "pb": os.getenv("ROLE_PB_ID"),
}

# SQLite setup and database initialization
def init_database():
    """Initialize the SQLite database and create the tokens table if it doesn't exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                role_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                used BOOLEAN DEFAULT FALSE
            )
        ''')
        conn.commit()

@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enable dict-like access to rows
    try:
        yield conn
    finally:
        conn.close()

# Token management with SQLite
def create_token(role_key: str, valid_minutes: int = 60) -> str:
    """Create a new token for the specified role."""
    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(minutes=valid_minutes)
    
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO tokens (token, role_key, expires_at, used)
            VALUES (?, ?, ?, ?)
        ''', (token, role_key, expires_at, False))
        conn.commit()
    
    return token

def validate_and_mark(token: str) -> str | None:
    """Validate token and mark it as used atomically. Returns role_key if valid, None otherwise."""
    now = datetime.utcnow()
    
    with get_db_connection() as conn:
        # Start a transaction
        conn.execute('BEGIN IMMEDIATE')
        
        try:
            # Find the token
            cursor = conn.execute('''
                SELECT role_key, used, expires_at 
                FROM tokens 
                WHERE token = ?
            ''', (token,))
            
            row = cursor.fetchone()
            
            if not row:
                conn.rollback()
                return None
            
            # Check if already used
            if row['used']:
                conn.rollback()
                return None
            
            # Check if expired (optional - uncomment if you want expiration)
            # if row['expires_at'] and datetime.fromisoformat(row['expires_at']) < now:
            #     conn.rollback()
            #     return None
            
            # Mark as used
            conn.execute('''
                UPDATE tokens 
                SET used = TRUE 
                WHERE token = ?
            ''', (token,))
            
            conn.commit()
            return row['role_key']
            
        except Exception as e:
            conn.rollback()
            logging.error(f"Error validating token: {e}")
            return None

def cleanup_expired_tokens():
    """Remove expired tokens from the database."""
    now = datetime.utcnow()
    with get_db_connection() as conn:
        conn.execute('''
            DELETE FROM tokens 
            WHERE expires_at IS NOT NULL AND expires_at < ?
        ''', (now,))
        conn.commit()

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

@routes.get("/discord/callback")
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

# Optional: Add a cleanup route for maintenance
@routes.get("/cleanup")
async def cleanup_tokens(request):
    """Manual endpoint to cleanup expired tokens."""
    cleanup_expired_tokens()
    return web.Response(text="Expired tokens cleaned up successfully")

# App setup
app = web.Application()
app.add_routes(routes)

async def main():
    # Initialize the database
    init_database()
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8080)
    await site.start()
    print("OAuth server listening on http://127.0.0.1:8080")
    print(f"Using SQLite database: {DB_PATH}")
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())