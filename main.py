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
import aiohttp
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json

# Load environment variables
load_dotenv()

# Discord & OAuth credentials
BOT_TOKEN     = os.getenv("DISCORD_TOKEN")
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI  = os.getenv("REDIRECT_URI")  # e.g. http://localhost:8080/callback
GUILD_ID      = os.getenv("GUILD_ID")
INVITE_URL    = os.getenv("INVITE_URL")      # post-role-assign redirect

# Email configuration
EMAIL_METHOD = os.getenv("EMAIL_METHOD", "sendgrid")  # "sendgrid" or "smtp"
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "contact@bitshala.org")
FROM_NAME = os.getenv("FROM_NAME", "Bitshala Team")

# SMTP configuration (if using SMTP instead of SendGrid)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# SQLite database path
DB_PATH = os.getenv("DB_PATH", "tokens.db")

# Cohort → Discord role ID map
ROLE_MAP = {
    "lbtcl_cohort":     os.getenv("ROLE_LBTCL_ID"),
    "bpd_cohort":       os.getenv("ROLE_BPD_ID"),
    "mb_cohort": os.getenv("ROLE_MASTER_ID"),
    "pb_cohort": os.getenv("ROLE_PB_ID"),
}

# Cohort display names
COHORT_NAMES = {
    "lbtcl_cohort": "Learn Bitcoin Through Command Line",
    "bpd_cohort": "Bitcoin Protocol Development",
    "mb_cohort": "Master Bitcoin",
    "pb_cohort": "Programming Bitcoin",
}

# SQLite setup and database initialization
def init_database():
    """Initialize the SQLite database and create/update the tokens table."""
    with sqlite3.connect(DB_PATH) as conn:
        # Create the table with the new schema
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                role_key TEXT NOT NULL,
                email TEXT,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                used BOOLEAN DEFAULT FALSE,
                email_sent BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Check if email column exists, if not add it (for existing databases)
        cursor = conn.execute("PRAGMA table_info(tokens)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'email' not in columns:
            conn.execute('ALTER TABLE tokens ADD COLUMN email TEXT')
        if 'name' not in columns:
            conn.execute('ALTER TABLE tokens ADD COLUMN name TEXT')
        if 'email_sent' not in columns:
            conn.execute('ALTER TABLE tokens ADD COLUMN email_sent BOOLEAN DEFAULT FALSE')
            
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

def create_email_html(name, cohort_name, invite_url, server_name="Bitshala"):
    """Create HTML email content"""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to {cohort_name}!</title>
</head>
<body style="margin:0; padding:0; background-color:#202124; font-family:Arial, sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#202124">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" bgcolor="#272727"
                       style="margin:30px 0; border-radius:8px; overflow:hidden; max-width:100%;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color:#000000; padding:20px; text-align:center;">
                            <h1 style="color:#ffffff; margin:0; font-size:24px; line-height:1.2;">
                                🎉 Welcome {name}!
                            </h1>
                            <h2 style="color:#FF9900; margin:10px 0 0 0; font-size:18px; font-weight:normal;">
                                You've joined the {cohort_name}
                            </h2>
                        </td>
                    </tr>
                    <!-- Body -->
                    <tr>
                        <td style="padding:30px; color:#dddddd; font-size:16px; line-height:1.6;">
                            <p style="margin-top:0;">
                                We're thrilled to have you onboard! 🚀
                            </p>
                            <p>
                                Connect with fellow Bitcoiners and developers in our 
                                <strong style="color:#FF9900;">{server_name} Discord community</strong>. 
                                This is where the magic happens - discussions, collaboration, and learning together.
                            </p>
                            
                            <div style="text-align:center; margin:30px 0;">
                                <a href="{invite_url}"
                                   style="background: linear-gradient(135deg, #FF9900, #FFB84D);
                                          color:#ffffff;
                                          text-decoration:none;
                                          padding:15px 30px;
                                          border-radius:25px;
                                          display:inline-block;
                                          font-size:16px;
                                          font-weight:bold;
                                          box-shadow: 0 4px 15px rgba(255, 153, 0, 0.3);
                                          transition: all 0.3s ease;">
                                    🚀 Join Discord Server
                                </a>
                            </div>
                            
                            <div style="background-color:#1a1a1a; padding:20px; border-radius:8px; margin:20px 0;">
                                <h3 style="color:#FF9900; margin:0 0 10px 0; font-size:16px;">
                                    What's Next?
                                </h3>
                                <ul style="margin:0; padding-left:20px; color:#cccccc;">
                                    <li>Click the button above to join our Discord</li>
                                    <li>Introduce yourself in the #introductions channel</li>
                                    <li>Check out the cohort resources and schedule</li>
                                    <li>Start connecting with your peers!</li>
                                </ul>
                            </div>
                            
                            <p style="font-size:14px; color:#999999; text-align:center; margin:20px 0 5px;">
                                Having trouble with the button? Copy and paste this link:
                            </p>
                            <p style="font-size:12px; color:#FF9900; word-break:break-all; text-align:center; margin:0; background-color:#1a1a1a; padding:10px; border-radius:4px;">
                                {invite_url}
                            </p>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="background-color:#000000; padding:20px; text-align:center; font-size:12px; color:#777777;">
                            <p style="margin:0 0 10px 0;">
                                Ready to dive into Bitcoin development? We're here to support your journey! 💪
                            </p>
                            <p style="margin:0;">
                                Cheers,<br>
                                <strong style="color:#FF9900;">The {server_name} Team</strong>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

def send_email_smtp(to_email, subject, html_body):
    """Send email using SMTP"""
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        logging.error(f"Failed to send email via SMTP: {e}")
        return False

async def send_welcome_email(email, name, cohort, token):
    """Send welcome email with Discord invite link"""
    try:
        cohort_name = COHORT_NAMES.get(cohort, f"{cohort} Cohort")
        invite_url = f"{REDIRECT_URI.replace('/discord/callback', '')}/invite/{cohort}?token={token}"
        
        subject = f"🎉 Welcome to {cohort_name} - Join our Discord!"
        html_body = create_email_html(name, cohort_name, invite_url)
        
        success = send_email_smtp(email, subject, html_body)
        
        # Update email_sent status in database
        with get_db_connection() as conn:
            conn.execute('''
                UPDATE tokens 
                SET email_sent = ? 
                WHERE token = ?
            ''', (success, token))
            conn.commit()
        
        return success
        
    except Exception as e:
        logging.error(f"Error sending welcome email: {e}")
        return False

# Token management with SQLite (updated to include email)
def create_token(role_key: str, email: str = None, name: str = None, valid_minutes: int = 60) -> str:
    """Create a new token for the specified role with email and name."""
    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(minutes=valid_minutes)
    
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO tokens (token, role_key, email, name, expires_at, used, email_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (token, role_key, email, name, expires_at, False, False))
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

# New route to handle registration and email sending from Rust
@routes.post("/bot/invite")
async def send_invite_email(request):
    """Handle email invitation requests from Rust service"""
    try:
        data = await request.json()
        name = data.get('name')
        email = data.get('email')
        cohort = data.get('role')
        
        print(data)
        
        # Validate required fields
        if not all([name, email, cohort]):
            return web.json_response(
                {"error": "Missing required fields: name, email, cohort", "status": "ERROR"}, 
                status=400
            )
        
        # Validate cohort
        if cohort not in ROLE_MAP:
            return web.json_response(
                {"error": f"Invalid cohort: {cohort}", "status": "ERROR"}, 
                status=400
            )
        
        # Create token with email and name
        token = create_token(cohort, email, name)
        
        # Send welcome email
        email_sent = await send_welcome_email(email, name, cohort, token)
        print(f"Email sent: {email_sent}")
        
        # Generate invite URL
        invite_url = f"{REDIRECT_URI.replace('/discord/callback', '')}/invite/{cohort}?token={token}"
        
        if email_sent:
            logging.info(f"Successfully sent invite email to {email} for cohort {cohort}")
            return web.json_response({
                "invite_link": invite_url,
                "status": "SENT",
                "message": "Email sent successfully",
                "token": token
            })
        else:
            logging.error(f"Failed to send email to {email}")
            return web.json_response({
                "invite_link": invite_url,
                "status": "EMAIL_FAILED",
                "message": "Failed to send email, but token created",
                "token": token
            }, status=500)
            
    except json.JSONDecodeError:
        return web.json_response(
            {"error": "Invalid JSON payload", "status": "ERROR"}, 
            status=400
        )
    except Exception as e:
        logging.error(f"Error in send_invite_email: {e}")
        return web.json_response(
            {"error": str(e), "status": "ERROR"}, 
            status=500
        )


@routes.get("/invite/{cohort}")
async def invite(request):
    cohort = request.match_info["cohort"]
    if cohort not in ROLE_MAP:
        return web.Response(text="Invalid cohort", status=400)

    # Check if token is provided in query params (from email link)
    provided_token = request.query.get("token")
    
    if provided_token:
        # Use the provided token
        token = provided_token
    else:
        # Create a new token (legacy behavior)
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

@routes.get("/bot/callback")
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

# Health check endpoint
@routes.get("/health")
async def health_check(request):
    return web.json_response({"status": "healthy"})

# Admin route to view tokens (for debugging)
@routes.get("/bot/admin/tokens")
async def view_tokens(request):
    """Admin endpoint to view all tokens (for debugging)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute('''
                SELECT id, role_key, email, name, created_at, expires_at, used, email_sent
                FROM tokens 
                ORDER BY created_at DESC 
                LIMIT 50
            ''')
            tokens = []
            for row in cursor.fetchall():
                tokens.append({
                    "id": row["id"],
                    "role_key": row["role_key"],
                    "email": row["email"],
                    "name": row["name"],
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                    "used": bool(row["used"]),
                    "email_sent": bool(row["email_sent"])
                })
        
        return web.json_response({"tokens": tokens})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

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
    print(f"Email method: {EMAIL_METHOD}")
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())