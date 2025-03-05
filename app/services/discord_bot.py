import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
import tempfile
from typing import Optional

from app.models.user import User
from app.services.database import create_user, get_user, update_user_resume, get_users_by_category, get_all_users
from app.services.openai_service import find_best_match
from app.utils.resume_parser import process_resume

# Load environment variables
load_dotenv()

# Get Discord token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Dictionary to track users who are in the process of uploading a resume
waiting_for_resume = {}


@bot.event
async def on_ready():
    """Event handler for when the bot is ready."""
    print(f"{bot.user} is ready and online!")
    
    # Sync commands with Discord
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.tree.command(name="register", description="Register your information with the bot")
@app_commands.describe(
    name="Your full name",
    phone="Your phone number"
)
async def register(interaction: discord.Interaction, name: str, phone: str):
    """Command to register a user."""
    try:
        # Create a new user
        user = User(name=name, phone=phone)
        user = await create_user(user)
        
        # Store the user ID in the waiting_for_resume dictionary
        waiting_for_resume[interaction.user.id] = user.id
        
        await interaction.response.send_message(
            f"Thanks for registering, {name}! Please upload your resume as an attachment in your next message.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Error registering: {str(e)}",
            ephemeral=True
        )


@bot.event
async def on_message(message: discord.Message):
    """Event handler for when a message is received."""
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Check if the user is waiting to upload a resume
    if message.author.id in waiting_for_resume:
        # Check if the message has attachments
        if message.attachments:
            attachment = message.attachments[0]
            
            try:
                # Download the attachment to a temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(attachment.filename)[1]) as temp_file:
                    await attachment.save(temp_file.name)
                    
                    # Process the resume
                    file_url = attachment.url
                    
                    # Extract text from the resume
                    _, resume_text = await process_resume(temp_file.name)
                    
                    # Debug output
                    print(f"Resume text extracted: {resume_text[:100]}...")
                    
                    # Update the user's resume
                    user_id = waiting_for_resume[message.author.id]
                    await update_user_resume(user_id, file_url, resume_text)
                    
                    # Remove the user from the waiting list
                    del waiting_for_resume[message.author.id]
                    
                    # Send a confirmation message
                    await message.reply("Thanks for uploading your resume! Your information has been saved.")
                    
                    # Clean up the temporary file
                    os.unlink(temp_file.name)
            except Exception as e:
                await message.reply(f"Error processing your resume: {str(e)}")
                print(f"Error processing resume: {e}")
        else:
            await message.reply("Please upload your resume as an attachment.")
    
    # Process commands
    await bot.process_commands(message)


@bot.tree.command(name="connect", description="Find someone to connect with")
@app_commands.describe(
    looking_for="What kind of person are you looking for? (e.g., 'software engineer', 'marketing expert')"
)
async def connect(interaction: discord.Interaction, looking_for: str):
    """Command to find a connection."""
    try:
        # Get all users from the database
        candidates = await get_all_users()
        
        if not candidates:
            await interaction.response.send_message(
                f"Sorry, there are no users in our database yet.",
                ephemeral=True
            )
            return
        
        # Find the best match using OpenAI
        try:
            best_match, explanation = await find_best_match(looking_for, candidates)
        except Exception as e:
            print(f"Error in find_best_match: {e}")
            await interaction.response.send_message(
                f"Sorry, I encountered an error while finding a match: {str(e)}",
                ephemeral=True
            )
            return
        
        if best_match:
            try:
                # Extract a cleaner explanation by removing the candidate number prefix if present
                clean_explanation = explanation if explanation else "This person's skills and experience match your requirements."
                
                # Limit the explanation length to avoid Discord message limits
                if len(clean_explanation) > 1500:
                    clean_explanation = clean_explanation[:1500] + "..."
                
                await interaction.response.send_message(
                    f"I found a great match for you!\n\n"
                    f"Name: {best_match.name}\n"
                    f"Phone: {best_match.phone}\n\n"
                    f"Why this person is a good match: {clean_explanation}\n\n"
                    f"Feel free to reach out to them directly!",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending match response: {e}")
                await interaction.response.send_message(
                    f"I found a match ({best_match.name}), but encountered an error displaying the details: {str(e)}",
                    ephemeral=True
                )
        else:
            try:
                # Use the explanation from OpenAI if available, otherwise use a default message
                no_match_reason = explanation if explanation else "Your specific requirements couldn't be matched with our current database."
                
                # Limit the explanation length to avoid Discord message limits
                if len(no_match_reason) > 1500:
                    no_match_reason = no_match_reason[:1500] + "..."
                
                await interaction.response.send_message(
                    f"Sorry, I couldn't find anyone matching your specific requirements for '{looking_for}'.\n\n"
                    f"Reason: {no_match_reason}\n\n"
                    f"Please try again with different criteria or check back later when more people have registered.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending no match response: {e}")
                await interaction.response.send_message(
                    f"Sorry, I couldn't find a match and encountered an error: {str(e)}",
                    ephemeral=True
                )
    except Exception as e:
        print(f"Error in connect command: {e}")
        await interaction.response.send_message(
            f"Error finding a connection: {str(e)}",
            ephemeral=True
        )


async def start_bot():
    """Start the Discord bot."""
    await bot.start(DISCORD_TOKEN) 