import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
import tempfile
from typing import Optional
import re

from app.models.user import User
from app.services.database import create_user, get_user, update_user_resume, get_users_by_category, get_all_users, update_user, delete_user
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
        # Acknowledge the interaction immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        # Create a new user
        user = User(name=name, phone=phone)
        user = await create_user(user)
        
        # Store the user ID in the waiting_for_resume dictionary
        waiting_for_resume[interaction.user.id] = user.id
        
        await interaction.followup.send(
            f"Thanks for registering, {name}! Please upload your resume as an attachment in your next message.",
            ephemeral=True
        )
    except Exception as e:
        print(f"Error in register command: {e}")
        try:
            # Try to respond if we haven't already
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Error registering: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Error registering: {str(e)}",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending error message: {follow_up_error}")


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
            temp_file_path = None
            
            try:
                # Check if the file is a valid document type
                file_ext = os.path.splitext(attachment.filename)[1].lower()
                valid_extensions = ['.pdf', '.doc', '.docx', '.txt', '.rtf']
                
                if file_ext not in valid_extensions:
                    await message.reply(f"Please upload a valid resume file (PDF, DOC, DOCX, TXT, or RTF). Received: {file_ext}")
                    return
                
                # Download the attachment to a temporary file
                temp_file_path = tempfile.mktemp(suffix=file_ext)
                await attachment.save(temp_file_path)
                
                # Process the resume
                file_url = attachment.url
                
                # Extract text from the resume
                print(f"Processing resume: {attachment.filename}")
                _, resume_text = await process_resume(temp_file_path)
                
                if not resume_text or len(resume_text.strip()) < 50:
                    await message.reply("I couldn't extract enough text from your resume. Please make sure your file is not corrupted or password-protected, and try again.")
                    return
                
                # Debug output
                print(f"Resume text extracted: {resume_text[:100]}...")
                
                # Update the user's resume
                user_id = waiting_for_resume[message.author.id]
                await update_user_resume(user_id, file_url, resume_text)
                
                # Remove the user from the waiting list
                del waiting_for_resume[message.author.id]
                
                # Send a confirmation message
                await message.reply("Thanks for uploading your resume! Your information has been saved. You can now use the `/connect` command to find connections.")
                
            except Exception as e:
                print(f"Error processing resume: {str(e)}")
                await message.reply(f"Error processing your resume: {str(e)}\nPlease try again or contact an administrator for help.")
            finally:
                # Clean up the temporary file
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        print(f"Error deleting temporary file: {str(e)}")
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
        # Acknowledge the interaction immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        # Get all users from the database
        candidates = await get_all_users()
        
        if not candidates:
            await interaction.followup.send(
                f"Sorry, there are no users in our database yet.",
                ephemeral=True
            )
            return
        
        # Find the best match using OpenAI
        try:
            best_match, explanation = await find_best_match(looking_for, candidates)
        except Exception as e:
            print(f"Error in find_best_match: {e}")
            await interaction.followup.send(
                f"Sorry, I encountered an error while finding a match: {str(e)}",
                ephemeral=True
            )
            return
        
        if best_match:
            try:
                # Clean up the explanation
                clean_explanation = explanation if explanation else "This person's skills and experience match your requirements."
                
                # Replace "Candidate X" references with the person's name
                for i, candidate in enumerate(candidates):
                    candidate_ref = f"Candidate {i+1}"
                    if candidate_ref in clean_explanation:
                        clean_explanation = clean_explanation.replace(candidate_ref, candidate.name)
                
                # Remove any remaining "Candidate X" references (for candidates not in our list)
                clean_explanation = re.sub(r'Candidate \d+', best_match.name, clean_explanation)
                
                # Limit the explanation length to avoid Discord message limits
                if len(clean_explanation) > 1500:
                    clean_explanation = clean_explanation[:1500] + "..."
                
                await interaction.followup.send(
                    f"I found a great match for you!\n\n"
                    f"Name: {best_match.name}\n"
                    f"Phone: {best_match.phone}\n\n"
                    f"{clean_explanation}\n\n"
                    f"Feel free to reach out to them directly!",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending match response: {e}")
                await interaction.followup.send(
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
                
                await interaction.followup.send(
                    f"Sorry, I couldn't find anyone matching your specific requirements for '{looking_for}'.\n\n"
                    f"Reason: {no_match_reason}\n\n"
                    f"Please try again with different criteria or check back later when more people have registered.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending no match response: {e}")
                await interaction.followup.send(
                    f"Sorry, I couldn't find a match and encountered an error: {str(e)}",
                    ephemeral=True
                )
    except Exception as e:
        print(f"Error in connect command: {e}")
        try:
            # Try to respond if we haven't already
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Error finding a connection: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Error finding a connection: {str(e)}",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending error message: {follow_up_error}")


@bot.tree.command(name="update", description="Update your information")
@app_commands.describe(
    name="Your full name (optional)",
    phone="Your phone number (optional)"
)
async def update_info(interaction: discord.Interaction, name: Optional[str] = None, phone: Optional[str] = None):
    """Command to update user information."""
    try:
        # Acknowledge the interaction immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        # Get the user's Discord ID
        discord_id = interaction.user.id
        
        # Try to find the user in the database
        user = await get_user(discord_id)
        
        if not user:
            await interaction.followup.send(
                "You haven't registered yet. Please use the `/register` command first.",
                ephemeral=True
            )
            return
        
        # Update the user's information
        updated = False
        update_message = "Your information has been updated:"
        
        if name:
            user.name = name
            updated = True
            update_message += f"\n- Name: {name}"
        
        if phone:
            user.phone = phone
            updated = True
            update_message += f"\n- Phone: {phone}"
        
        if not updated:
            # If no fields were provided, assume the user wants to update their resume
            waiting_for_resume[interaction.user.id] = user.id
            await interaction.followup.send(
                "Please upload your new resume as an attachment in your next message.",
                ephemeral=True
            )
            return
        
        # Save the updated user
        updated_user = await update_user(user)
        
        if not updated_user:
            await interaction.followup.send(
                "There was an error updating your information. Please try again later.",
                ephemeral=True
            )
            return
        
        await interaction.followup.send(update_message, ephemeral=True)
    except Exception as e:
        print(f"Error in update command: {e}")
        try:
            # Try to respond if we haven't already
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Error updating your information: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Error updating your information: {str(e)}",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending error message: {follow_up_error}")


@bot.tree.command(name="help", description="Get help with using the Super Connector bot")
async def help_command(interaction: discord.Interaction):
    """Command to provide help information."""
    try:
        # Acknowledge the interaction immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        help_message = (
            "# 🤖 Super Connector Bot Help\n\n"
            "Super Connector helps you find the right people to connect with based on your needs. "
            "Here are the available commands:\n\n"
            
            "## 📝 Registration & Profile\n"
            "- `/register [name] [phone]` - Register with the bot\n"
            "- `/update [name] [phone]` - Update your profile information\n\n"
            
            "## 🔍 Finding Connections\n"
            "- `/connect [looking_for]` - Find someone to connect with based on what you're looking for\n\n"
            
            "## ℹ️ Help & Information\n"
            "- `/help` - Display this help message\n\n"
            
            "## 📄 Resume Upload\n"
            "After registering or when updating your profile, you can upload your resume by attaching it to a message. "
            "Supported formats: PDF, DOC, DOCX, TXT, RTF\n\n"
            
            "## 🔒 Privacy\n"
            "Your information is only shared when someone specifically requests a connection that matches your profile."
        )
        
        await interaction.followup.send(help_message, ephemeral=True)
    except Exception as e:
        print(f"Error in help command: {e}")
        try:
            # Try to respond if we haven't already
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Error displaying help: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Error displaying help: {str(e)}",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending error message: {follow_up_error}")


async def start_bot():
    """Start the Discord bot."""
    await bot.start(DISCORD_TOKEN) 