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
from aiohttp_cors import setup as cors_setup, ResourceOptions
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
        # Create the table with composite primary key (id, email)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER,
                token TEXT UNIQUE NOT NULL,
                role_key TEXT NOT NULL,
                email TEXT NOT NULL,
                name TEXT,
                location TEXT,
                describe_yourself TEXT,
                year TEXT,
                background TEXT,
                github TEXT,
                time TEXT,
                why TEXT,
                skills TEXT,
                books TEXT,
                enrolled BOOLEAN DEFAULT FALSE,
                cohort_name TEXT,
                hear_from TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                used BOOLEAN DEFAULT FALSE,
                email_sent BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (email)
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
                                You've joined the {cohort_name} Study Cohort
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
                            
                            <p style="text-align:center; color:#FFB84D; font-weight:bold; margin:20px 0 10px 0;">
                                Register for the private cohort channels with the link below (one-time-use)
                            </p>
                            
                            <div style="text-align:center; margin:20px 0;">
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
                            
                            <p style="text-align:center; color:#cccccc; font-size:14px; margin:15px 0;">
                                If facing any issue while registering, please connect with the Admins at 
                                <a href="https://discord.gg/bitshala" style="color:#FF9900; text-decoration:none;">Bitshala Discord</a>
                            </p>
                            
                            <div style="background-color:#1a1a1a; padding:20px; border-radius:8px; margin:20px 0;">
                                <h3 style="color:#FF9900; margin:0 0 10px 0; font-size:16px;">
                                    What's Next?
                                </h3>
                                <ul style="margin:0; padding-left:20px; color:#cccccc;">
                                    <li>Click the button above to join private cohort channels</li>
                                    <li>Introduce yourself in the <a href="https://discord.com/channels/773195413825683466/773195414295511100" style="color:#FF9900; text-decoration:none;">#introductions</a> channel</li>
                                    <li>Check out the #general and #notice-board channels under PB Category (Ask Admins if you can't see the channels even after registering)</li>
                                    <li>Stay tuned in the channels for further updates and connect with peers</li>
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
def create_token(role_key: str, email: str = None, name: str = None, location: str = None, 
                 describe_yourself: str = None, year: str = None, background: str = None, 
                 github: str = None, time: str = None, why: str = None, skills: list = None, 
                 books: list = None, enrolled: bool = False, cohort_name: str = None, 
                 hear_from: str = None, valid_minutes: int = 60) -> str:
    """Create a new token for the specified role with all user data."""
    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(minutes=valid_minutes)
    
    if not email:
        raise ValueError("Email is required for token creation")
    
    # Convert lists to JSON strings for storage
    skills_json = json.dumps(skills) if skills else None
    books_json = json.dumps(books) if books else None
    
    with get_db_connection() as conn:
        # Get the next available ID for this email
        cursor = conn.execute('''
            SELECT COALESCE(MAX(id), 0) + 1 as next_id 
            FROM tokens 
            WHERE email = ?
        ''', (email,))
        next_id = cursor.fetchone()[0]
        
        conn.execute('''
            INSERT INTO tokens (id, token, role_key, email, name, location, describe_yourself, 
                              year, background, github, time, why, skills, books, enrolled, 
                              cohort_name, hear_from, expires_at, used, email_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (next_id, token, role_key, email, name, location, describe_yourself, year, 
              background, github, time, why, skills_json, books_json, enrolled, cohort_name, 
              hear_from, expires_at, False, False))
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

# Route to handle registration (alias for /bot/invite for frontend compatibility)
@routes.post("/register")
async def register_user(request):
    """Handle registration requests from frontend - alias for /bot/invite"""
    return await send_invite_email(request)

# New route to handle registration and email sending from Rust
@routes.post("/bot/invite")
async def send_invite_email(request):
    """Handle email invitation requests from Rust service"""
    try:
        data = await request.json()
        name = data.get('name')
        email = data.get('email')
        cohort = data.get('role')
        location = data.get('location')
        describe_yourself = data.get('describeYourself')
        year = data.get('year')
        background = data.get('background')
        github = data.get('github')
        time = data.get('time')
        why = data.get('why')
        skills = data.get('skills', [])
        books = data.get('books', [])
        enrolled = data.get('enrolled', False)
        cohort_name = data.get('cohortName')
        hear_from = data.get('hearFrom')
        
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
        
        # Create token with all user data
        token = create_token(
            role_key=cohort, 
            email=email, 
            name=name,
            location=location,
            describe_yourself=describe_yourself,
            year=year,
            background=background,
            github=github,
            time=time,
            why=why,
            skills=skills,
            books=books,
            enrolled=enrolled,
            cohort_name=cohort_name,
            hear_from=hear_from
        )
        
        # Send welcome email
        email_sent = await send_welcome_email(email, name, cohort, token)
        print(f"Email sent: {email_sent}")
        
        # Generate invite URL
        invite_url = f"{REDIRECT_URI.replace('/bot/callback', '')}/invite/{cohort}?token={token}"
        
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
                SELECT id, role_key, email, name, location, describe_yourself, year, background, 
                       github, time, why, skills, books, enrolled, cohort_name, hear_from,
                       created_at, expires_at, used, email_sent
                FROM tokens 
                ORDER BY created_at DESC 
                LIMIT 50
            ''')
            tokens = []
            for row in cursor.fetchall():
                # Parse JSON fields back to lists
                skills = json.loads(row["skills"]) if row["skills"] else []
                books = json.loads(row["books"]) if row["books"] else []
                
                tokens.append({
                    "id": row["id"],
                    "role_key": row["role_key"],
                    "email": row["email"],
                    "name": row["name"],
                    "location": row["location"],
                    "describe_yourself": row["describe_yourself"],
                    "year": row["year"],
                    "background": row["background"],
                    "github": row["github"],
                    "time": row["time"],
                    "why": row["why"],
                    "skills": skills,
                    "books": books,
                    "enrolled": bool(row["enrolled"]),
                    "cohort_name": row["cohort_name"],
                    "hear_from": row["hear_from"],
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

# Setup CORS
cors = cors_setup(app, defaults={
    "*": ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
        allow_methods="*"
    )
})

# Add CORS to all routes
for route in list(app.router.routes()):
    cors.add(route)

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