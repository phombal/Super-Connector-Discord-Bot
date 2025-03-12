import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
import tempfile
from typing import Optional, Dict, List, Tuple
import re
import json
import time
from collections import defaultdict, deque
from openai import OpenAI

from app.models.user import User
from app.services.database import create_user, get_user, update_user_resume, get_users_by_category, get_all_users, update_user, delete_user, add_connection_request
from app.services.openai_service import find_best_match
from app.utils.resume_parser import process_resume

# Load environment variables
load_dotenv()

# Get Discord token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Dictionary to track users who are in the process of uploading a resume
waiting_for_resume = {}
# Dictionary to track which channel to use for resume uploads (DM or original channel)
resume_upload_channels = {}

# Message history tracking (channel_id -> list of (timestamp, author, content) tuples)
# Using deque with maxlen to automatically limit history size
message_history = defaultdict(lambda: deque(maxlen=50))  # Store last 50 messages per channel


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
        # Immediately acknowledge the interaction with a deferred response
        # This prevents the "application did not respond" error
        await interaction.response.defer(ephemeral=True, thinking=True)
        print(f"Deferred response for registration request from {name}")
        
        # Process the request directly (no need for background task with defer)
        await process_registration_request(interaction, name, phone)
        
    except Exception as e:
        print(f"Error in register command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error processing your registration. Please try again later.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Sorry, I encountered an error processing your registration. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, "Sorry, I encountered an error processing your registration. Please try again later.")


async def process_registration_request(interaction: discord.Interaction, name: str, phone: str):
    """Process a registration request asynchronously."""
    try:
        print(f"Processing registration for {name}")
        
        # Get the user's Discord ID
        discord_id = str(interaction.user.id)
        
        # Check if user already exists
        existing_user = await get_user(discord_id)
        if existing_user:
            try:
                await interaction.followup.send(
                    f"You're already registered as {existing_user.name}. Use the `/update` command if you want to update your information.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending already registered message: {e}")
                await send_dm_fallback(interaction.user, f"You're already registered as {existing_user.name}. Use the `/update` command if you want to update your information.")
            return
        
        # Create a new user
        user = User(name=name, phone=phone)
        user = await create_user(user, discord_id=discord_id)
        
        if not user:
            try:
                await interaction.followup.send(
                    "There was an error creating your profile. Please try again later.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending creation error message: {e}")
                await send_dm_fallback(interaction.user, "There was an error creating your profile. Please try again later.")
            return
        
        # Store the user ID in the waiting_for_resume dictionary
        waiting_for_resume[interaction.user.id] = user.id
        
        print(f"Sending registration confirmation for {name}")
        try:
            await interaction.followup.send(
                f"Thanks for registering, {name}! Please check your DMs to upload your resume privately.",
                ephemeral=True
            )
            # Send a DM to the user requesting the resume
            await request_resume_via_dm(interaction.user, "Thanks for registering! Please upload your resume as an attachment in this private message.")
        except Exception as e:
            print(f"Error sending registration confirmation via followup: {e}")
            await send_dm_fallback(interaction.user, f"Thanks for registering, {name}! Please upload your resume as an attachment in this private message.")
            
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


async def request_resume_via_dm(user, message):
    """Send a DM to the user requesting their resume."""
    try:
        # Create a DM channel with the user
        dm_channel = await user.create_dm()
        
        # Send the message
        await dm_channel.send(message)
        print(f"Sent resume request DM to user {user.id}")
    except Exception as e:
        print(f"Failed to send resume request DM to user {user.id}: {e}")


@bot.event
async def on_message(message: discord.Message):
    """Event handler for when a message is received."""
    # Debug print
    print(f"Received message: '{message.content}' from {message.author.name} in {message.channel.name if hasattr(message.channel, 'name') else 'DM'}")
    
    # Store message in history (even bot messages)
    channel_id = str(message.channel.id)
    message_history[channel_id].append((
        time.time(),
        message.author.name,
        message.content
    ))
    
    # Debug: Print current message history size
    print(f"Message history for channel {channel_id} now has {len(message_history[channel_id])} messages")
    
    # Ignore messages from the bot itself
    if message.author == bot.user:
        print("Ignoring message from self")
        return
    
    # Check if this is a DM channel
    is_dm = isinstance(message.channel, discord.DMChannel)
    print(f"Message is in DM: {is_dm}")
    
    # Check if the user is waiting to upload a resume
    if message.author.id in waiting_for_resume:
        print(f"User {message.author.id} is waiting for resume upload")
        
        # For resume uploads, we only process them in DMs for privacy
        if not is_dm and message.attachments:
            # If they try to upload in a public channel, redirect them to DMs
            try:
                await message.reply("For privacy reasons, please upload your resume in a direct message with me instead of in this channel. I've sent you a DM.", delete_after=10)
                await message.delete()  # Delete the message with the attachment for privacy
                await request_resume_via_dm(message.author, "Please upload your resume as an attachment in this private message for privacy.")
            except Exception as e:
                print(f"Error redirecting resume upload to DM: {e}")
            return
        
        # Process resume uploads in DMs
        if is_dm and message.attachments:
            attachment = message.attachments[0]
            temp_file_path = None
            
            try:
                # Check if the file is a valid document type
                file_ext = os.path.splitext(attachment.filename)[1].lower()
                valid_extensions = ['.pdf', '.doc', '.docx', '.txt', '.rtf']
                
                if file_ext not in valid_extensions:
                    await message.reply(f"Please upload a valid resume file (PDF, DOC, DOCX, TXT, or RTF). Received: {file_ext}")
                    return
                
                # Get the user from the database
                user_id = waiting_for_resume[message.author.id]
                user = await get_user(user_id)
                
                # Check if the user already has a resume
                if user and user.has_resume:
                    await message.reply("You've already uploaded a resume. You can only upload one resume. If you want to update your resume, use the `/update` command.")
                    # Remove the user from the waiting list
                    del waiting_for_resume[message.author.id]
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
                print(f"Updating resume for user ID: {user_id}")
                updated_user = await update_user_resume(user_id, file_url, resume_text)
                
                if not updated_user:
                    await message.reply("There was an error saving your resume. Please try again or contact an administrator for help.")
                    return
                
                # Remove the user from the waiting list
                del waiting_for_resume[message.author.id]
                
                # Send a confirmation message
                print(f"Resume successfully processed for user {message.author.id}")
                await message.reply("Thanks for uploading your resume! Your information has been saved privately. You can now use the `/connect` command to find connections.")
                
            except discord.errors.HTTPException as e:
                print(f"HTTP Exception in on_message: {e}")
                await message.reply(f"Error processing your resume: Discord API error. Please try again later.")
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
        elif is_dm and not message.attachments:
            # If the user is expected to upload a resume but sends a message instead in DM
            # Check if they're trying to cancel the resume upload
            if message.content.lower() in ["cancel", "stop", "quit", "exit"]:
                # Remove the user from the waiting list
                del waiting_for_resume[message.author.id]
                await message.reply("Resume upload cancelled. You can use the `/register` command again if you change your mind.")
            else:
                await message.reply("Please upload your resume as an attachment, or type 'cancel' to stop the resume upload process.")
        return
    
    # Check if the message has attachments (potential resume)
    if message.attachments and not message.author.id in waiting_for_resume:
        attachment = message.attachments[0]
        temp_file_path = None
        
        # Check if the file is a valid document type
        file_ext = os.path.splitext(attachment.filename)[1].lower()
        valid_extensions = ['.pdf', '.doc', '.docx', '.txt', '.rtf']
        
        if file_ext in valid_extensions:
            print(f"Detected potential resume upload from {message.author.name}: {attachment.filename}")
            
            # Show typing indicator to indicate the bot is processing
            async with message.channel.typing():
                try:
                    # Download the attachment to a temporary file
                    temp_file_path = tempfile.mktemp(suffix=file_ext)
                    await attachment.save(temp_file_path)
                    
                    # Extract text from the resume
                    print(f"Processing resume for feedback: {attachment.filename}")
                    _, resume_text = await process_resume(temp_file_path)
                    
                    if not resume_text or len(resume_text.strip()) < 50:
                        await message.reply("I couldn't extract enough text from your resume. Please make sure your file is not corrupted or password-protected, and try again.")
                        return
                    
                    # Debug output
                    print(f"Resume text extracted for feedback: {resume_text[:100]}...")
                    
                    # Generate feedback using OpenAI API
                    feedback = await get_resume_feedback(resume_text, message.author.name)
                    
                    # Ensure the feedback is within Discord's message length limits (2000 characters)
                    if len(feedback) > 1900:  # Leave some buffer
                        feedback = feedback[:1900] + "..."
                    
                    # Send the feedback
                    await message.reply(feedback)
                    print(f"Sent resume feedback to {message.author.id}")
                    
                except Exception as e:
                    print(f"Error processing resume for feedback: {e}")
                    try:
                        error_msg = str(e)
                        # Ensure error message is within Discord's limits
                        if len(error_msg) > 1900:
                            error_msg = error_msg[:1900] + "..."
                        
                        await message.reply("I noticed you uploaded what looks like a resume, but I encountered an error while analyzing it. Please try using the `/register` command instead, which uses a different process to handle resumes.")
                    except Exception as reply_error:
                        print(f"Error sending reply: {reply_error}")
                finally:
                    # Clean up the temporary file
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except Exception as e:
                            print(f"Error deleting temporary file: {str(e)}")
            
            # We've handled the resume, so return
            return
    
    # Process all normal messages (not commands) with OpenAI API
    if not message.content.startswith('/') and not message.content.startswith('!'):
        print(f"Processing message with OpenAI API: '{message.content}'")
        
        # Show typing indicator to indicate the bot is processing
        async with message.channel.typing():
            try:
                # Get user's message content
                user_message = message.content
                
                # Remove bot mention if present
                if bot.user.id:
                    user_message = user_message.replace(f'<@{bot.user.id}>', '').strip()
                
                if not user_message:
                    user_message = "Hello"  # Default message if the user just mentioned the bot
                
                print(f"Processing chat message from {message.author.id}: {user_message}")
                
                # Call OpenAI API for a response, passing the channel ID for history access
                response_text = await get_openai_response(
                    user_message, 
                    message.author.name,
                    channel_id=str(message.channel.id)
                )
                
                # Ensure the response is within Discord's message length limits
                if len(response_text) > 1900:  # Leave some buffer
                    response_text = response_text[:1900] + "..."
                
                # Send the response
                await message.reply(response_text)
                print(f"Sent chat response to {message.author.id}")
            except Exception as e:
                print(f"Error processing chat message: {e}")
                try:
                    await message.reply("I'm sorry, I encountered an error processing your message. Please try again later.")
                except Exception as reply_error:
                    print(f"Error sending error reply: {reply_error}")
    else:
        print(f"Message starts with command prefix: '{message.content}'")
    
    # Process commands
    await bot.process_commands(message)


async def get_openai_response(user_message: str, username: str, channel_id: str = None) -> str:
    """
    Get a response from the OpenAI API for a chat message.
    
    Args:
        user_message: The user's message
        username: The user's name
        channel_id: The channel ID for accessing message history
        
    Returns:
        The response from OpenAI
    """
    try:
        # Check if the message is asking about conversation history
        history_keywords = [
            "what was this conversation about",
            "what were we talking about",
            "what did we discuss",
            "conversation history",
            "previous messages",
            "what did you say",
            "what did i say",
            "our conversation",
            "our discussion",
            "our chat",
            "this convo",
            "this conversation",
            "what's been said",
            "what has been said",
            "summarize our conversation",
            "last question",
            "previous question",
            "earlier message",
            "what i asked",
            "what we said",
            "what was said",
            "chat history",
            "message history"
        ]
        
        # More sophisticated history request detection
        is_history_request = False
        
        # Check for exact keyword matches
        if any(keyword in user_message.lower() for keyword in history_keywords):
            is_history_request = True
        
        # Check for question patterns about past interactions
        question_patterns = [
            r"what (did|was) (the )?(last|previous)",
            r"what (have|had) (we|i|you) (been )?(talk|speak|chat|discuss)",
            r"what (was|were) (i|we|you) (talk|speak|chat|discuss)",
            r"can you (remember|recall)",
            r"do you (remember|recall)",
            r"tell me (about|what) (we|i|you) (said|talked|discussed)"
        ]
        
        if any(re.search(pattern, user_message.lower()) for pattern in question_patterns):
            is_history_request = True
        
        print(f"Is history request: {is_history_request}, Channel ID: {channel_id}")
        
        # Always include conversation history for context, but with different instructions
        # based on whether it's a direct history request or not
        system_prompt = """You are a helpful assistant for a professional networking platform called Super Connector. 
        
Your role is to help users with their networking needs, answer questions about the platform, and provide career advice including resume improvement tips.

About Super Connector:
- It's a Discord bot that helps people connect with others based on their skills and experience
- Users can register with /register, update their info with /update, and find connections with /connect
- Users can upload their resumes to improve matching
- The platform uses AI to match people based on their skills and what they're looking for
- The platform can also analyze resumes and provide feedback when users upload them directly

When responding:
1. Be friendly, professional, and helpful
2. If users ask about finding connections, suggest they use the /connect command
3. If users want to register, direct them to the /register command
4. For help with commands, suggest the /help command
5. If users ask about resume advice or improvement, provide specific, actionable tips directly in your response
6. Don't make up information about the platform that isn't mentioned above
7. Keep responses concise and focused on helping with networking and career development

Resume improvement tips you can provide include:
- Using strong action verbs
- Quantifying achievements with numbers
- Tailoring the resume to specific job descriptions
- Formatting for readability
- Highlighting relevant skills and experience
- Avoiding common resume mistakes

Remember that your primary purpose is to facilitate professional networking and help users navigate the platform and improve their career prospects.
"""

        # Always include history if available, regardless of whether it's a history request
        if channel_id:
            # Debug: Print message history for this channel
            if channel_id in message_history:
                print(f"Message history for channel {channel_id}: {len(message_history[channel_id])} messages")
                for i, (ts, author, content) in enumerate(list(message_history[channel_id])[-10:]):
                    print(f"  {i}: {author}: {content[:50]}...")
            else:
                print(f"No message history for channel {channel_id}")
            
            # Get the conversation history for this channel
            history = list(message_history.get(channel_id, []))
            
            if history and len(history) > 1:  # Ensure we have more than just the current message
                # Format the history for the prompt
                history_text = "Here is the recent conversation history:\n\n"
                for i, (timestamp, author, content) in enumerate(history[-15:]):  # Last 15 messages
                    if content:  # Skip empty messages
                        history_text += f"{author}: {content}\n"
                
                # Add appropriate instructions based on whether it's a history request
                if is_history_request:
                    system_prompt += "\n\nThe user is asking about the conversation history. Directly answer their question about previous messages, referring to the conversation history provided. Be specific about what was discussed, who said what, and any questions that were asked."
                else:
                    system_prompt += "\n\nUse the conversation history to maintain context, but focus on answering the user's current question. You don't need to explicitly mention the history unless it's directly relevant to their question."
                
                # Prepare the user prompt with history
                user_prompt = f"{username} is asking: {user_message}\n\n{history_text}"
                
                print(f"Including conversation history in prompt. History length: {len(history_text)} characters")
            else:
                # No substantial history available
                user_prompt = f"{username}: {user_message}"
                if is_history_request:
                    system_prompt += "\n\nThe user is asking about conversation history, but there isn't enough history yet. Politely explain that the conversation just started and there isn't much history to summarize."
                print("No substantial conversation history available to include")
        else:
            # No channel ID available
            user_prompt = f"{username}: {user_message}"
            if is_history_request:
                system_prompt += "\n\nThe user is asking about conversation history, but you don't have access to the history. Politely explain that you can't recall the previous messages."
            print("No channel ID provided, cannot include conversation history")

        # Initialize OpenAI client
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Call OpenAI API directly
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=500,
            temperature=0.7  # Higher temperature for more conversational responses
        )
        
        # Extract the response
        ai_response = response.choices[0].message.content.strip()
        
        return ai_response
    except Exception as e:
        print(f"Error calling OpenAI API for chat: {e}")
        return "I'm sorry, I'm having trouble processing your request right now. Please try again later or use one of our commands like /help, /register, or /connect."


@bot.tree.command(name="connect", description="Find someone to connect with")
@app_commands.describe(
    looking_for="What kind of person are you looking for? (e.g., 'software engineer', 'marketing expert')"
)
async def connect(interaction: discord.Interaction, looking_for: str):
    """Command to find a connection."""
    try:
        # Immediately acknowledge the interaction with a deferred response
        # This prevents the "application did not respond" error
        await interaction.response.defer(ephemeral=True, thinking=True)
        print(f"Deferred response for connection request: '{looking_for}'")
        
        # Process the request directly (no need for background task with defer)
        await process_connection_request(interaction, looking_for)
        
    except Exception as e:
        print(f"Error in connect command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error starting your search. Please try again later.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Sorry, I encountered an error starting your search. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, f"Sorry, I encountered an error starting your search. Please try again later.")


async def process_connection_request(interaction: discord.Interaction, looking_for: str):
    """Process a connection request asynchronously."""
    try:
        print(f"Processing connection request: '{looking_for}'")
        
        # Get all users from the database
        candidates = await get_all_users()
        
        if not candidates:
            try:
                await interaction.followup.send(
                    f"Sorry, there are no users in our network yet. Please check back later when more people have registered.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending no candidates message: {e}")
                await send_dm_fallback(interaction.user, f"Sorry, there are no users in our network yet. Please check back later when more people have registered.")
            return
        
        # Filter candidates to only include those with resumes
        candidates_with_resumes = [c for c in candidates if c.resume_text and len(c.resume_text.strip()) > 0]
        
        if not candidates_with_resumes:
            try:
                await interaction.followup.send(
                    f"Sorry, none of the users in our network have uploaded resumes yet. Please check back later.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending no resumes message: {e}")
                await send_dm_fallback(interaction.user, f"Sorry, none of the users in our network have uploaded resumes yet. Please check back later.")
            return
        
        # Find the best match using OpenAI
        try:
            print(f"Calling OpenAI API to find match for '{looking_for}'")
            best_match, explanation = await find_best_match(looking_for, candidates_with_resumes)
            print(f"Received response from OpenAI API")
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
            await send_connection_response(interaction, best_match, explanation, candidates_with_resumes)
        else:
            # Handle the case where no match was found
            try:
                # Use the explanation from OpenAI if available, otherwise use a default message
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
                    f"❌ I couldn't find a match for '{looking_for}' in our current network.\n\n"
                    f"{no_match_reason}\n\n"
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


async def send_connection_response(interaction: discord.Interaction, best_match, explanation, candidates):
    """Send a connection response to the user."""
    try:
        # Clean up the explanation
        clean_explanation = explanation if explanation else "This person's skills and experience may be relevant to your requirements."
        
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
            f"✅ I found a connection for you!\n\n"
            f"Name: {best_match.name}\n"
            f"Phone: {best_match.phone}\n\n"
            f"{clean_explanation}\n\n"
            f"Feel free to reach out to them directly!"
        )
        
        # Record this connection request
        await add_connection_request(best_match.id, str(interaction.user.id))
        
        print(f"Sending match response for {best_match.name}")
        try:
            # Send the response as a followup to the deferred response
            await interaction.followup.send(message, ephemeral=True)
        except Exception as e:
            print(f"Error sending match response via followup: {e}")
            # Try to send a DM as a fallback
            await send_dm_fallback(interaction.user, message)
    except Exception as e:
        print(f"Error in send_connection_response: {e}")
        try:
            # Send a simplified error message as a followup
            await interaction.followup.send(
                f"I found a match ({best_match.name}), but encountered an error displaying the details. Please try again.",
                ephemeral=True
            )
        except Exception as follow_up_error:
            print(f"Error sending match error via followup: {follow_up_error}")
            await send_dm_fallback(interaction.user, f"I found a match ({best_match.name}), but encountered an error displaying the details. Please try again.")


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
    phone="Your phone number (optional)",
    update_resume="Whether to update your resume (optional)"
)
async def update_info(interaction: discord.Interaction, name: Optional[str] = None, phone: Optional[str] = None, update_resume: Optional[bool] = False):
    """Command to update user information."""
    try:
        # Immediately acknowledge the interaction with a deferred response
        # This prevents the "application did not respond" error
        await interaction.response.defer(ephemeral=True, thinking=True)
        print(f"Deferred response for update request from user {interaction.user.id}")
        
        # Process the request directly (no need for background task with defer)
        await process_update_request(interaction, name, phone, update_resume)
        
    except Exception as e:
        print(f"Error in update command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error processing your update. Please try again later.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Sorry, I encountered an error processing your update. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, "Sorry, I encountered an error processing your update. Please try again later.")


async def process_update_request(interaction: discord.Interaction, name: Optional[str], phone: Optional[str], update_resume: Optional[bool]):
    """Process an update request asynchronously."""
    try:
        print(f"Processing update request for user {interaction.user.id}")
        
        # Get the user's Discord ID
        discord_id = str(interaction.user.id)
        
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
        
        if update_resume:
            # Check if the user already has a resume
            if user.has_resume:
                # Store the user ID in the waiting_for_resume dictionary
                waiting_for_resume[interaction.user.id] = user.id
                try:
                    await interaction.followup.send(
                        "Please check your DMs to upload your new resume privately. This will replace your existing resume.",
                        ephemeral=True
                    )
                    # Send a DM to the user requesting the resume
                    await request_resume_via_dm(interaction.user, "Please upload your new resume as an attachment in this private message. This will replace your existing resume.")
                except Exception as e:
                    print(f"Error sending resume update message: {e}")
                    await send_dm_fallback(interaction.user, "Please upload your new resume as an attachment in this private message. This will replace your existing resume.")
                return
            else:
                # Store the user ID in the waiting_for_resume dictionary
                waiting_for_resume[interaction.user.id] = user.id
                try:
                    await interaction.followup.send(
                        "Please check your DMs to upload your resume privately.",
                        ephemeral=True
                    )
                    # Send a DM to the user requesting the resume
                    await request_resume_via_dm(interaction.user, "Please upload your resume as an attachment in this private message.")
                except Exception as e:
                    print(f"Error sending resume request message: {e}")
                    await send_dm_fallback(interaction.user, "Please upload your resume as an attachment in this private message.")
                return
        
        if not updated and not update_resume:
            try:
                await interaction.followup.send(
                    "No information was provided to update. Please specify at least one field to update or set update_resume to true.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending no update message: {e}")
                await send_dm_fallback(interaction.user, "No information was provided to update. Please specify at least one field to update or set update_resume to true.")
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
        # Immediately acknowledge the interaction with a deferred response
        # This prevents the "application did not respond" error
        await interaction.response.defer(ephemeral=True, thinking=True)
        print(f"Deferred response for help request from user {interaction.user.id}")
        
        # Process the request directly (no need for background task with defer)
        await process_help_request(interaction)
        
    except Exception as e:
        print(f"Error in help command initial response: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, I encountered an error fetching help information. Please try again later.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Sorry, I encountered an error fetching help information. Please try again later.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            print(f"Error sending initial error message: {follow_up_error}")
            await send_dm_fallback(interaction.user, "Sorry, I encountered an error fetching help information. Please try again later.")


async def process_help_request(interaction: discord.Interaction):
    """Process a help request asynchronously."""
    try:
        print(f"Processing help request for user {interaction.user.id}")
        
        help_message = (
            "# 🤖 Super Connector Bot Help\n\n"
            "Super Connector helps you find the right people to connect with based on your needs. "
            "Here are the available commands:\n\n"
            
            "## 📝 Registration & Profile\n"
            "- `/register [name] [phone]` - Register with the bot\n"
            "- `/update [name] [phone]` - Update your profile information\n"
            "- `/profile` - View your profile information, including resume status and connection history\n\n"
            
            "## 🔍 Finding Connections\n"
            "- `/connect [looking_for]` - Find someone to connect with based on what you're looking for\n\n"
            
            "## ℹ️ Help & Information\n"
            "- `/help` - Display this help message\n\n"
            
            "## 💬 Chat Functionality\n"
            "You can also chat with me directly! Just mention me (@Super Connector) in a message or send me a direct message. "
            "I can answer questions about the platform and help guide you through the process.\n\n"
            
            "## 📄 Resume Upload\n"
            "After registering, you can upload your resume by attaching it to a message. "
            "You can only upload one resume. If you want to update your resume, use the `/update` command.\n"
            "Supported formats: PDF, DOC, DOCX, TXT, RTF\n\n"
            
            "## 🔒 Privacy\n"
            "Your information is only shared when someone specifically requests a connection that matches your profile. "
            "You can see how many people have received your contact information by using the `/profile` command."
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


async def get_resume_feedback(resume_text: str, username: str) -> str:
    """
    Generate feedback for a resume using the OpenAI API.
    
    Args:
        resume_text: The extracted text from the resume
        username: The user's name
        
    Returns:
        Feedback on the resume
    """
    try:
        # Prepare an extremely concise system prompt that emphasizes brevity
        system_prompt = """You are a resume reviewer providing concise, actionable feedback. 

IMPORTANT: Keep your response SHORT and FOCUSED. Limit your review to 3-5 key points maximum.

Your review should:
1. Briefly mention 1-2 strengths of the resume
2. Identify 2-3 specific areas for improvement
3. Provide very brief, actionable suggestions

Be direct and to the point. Avoid lengthy explanations. Focus on the most impactful changes the person could make.
"""

        # Limit resume text to 1000 characters to avoid token limits
        limited_resume_text = resume_text[:1000]
        if len(resume_text) > 1000:
            limited_resume_text += "... [truncated]"

        # Prepare a minimal user prompt that emphasizes brevity
        user_prompt = f"Provide a BRIEF resume review for {username}. Resume: {limited_resume_text}"

        # Print debug information
        print(f"System prompt length: {len(system_prompt)} characters")
        print(f"User prompt length: {len(user_prompt)} characters")
        print(f"Total message content length: {len(system_prompt) + len(user_prompt)} characters")
        
        # Initialize OpenAI client
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Call OpenAI API directly
        print("Sending request to OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5,
            max_tokens=400  # Reduced token limit to encourage brevity
        )
        
        # Extract the response
        ai_response = response.choices[0].message.content.strip()
        
        if not ai_response:
            print("Empty response from API")
            raise Exception("Empty response from API")
        
        # Format the response - ensure it's within Discord's message length limits
        formatted_response = f"# 📄 Resume Review\n\n{ai_response[:1500]}"
        
        # Add a note only if there's room
        if len(formatted_response) < 1800:
            formatted_response += "\n\n*This is a brief automated review. For more detailed feedback, consider consulting with a career counselor.*"
        
        # Final check to ensure we're within Discord's limits
        if len(formatted_response) > 1900:
            formatted_response = formatted_response[:1900] + "..."
            
        print(f"Final response length: {len(formatted_response)} characters")
        
        return formatted_response
    except Exception as e:
        print(f"Error generating resume feedback: {e}")
        return "I noticed you uploaded what looks like a resume, but I encountered an error while analyzing it. Please try using the `/register` command instead, which uses a different process to handle resumes."


@bot.tree.command(name="profile", description="View your current profile information")
async def view_profile(interaction: discord.Interaction):
    """Command to view user's profile information."""
    try:
        # Immediately acknowledge the interaction with a deferred response
        # This prevents the "application did not respond" error
        await interaction.response.defer(ephemeral=True, thinking=True)
        print(f"Deferred response for profile request from user {interaction.user.id}")
        
        # Get the user's Discord ID
        discord_id = str(interaction.user.id)
        print(f"Looking up profile for Discord ID: {discord_id}")
        
        # Try to find the user in the database
        user = await get_user(discord_id)
        
        if not user:
            await interaction.followup.send(
                "You haven't registered yet. Please use the `/register` command first.",
                ephemeral=True
            )
            return
        
        # Create a profile message
        profile_message = f"**Your Profile Information**\n\n"
        profile_message += f"Name: {user.name}\n"
        profile_message += f"Phone: {user.phone}\n"
        
        # Add resume information if available
        if user.has_resume:
            profile_message += f"Resume: ✅ Uploaded\n"
        else:
            profile_message += "Resume: ❌ Not uploaded\n"
        
        # Add connection request information
        if user.connection_requests and len(user.connection_requests) > 0:
            profile_message += f"\nYour profile has been shared with {len(user.connection_requests)} people who requested connections.\n"
        else:
            profile_message += "\nYour profile hasn't been shared with anyone yet.\n"
        
        profile_message += "\n\nTo update your information, use the `/update` command."
        
        await interaction.followup.send(profile_message, ephemeral=True)
    except Exception as e:
        print(f"Error in profile command: {e}")
        try:
            # Try to respond if we haven't already
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Error retrieving your profile: {str(e)}",
                    ephemeral=True
                )
            else:
                try:
                    await interaction.followup.send(
                        f"Error retrieving your profile: {str(e)}",
                        ephemeral=True
                    )
                except Exception as follow_up_error:
                    print(f"Error sending final error message: {follow_up_error}")
                    await send_dm_fallback(interaction.user, "Error retrieving your profile. Please try again later.")
        except Exception as response_error:
            print(f"Error sending error message: {response_error}")


async def start_bot():
    """Start the Discord bot."""
    await bot.start(DISCORD_TOKEN) 