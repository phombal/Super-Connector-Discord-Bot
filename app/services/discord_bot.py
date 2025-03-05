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
from app.services.mistral_service import find_best_match
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
        # Immediately acknowledge the interaction with a temporary response
        await interaction.response.send_message(
            "Processing your registration...",
            ephemeral=True
        )
        print(f"Initial acknowledgment sent for registration request from {name}")
        
        # Create a background task to process the request
        asyncio.create_task(process_registration_request(interaction, name, phone))
        
    except Exception as e:
        print(f"Error in register command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error processing your registration. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")


async def process_registration_request(interaction: discord.Interaction, name: str, phone: str):
    """Process a registration request asynchronously."""
    try:
        print(f"Processing registration in background for {name}")
        
        # Create a new user
        user = User(name=name, phone=phone)
        user = await create_user(user)
        
        # Store the user ID in the waiting_for_resume dictionary
        waiting_for_resume[interaction.user.id] = user.id
        
        print(f"Sending registration confirmation for {name}")
        try:
            await interaction.followup.send(
                f"Thanks for registering, {name}! Please upload your resume as an attachment in your next message.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error sending registration confirmation via followup: {e}")
            await send_dm_fallback(interaction.user, f"Thanks for registering, {name}! Please upload your resume as an attachment in your next message.")
            
    except Exception as e:
        print(f"Unhandled error in process_registration_request: {e}")
        try:
            await interaction.followup.send(
                "An unexpected error occurred while registering. Please try again later.",
                ephemeral=True
            )
        except Exception as follow_up_error:
            print(f"Error sending final error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, "An unexpected error occurred while registering. Please try again later.")


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
                print(f"Processing resume: {attachment.filename} for user {message.author.id}")
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
                print(f"Resume successfully processed for user {message.author.id}")
                try:
                    await message.reply("Thanks for uploading your resume! Your information has been saved. You can now use the `/connect` command to find connections.")
                except discord.errors.HTTPException as e:
                    print(f"HTTP Exception when replying to message: {e}")
                    try:
                        await message.channel.send(f"{message.author.mention} Thanks for uploading your resume! Your information has been saved. You can now use the `/connect` command to find connections.")
                    except Exception as channel_error:
                        print(f"Error sending channel message: {channel_error}")
                
            except discord.errors.HTTPException as e:
                print(f"HTTP Exception in on_message: {e}")
                try:
                    await message.reply(f"Error processing your resume: Discord API error. Please try again later.")
                except Exception as reply_error:
                    print(f"Error sending reply: {reply_error}")
            except Exception as e:
                print(f"Error processing resume: {str(e)}")
                try:
                    await message.reply(f"Error processing your resume: {str(e)}\nPlease try again or contact an administrator for help.")
                except Exception as reply_error:
                    print(f"Error sending reply: {reply_error}")
            finally:
                # Clean up the temporary file
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        print(f"Error deleting temporary file: {str(e)}")
        else:
            try:
                await message.reply("Please upload your resume as an attachment.")
            except Exception as e:
                print(f"Error sending reply: {e}")
    
    # Process commands
    await bot.process_commands(message)


@bot.tree.command(name="connect", description="Find someone to connect with")
@app_commands.describe(
    looking_for="What kind of person are you looking for? (e.g., 'software engineer', 'marketing expert')"
)
async def connect(interaction: discord.Interaction, looking_for: str):
    """Command to find a connection."""
    try:
        # Immediately acknowledge the interaction with a temporary response
        await interaction.response.send_message(
            f"🔍 Searching for someone who matches: '{looking_for}'...\n\n"
            f"This may take a moment. I'll send you the results as soon as they're ready.",
            ephemeral=True
        )
        print(f"Initial acknowledgment sent for connection request: '{looking_for}'")
        
        # Create a background task to process the request
        asyncio.create_task(process_connection_request(interaction, looking_for))
        
    except Exception as e:
        print(f"Error in connect command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error starting your search. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")


async def process_connection_request(interaction: discord.Interaction, looking_for: str):
    """Process a connection request asynchronously."""
    try:
        print(f"Processing connection request in background: '{looking_for}'")
        
        # Get all users from the database
        candidates = await get_all_users()
        
        if not candidates:
            try:
                await interaction.followup.send(
                    f"Sorry, there are no users in our network yet.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending no candidates message: {e}")
                await send_dm_fallback(interaction.user, f"Sorry, there are no users in our network yet.")
            return
        
        # Find the best match using Mistral
        try:
            print(f"Calling Mistral API to find match for '{looking_for}'")
            best_match, explanation = await find_best_match(looking_for, candidates)
            print(f"Received response from Mistral API")
        except Exception as e:
            print(f"Error in find_best_match: {e}")
            try:
                await interaction.followup.send(
                    f"Sorry, I encountered an error while finding a match. Please try again with more specific criteria.",
                    ephemeral=True
                )
            except Exception as follow_up_error:
                print(f"Error sending API error message: {follow_up_error}")
                await send_dm_fallback(interaction.user, f"Sorry, I encountered an error while finding a match. Please try again with more specific criteria.")
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
                
                # Remove any mentions of database, files, etc.
                clean_explanation = re.sub(r'(?i)(database|file|stored|record|system)', 'network', clean_explanation)
                
                # Limit the explanation length to avoid Discord message limits
                if len(clean_explanation) > 1500:
                    clean_explanation = clean_explanation[:1500] + "..."
                
                message = (
                    f"✅ I found a great match for you!\n\n"
                    f"Name: {best_match.name}\n"
                    f"Phone: {best_match.phone}\n\n"
                    f"{clean_explanation}\n\n"
                    f"Feel free to reach out to them directly!"
                )
                
                print(f"Sending match response for {best_match.name}")
                try:
                    await interaction.followup.send(message, ephemeral=True)
                except Exception as e:
                    print(f"Error sending match response via followup: {e}")
                    await send_dm_fallback(interaction.user, message)
                    
            except Exception as e:
                print(f"Error preparing match response: {e}")
                try:
                    await interaction.followup.send(
                        f"I found a match ({best_match.name}), but encountered an error displaying the details. Please try again.",
                        ephemeral=True
                    )
                except Exception as follow_up_error:
                    print(f"Error sending match error via followup: {follow_up_error}")
                    await send_dm_fallback(interaction.user, f"I found a match ({best_match.name}), but encountered an error displaying the details. Please try again.")
        else:
            try:
                # Use the explanation from Mistral if available, otherwise use a default message
                no_match_reason = explanation if explanation else "Your specific requirements couldn't be matched with our current network."
                
                # Remove any mentions of database, files, etc.
                no_match_reason = re.sub(r'(?i)(database|file|stored|record|system)', 'network', no_match_reason)
                
                # Additional privacy protection: Remove any candidate names from the explanation
                for candidate in candidates:
                    if candidate.name and len(candidate.name) > 2:  # Avoid replacing very short names that might be common words
                        no_match_reason = re.sub(r'(?i)\b' + re.escape(candidate.name) + r'\b', "a candidate", no_match_reason)
                
                # Remove any "Candidate X" references
                no_match_reason = re.sub(r'Candidate \d+', "a candidate", no_match_reason)
                
                # Limit the explanation length to avoid Discord message limits
                if len(no_match_reason) > 1500:
                    no_match_reason = no_match_reason[:1500] + "..."
                
                message = (
                    f"❌ Sorry, I couldn't find anyone matching your specific requirements for '{looking_for}'.\n\n"
                    f"Reason: {no_match_reason}\n\n"
                    f"Please try again with different criteria or check back later when more people have registered."
                )
                
                print(f"Sending no-match response for '{looking_for}'")
                try:
                    await interaction.followup.send(message, ephemeral=True)
                except Exception as e:
                    print(f"Error sending no-match response via followup: {e}")
                    await send_dm_fallback(interaction.user, message)
                    
            except Exception as e:
                print(f"Error preparing no-match response: {e}")
                try:
                    await interaction.followup.send(
                        f"Sorry, I couldn't find a match for your criteria. Please try again with different requirements.",
                        ephemeral=True
                    )
                except Exception as follow_up_error:
                    print(f"Error sending no-match error via followup: {follow_up_error}")
                    await send_dm_fallback(interaction.user, f"Sorry, I couldn't find a match for your criteria. Please try again with different requirements.")
    except Exception as e:
        print(f"Unhandled error in process_connection_request: {e}")
        try:
            await interaction.followup.send(
                "An unexpected error occurred while processing your request. Please try again later.",
                ephemeral=True
            )
        except Exception as follow_up_error:
            print(f"Error sending final error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, "An unexpected error occurred while processing your request. Please try again later.")


async def send_dm_fallback(user, message):
    """Send a direct message to a user as a fallback when interaction responses fail."""
    try:
        # Create a DM channel with the user
        dm_channel = await user.create_dm()
        
        # Send the message
        await dm_channel.send(message)
        print(f"Sent DM fallback to user {user.id}")
    except Exception as e:
        print(f"Failed to send DM fallback to user {user.id}: {e}")


@bot.tree.command(name="update", description="Update your information")
@app_commands.describe(
    name="Your full name (optional)",
    phone="Your phone number (optional)"
)
async def update_info(interaction: discord.Interaction, name: Optional[str] = None, phone: Optional[str] = None):
    """Command to update user information."""
    try:
        # Immediately acknowledge the interaction with a temporary response
        await interaction.response.send_message(
            "Processing your update request...",
            ephemeral=True
        )
        print(f"Initial acknowledgment sent for update request from user {interaction.user.id}")
        
        # Create a background task to process the request
        asyncio.create_task(process_update_request(interaction, name, phone))
        
    except Exception as e:
        print(f"Error in update command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error processing your update. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")


async def process_update_request(interaction: discord.Interaction, name: Optional[str], phone: Optional[str]):
    """Process an update request asynchronously."""
    try:
        print(f"Processing update request in background for user {interaction.user.id}")
        
        # Get the user's Discord ID
        discord_id = interaction.user.id
        
        # Try to find the user in the database
        user = await get_user(discord_id)
        
        if not user:
            try:
                await interaction.followup.send(
                    "You haven't registered yet. Please use the `/register` command first.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending not registered message: {e}")
                await send_dm_fallback(interaction.user, "You haven't registered yet. Please use the `/register` command first.")
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
            try:
                await interaction.followup.send(
                    "Please upload your new resume as an attachment in your next message.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending resume request message: {e}")
                await send_dm_fallback(interaction.user, "Please upload your new resume as an attachment in your next message.")
            return
        
        # Save the updated user
        updated_user = await update_user(user)
        
        if not updated_user:
            try:
                await interaction.followup.send(
                    "There was an error updating your information. Please try again later.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending update error message: {e}")
                await send_dm_fallback(interaction.user, "There was an error updating your information. Please try again later.")
            return
        
        print(f"Sending update confirmation for user {interaction.user.id}")
        try:
            await interaction.followup.send(update_message, ephemeral=True)
        except Exception as e:
            print(f"Error sending update confirmation via followup: {e}")
            await send_dm_fallback(interaction.user, update_message)
            
    except Exception as e:
        print(f"Unhandled error in process_update_request: {e}")
        try:
            await interaction.followup.send(
                "An unexpected error occurred while updating your information. Please try again later.",
                ephemeral=True
            )
        except Exception as follow_up_error:
            print(f"Error sending final error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, "An unexpected error occurred while updating your information. Please try again later.")


@bot.tree.command(name="help", description="Get help with using the Super Connector bot")
async def help_command(interaction: discord.Interaction):
    """Command to provide help information."""
    try:
        # Immediately acknowledge the interaction with a temporary response
        await interaction.response.send_message(
            "Fetching help information...",
            ephemeral=True
        )
        print(f"Initial acknowledgment sent for help request from user {interaction.user.id}")
        
        # Create a background task to process the request
        asyncio.create_task(process_help_request(interaction))
        
    except Exception as e:
        print(f"Error in help command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error fetching help information. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")


async def process_help_request(interaction: discord.Interaction):
    """Process a help request asynchronously."""
    try:
        print(f"Processing help request in background for user {interaction.user.id}")
        
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
        
        print(f"Sending help information to user {interaction.user.id}")
        try:
            await interaction.followup.send(help_message, ephemeral=True)
        except Exception as e:
            print(f"Error sending help information via followup: {e}")
            await send_dm_fallback(interaction.user, help_message)
            
    except Exception as e:
        print(f"Unhandled error in process_help_request: {e}")
        try:
            await interaction.followup.send(
                "An unexpected error occurred while fetching help information. Please try again later.",
                ephemeral=True
            )
        except Exception as follow_up_error:
            print(f"Error sending final error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, "An unexpected error occurred while fetching help information. Please try again later.")


async def start_bot():
    """Start the Discord bot."""
    await bot.start(DISCORD_TOKEN) 