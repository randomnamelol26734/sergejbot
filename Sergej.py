import discord
from discord.ext import commands, tasks
from discord import ui, ButtonStyle
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Server-ID für die Statistik-Kanäle
DEINE_SERVER_ID = 1342638710004649986  # Ersetze dies mit deiner Server-ID

CONFIG = {
    "CHANNELS": {
        "welcome": 1342663677345792082,  # Willkommenskanal
        "logs": 1342665916281917471,     # Log-Kanal
        "ticket": 1342665879233757214,   # Ticket-Kanal
        "portal": 1342663677345792082    # Portal-Kanal (für Willkommens- und Verlassen-Nachrichten)
    },
    "ROLES": {
        "default": "Nicht verifiziert",
        "member": "Mitglied",
        "admin_roles": {"Owner", "Admin", "Moderator"}
    },
    "COOLDOWN": 86400,  # 24 Stunden
    "DELETE_DELAY": 20   # Sekunden
}

ticket_cooldowns = {}
pending_tickets = {}

# Kanäle, in denen Nachrichten nicht gelöscht werden dürfen
PROTECTED_CHANNELS = {
    1342663628511379598,  # Geschützte Kanäle
    1342663677345792082,
    1343365039935066202,
    1342665847961026682,
    1342665879233757214,
    1342665916281917471
}

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.bans = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Hilfsfunktionen
async def log_action(action: str, details: str):
    """Loggt Aktionen in den Bot-Log-Kanal."""
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        embed = discord.Embed(
            title=f"📝 {action}",
            description=details,
            color=0x7289da,
            timestamp=datetime.now()
        )
        await log_channel.send(embed=embed)

async def create_deleted_messages_file(messages: list, filename: str):
    """Erstellt eine Textdatei mit den gelöschten Nachrichten."""
    with open(filename, "w", encoding="utf-8") as file:
        for message in messages:
            file.write(f"{message.author} ({message.author.id}) | {message.created_at}:\n{message.content}\n\n")
    return filename

# Statistik-Kanäle
async def setup_stats_channels():
    """Erstellt oder aktualisiert die Statistik-Kanäle."""
    guild = bot.get_guild(DEINE_SERVER_ID)
    if not guild:
        print("❌ Guild nicht gefunden! Überprüfe die Server-ID.")
        return

    # Prüfe, ob die Kategorie existiert, sonst erstelle sie
    category_name = "📊 Server Statistiken"
    category = discord.utils.get(guild.categories, name=category_name)
    
    if not category:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=False, speak=False)  # Sperrt die Channels
        }
        try:
            category = await guild.create_category(category_name, overwrites=overwrites)
            print(f"✅ Kategorie '{category_name}' erstellt.")
        except discord.Forbidden:
            print("❌ Fehler: Der Bot hat keine Berechtigung, Kanäle zu erstellen.")
            return
        except discord.HTTPException as e:
            print(f"❌ Fehler beim Erstellen der Kategorie: {e}")
            return
    
    # Lösche alle vorhandenen Kanäle in der Kategorie
    for channel in category.voice_channels:
        try:
            await channel.delete()
            print(f"✅ Kanal '{channel.name}' gelöscht.")
        except discord.Forbidden:
            print(f"❌ Fehler: Der Bot hat keine Berechtigung, den Kanal '{channel.name}' zu löschen.")
            return
        except discord.HTTPException as e:
            print(f"❌ Fehler beim Löschen des Kanals '{channel.name}': {e}")
            return

    # Erstelle neue Kanäle
    channel_names = {
        "all_members": "👥 Alle Mitglieder",
        "members": "🟢 Mitglieder",
        "bots": "🤖 Bots"
    }
    channels = {}

    for key, name in channel_names.items():
        try:
            channels[key] = await guild.create_voice_channel(name, category=category)
            print(f"✅ Kanal '{name}' erstellt.")
        except discord.Forbidden:
            print(f"❌ Fehler: Der Bot hat keine Berechtigung, den Kanal '{name}' zu erstellen.")
            return
        except discord.HTTPException as e:
            print(f"❌ Fehler beim Erstellen des Kanals '{name}': {e}")
            return

    # IDs speichern, damit update_member_stats sie findet
    bot.stats_channels = channels
    print("✅ Statistik-Kanäle erfolgreich eingerichtet.")

@tasks.loop(minutes=5)  # Alle 5 Minuten aktualisieren
async def update_member_stats():
    """Aktualisiert die Statistik-Kanäle."""
    guild = bot.get_guild(DEINE_SERVER_ID)
    if not guild or not hasattr(bot, "stats_channels"):
        print("❌ Guild oder Statistik-Kanäle nicht gefunden!")
        return

    bot_role = discord.utils.get(guild.roles, name="Bots")
    unverified_role = discord.utils.get(guild.roles, name="Nicht verifiziert")

    if not bot_role or not unverified_role:
        print("❌ Rollen 'Bots' oder 'Nicht verifiziert' nicht gefunden!")
        return

    all_count = len([m for m in guild.members if bot_role not in m.roles])
    verified_count = len([m for m in guild.members if bot_role not in m.roles and unverified_role not in m.roles])
    bot_count = len([m for m in guild.members if bot_role in m.roles])

    try:
        await bot.stats_channels["all_members"].edit(name=f"👥 Alle Mitglieder: {all_count}")
        await bot.stats_channels["members"].edit(name=f"🟢 Mitglieder: {verified_count}")
        await bot.stats_channels["bots"].edit(name=f"🤖 Bots: {bot_count}")
        print("✅ Statistik-Kanäle erfolgreich aktualisiert.")
    except discord.Forbidden:
        print("❌ Fehler: Der Bot hat keine Berechtigung, die Kanäle zu bearbeiten.")
    except discord.HTTPException as e:
        print(f"❌ Fehler beim Aktualisieren der Statistik: {e}")

# Ticket-System
class AnswerButton(ui.View):
    def __init__(self, thread, user_id):
        super().__init__(timeout=None)
        self.thread = thread
        self.user_id = user_id  # Speichert die User-ID des "Nicht verifiziert"-Nutzers

    @ui.button(label="Antworten", style=ButtonStyle.blurple)
    async def answer(self, interaction: discord.Interaction, button: ui.Button):
        try:
            # Überprüfung, ob der Benutzer derjenige ist, der das Ticket erstellt hat
            if interaction.user.id != self.user_id:
                return await interaction.response.send_message("❌ Nur der Ticket-Ersteller kann antworten!", ephemeral=True)
            
            # Überprüfung, ob bereits eine Antwort existiert
            if pending_tickets[self.thread.id].get("answered", False):
                return await interaction.response.send_message("❌ Du hast bereits geantwortet!", ephemeral=True)
            
            await interaction.response.send_modal(TicketQuestion(self.thread))
        except Exception as e:
            print(f"Fehler bei der Interaktion: {e}")

class TicketQuestion(ui.Modal):
    def __init__(self, thread):
        super().__init__(title="Verifizierungsantwort", timeout=300)
        self.thread = thread
        self.answer = ui.TextInput(
            label="Antwort (1-200 Zeichen)",
            placeholder="Ich habe den Server durch...",
            min_length=1,
            max_length=200
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            pending_tickets[self.thread.id]["answered"] = True  # Antwort wurde eingereicht
            pending_tickets[self.thread.id]["answer"] = self.answer.value
            await interaction.response.defer()
            await self.thread.send(
                embed=discord.Embed(
                    title="Antwort eingereicht",
                    description=f"```{self.answer.value}```",
                    color=0x7289da
                ),
                view=VerificationButtons(self.thread)
            )
        except Exception as e:
            print(f"Fehler beim Verarbeiten der Antwort: {e}")

class TicketCreation(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Ticket erstellen", style=ButtonStyle.green, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: ui.Button):
        try:
            member = interaction.user
            
            # Überprüfe, ob der Benutzer bereits ein aktives Ticket hat
            for ticket in pending_tickets.values():
                if ticket["user"] == member.id and not ticket["answered"]:
                    return await interaction.response.send_message("❌ Du hast bereits ein aktives Ticket!", ephemeral=True)

            if discord.utils.get(member.roles, name=CONFIG['ROLES']['member']):
                return await interaction.response.send_message("❌ Du bist bereits verifiziert!", ephemeral=True)
            
            if ticket_cooldowns.get(member.id, 0) > time.time():
                remaining = ticket_cooldowns[member.id] - time.time()
                return await interaction.response.send_message(
                    f"❌ Du kannst erst in {timedelta(seconds=int(remaining))} ein neues Ticket erstellen!",
                    ephemeral=True
                )

            thread = await interaction.channel.create_thread(
                name=f"Ticket-{member.display_name}",
                type=discord.ChannelType.private_thread
            )
            
            await thread.add_user(member)
            
            for role_name in CONFIG['ROLES']['admin_roles']:
                role = discord.utils.get(interaction.guild.roles, name=role_name)
                if role:
                    for user in role.members:
                        await thread.add_user(user)
            
            pending_tickets[thread.id] = {"user": member.id, "answered": False}
            
            embed = discord.Embed(
                title="Verifizierungsfrage",
                description="Wie hast du auf diesen Server gefunden?",
                color=0x00ff00
            )
            await thread.send(embed=embed, view=AnswerButton(thread, member.id))
            await interaction.response.send_message(f"✅ Ticket erstellt: {thread.mention}", ephemeral=True)
        except Exception as e:
            print(f"Fehler beim Erstellen des Tickets: {e}")

class VerificationButtons(ui.View):
    def __init__(self, thread):
        super().__init__(timeout=None)
        self.thread = thread

    async def close_ticket(self):
        await asyncio.sleep(CONFIG['DELETE_DELAY'])
        try:
            await self.thread.delete()
        except:
            await self.thread.edit(archived=True, locked=True)

    @ui.button(label="Verifizieren", style=ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: ui.Button):
        try:
            if not any(role.name in CONFIG['ROLES']['admin_roles'] for role in interaction.user.roles):
                return await interaction.response.send_message("❌ Unbefugt!", ephemeral=True)
            
            data = pending_tickets.get(self.thread.id)
            if not data:
                return
            
            member = interaction.guild.get_member(data["user"])
            if member:
                # Rollen aktualisieren
                unverified_role = discord.utils.get(interaction.guild.roles, name=CONFIG['ROLES']['default'])
                member_role = discord.utils.get(interaction.guild.roles, name=CONFIG['ROLES']['member'])
                
                if unverified_role:
                    await member.remove_roles(unverified_role)
                if member_role:
                    await member.add_roles(member_role)
                
                # Loggen
                log_channel = interaction.guild.get_channel(CONFIG['CHANNELS']['logs'])
                if log_channel:
                    embed = discord.Embed(
                        title="✅ Verifizierung erfolgreich",
                        description=f"User: {member.mention}\nAntwort: {data['answer']}",
                        color=0x00ff00
                    )
                    await log_channel.send(embed=embed)
            
            await self.thread.send("🎉 Verifizierung abgeschlossen! Der Thread wird geschlossen.")
            del pending_tickets[self.thread.id]
            await self.close_ticket()
            await interaction.response.defer()
        except Exception as e:
            print(f"Fehler bei der Verifizierung: {e}")

    @ui.button(label="Ablehnen", style=ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: ui.Button):
        try:
            if not any(role.name in CONFIG['ROLES']['admin_roles'] for role in interaction.user.roles):
                return await interaction.response.send_message("❌ Unbefugt!", ephemeral=True)
            
            data = pending_tickets.get(self.thread.id)
            if not data:
                return
            
            member = interaction.guild.get_member(data["user"])
            if member:
                ticket_cooldowns[member.id] = time.time() + CONFIG['COOLDOWN']
                
                log_channel = interaction.guild.get_channel(CONFIG['CHANNELS']['logs'])
                if log_channel:
                    embed = discord.Embed(
                        title="❌ Verifizierung abgelehnt",
                        description=f"User: {member.mention}",
                        color=0xff0000
                    )
                    await log_channel.send(embed=embed)
            
            await self.thread.send("🚫 Verifizierung abgelehnt! Der Thread wird geschlossen.")
            del pending_tickets[self.thread.id]
            await self.close_ticket()
            await interaction.response.defer()
        except Exception as e:
            print(f"Fehler bei der Ablehnung: {e}")

    @ui.button(label="Verifizierung abbrechen", style=ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        try:
            member = interaction.guild.get_member(interaction.user.id)
            data = pending_tickets.get(self.thread.id)
            
            if not data or data["user"] != member.id:
                return await interaction.response.send_message("❌ Unbefugt!", ephemeral=True)
            
            log_channel = interaction.guild.get_channel(CONFIG['CHANNELS']['logs'])
            if log_channel:
                embed = discord.Embed(
                    title="❌ Ticket abgebrochen",
                    description=f"User: {member.mention}",
                    color=0xff0000
                )
                await log_channel.send(embed=embed)
            
            await self.thread.send("⚠️ Ticket vom User abgebrochen! Der Thread wird geschlossen.")
            del pending_tickets[self.thread.id]
            await self.close_ticket()
            await interaction.response.defer()
        except Exception as e:
            print(f"Fehler beim Abbrechen: {e}")

# Nachrichten-Löschfunktionen
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clearmsgtoday(ctx):
    """Löscht alle Nachrichten des heutigen Tages im aktuellen Kanal."""
    if ctx.channel.id in PROTECTED_CHANNELS:
        return await ctx.send("❌ Nachrichten in diesem Kanal dürfen nicht gelöscht werden!", ephemeral=True)
    
    today = datetime.utcnow().date()
    deleted_messages = []
    
    async for message in ctx.channel.history(limit=None):
        if message.created_at.date() == today:
            deleted_messages.append(message)
    
    await ctx.channel.delete_messages(deleted_messages)
    
    # Erstelle eine Textdatei mit den gelöschten Nachrichten
    filename = f"deleted_messages_{ctx.channel.id}_{today}.txt"
    file_path = await create_deleted_messages_file(deleted_messages, filename)
    
    # Sende die Datei in den Log-Kanal
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        await log_channel.send(
            f"🗑️ {len(deleted_messages)} Nachrichten im Kanal {ctx.channel.mention} gelöscht.",
            file=discord.File(file_path)  # Komma hinzugefügt
        )
    
    # Lösche die Datei nach dem Senden
    os.remove(file_path)
    
    await ctx.send(f"✅ {len(deleted_messages)} Nachrichten des heutigen Tages gelöscht.", ephemeral=True)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, channel: discord.TextChannel, amount: int):
    """Löscht die letzten 1-100 Nachrichten in einem bestimmten Kanal."""
    if channel.id in PROTECTED_CHANNELS:
        return await ctx.send("❌ Nachrichten in diesem Kanal dürfen nicht gelöscht werden!", ephemeral=True)
    
    if amount < 1 or amount > 100:
        return await ctx.send("❌ Bitte gib eine Anzahl zwischen 1 und 100 an!", ephemeral=True)
    
    deleted_messages = []
    async for message in channel.history(limit=amount):
        deleted_messages.append(message)
    
    await channel.delete_messages(deleted_messages)
    
    # Erstelle eine Textdatei mit den gelöschten Nachrichten
    filename = f"deleted_messages_{channel.id}_{datetime.utcnow().date()}.txt"
    file_path = await create_deleted_messages_file(deleted_messages, filename)
    
    # Sende die Datei in den Log-Kanal
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        await log_channel.send(
            f"🗑️ {len(deleted_messages)} Nachrichten im Kanal {channel.mention} gelöscht.",
            file=discord.File(file_path)  # Komma hinzugefügt
        )
    
    # Lösche die Datei nach dem Senden
    os.remove(file_path)
    
    await ctx.send(f"✅ {len(deleted_messages)} Nachrichten im Kanal {channel.mention} gelöscht.", ephemeral=True)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clearmsg(ctx, user: discord.Member):
    """Löscht alle Nachrichten eines bestimmten Benutzers im aktuellen Kanal."""
    if ctx.channel.id in PROTECTED_CHANNELS:
        return await ctx.send("❌ Nachrichten in diesem Kanal dürfen nicht gelöscht werden!", ephemeral=True)
    
    deleted_messages = []
    async for message in ctx.channel.history(limit=None):
        if message.author.id == user.id:
            deleted_messages.append(message)
    
    await ctx.channel.delete_messages(deleted_messages)
    
    # Erstelle eine Textdatei mit den gelöschten Nachrichten
    filename = f"deleted_messages_{ctx.channel.id}_{user.id}.txt"
    file_path = await create_deleted_messages_file(deleted_messages, filename)
    
    # Sende die Datei in den Log-Kanal
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        await log_channel.send(
            f"🗑️ {len(deleted_messages)} Nachrichten von {user.mention} im Kanal {ctx.channel.mention} gelöscht.",
            file=discord.File(file_path)  # Komma hinzugefügt
        )
    
    # Lösche die Datei nach dem Senden
    os.remove(file_path)
    
    await ctx.send(f"✅ {len(deleted_messages)} Nachrichten von {user.mention} gelöscht.", ephemeral=True)

# Events
@bot.event
async def on_ready():
    print(f"✅ Bot ist online als {bot.user.name}")
    bot.add_view(TicketCreation())
    
    # Ticket-Embed erstellen
    channel = bot.get_channel(CONFIG['CHANNELS']['ticket'])
    if channel:
        messages = [message async for message in channel.history(limit=1)]
        if not messages or not messages[0].components:
            embed = discord.Embed(
                title="🎫 Ticket erstellen",
                description="Klicke unten um ein Verifizierungsticket zu erstellen!",
                color=0x7289da
            )
            await channel.purge(limit=1)
            await channel.send(embed=embed, view=TicketCreation())
    
    await bot.get_channel(CONFIG['CHANNELS']['logs']).send("🤖 Bot gestartet")

    # Statistik-Kanäle einrichten und Task starten
    await setup_stats_channels()
    update_member_stats.start()

@bot.event
async def on_member_join(member):
    # Rolle "Nicht verifiziert" zuweisen
    unverified_role = discord.utils.get(member.guild.roles, name=CONFIG['ROLES']['default'])
    if unverified_role:
        await member.add_roles(unverified_role)
        print(f"Rolle 'Nicht verifiziert' an {member} zugewiesen")  # Debug-Ausgabe
    else:
        print(f"Rolle 'Nicht verifiziert' nicht gefunden!")  # Debug-Ausgabe
    
    # Willkommensnachricht mit Profilbild senden
    welcome_channel = bot.get_channel(CONFIG['CHANNELS']['welcome'])
    if welcome_channel:
        embed = discord.Embed(
            title=f"Willkommen bei der **{member.guild.name}**, **{member.name}**! 🎉",
            color=0x7289da  # Farbe des Embeds (hier: Blau)
        )
        embed.set_thumbnail(url=member.avatar.url)  # Profilbild als Thumbnail
        embed.set_footer(text=f"Mitglied #{len(member.guild.members)}")  # Mitgliedsnummer

        await welcome_channel.send(embed=embed)
    
    # Loggen des Joins
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        embed = discord.Embed(
            title="📥 Mitglied beigetreten",
            description=f"{member.mention} ({member.id})",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        await log_channel.send(embed=embed)

    # Benutzer per Privatnachricht anschreiben
    try:
        await member.send(f"Um der **{member.guild.name}** beizutreten, erstelle ein Ticket hier: <#{CONFIG['CHANNELS']['ticket']}>")
    except discord.Forbidden:
        print(f"❌ Konnte dem Benutzer {member.name} keine Privatnachricht senden (DM deaktiviert).")
    except Exception as e:
        print(f"❌ Fehler beim Senden der Privatnachricht: {e}")

    # Statistik aktualisieren
    await update_member_stats()

@bot.event
async def on_member_remove(member):
    # Loggen des Leaves
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        # Überprüfen, ob der Benutzer gebannt wurde
        try:
            await member.guild.fetch_ban(member)
            # Wenn der Benutzer gebannt wurde, wird dies in on_member_ban behandelt
            return
        except discord.NotFound:
            # Wenn der Benutzer nicht gebannt wurde, hat er den Server freiwillig verlassen
            embed = discord.Embed(
                title="🚪 Mitglied hat den Server verlassen",
                description=f"{member.mention} ({member.id}) hat den Server verlassen.",
                color=0xffa500,  # Orange für freiwilliges Verlassen
                timestamp=datetime.now()
            )
            await log_channel.send(embed=embed)
    
    # Nachricht im Portal-Kanal
    portal_channel = bot.get_channel(CONFIG['CHANNELS']['portal'])
    if portal_channel:
        await portal_channel.send(f"{member.mention} geht in den Westen...")

@bot.event
async def on_member_ban(guild, user):
    # Loggen des Bans
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        embed = discord.Embed(
            title="🔨 Mitglied gebannt",
            description=f"{user.mention} ({user.id}) wurde vom Server gebannt.",
            color=0xff0000,  # Rot für Bann
            timestamp=datetime.now()
        )
        await log_channel.send(embed=embed)
    
    # Nachricht im Portal-Kanal
    portal_channel = bot.get_channel(CONFIG['CHANNELS']['portal'])
    if portal_channel:
        await portal_channel.send(f"{user.mention} wurde in den Gulag geschickt...")

# Befehle
def is_admin(ctx):
    return any(role.name in CONFIG['ROLES']['admin_roles'] for role in ctx.author.roles)

@bot.command()
@commands.check(is_admin)
async def test(ctx):
    """Testet alle Systemfunktionen (Admin only)"""
    welcome_channel = bot.get_channel(CONFIG['CHANNELS']['welcome'])
    if welcome_channel:
        await welcome_channel.send("🎌 **TEST** Willkommensnachricht")
    
    log_channel = bot.get_channel(CONFIG['CHANNELS']['logs'])
    if log_channel:
        await log_channel.send("📝 **TEST** Join-Log")
        await log_channel.send("📝 **TEST** Leave-Log")
        await log_channel.send("📝 **TEST** Ban-Log")
    
    await ctx.send("✅ Alle Systeme funktionieren normal")

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"KRITISCHER FEHLER: {str(e)}")
        input("Drücke Enter zum Beenden...")