# Discord Developer Portal Setup Guide

This guide will walk you through the process of setting up your Discord bot in the Discord Developer Portal.

## Step 1: Create a New Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click on the "New Application" button in the top right corner
3. Enter a name for your application (e.g., "Super Connector Bot")
4. Accept the terms of service and click "Create"

## Step 2: Set Up the Bot

1. In the left sidebar, click on "Bot"
2. Click the "Add Bot" button and confirm by clicking "Yes, do it!"
3. Under the "TOKEN" section, click "Reset Token" and copy the token (you'll need this for your `.env` file)
4. Under "Privileged Gateway Intents", enable:
   - Presence Intent
   - Server Members Intent
   - Message Content Intent
5. Click "Save Changes"

## Step 3: Configure OAuth2 Settings

1. In the left sidebar, click on "OAuth2"
2. Under "OAuth2 URL Generator", select the following scopes:
   - `bot`
   - `applications.commands`
3. Under "Bot Permissions", select:
   - View Channels
   - Send Messages
   - Attach Files
   - Read Message History
4. Copy the generated URL at the bottom of the page

## Step 4: Invite the Bot to Your Server

1. Paste the URL you copied in the previous step into your web browser
2. Select the server you want to add the bot to
3. Click "Authorize"
4. Complete the CAPTCHA if prompted

## Step 5: Configure Your Environment Variables

1. In your project's `.env` file, add the following variables:
   ```
   DISCORD_TOKEN=your_bot_token
   DISCORD_CLIENT_ID=your_application_id
   DISCORD_GUILD_ID=your_server_id
   ```

   - `your_bot_token` is the token you copied in Step 2
   - `your_application_id` can be found in the "General Information" tab of your application
   - `your_server_id` can be obtained by enabling Developer Mode in Discord (Settings > Advanced > Developer Mode), then right-clicking on your server and selecting "Copy ID"

## Step 6: Run Your Bot

1. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Start the FastAPI server:
   ```
   uvicorn app.main:app --reload
   ```

3. Your bot should now be online and ready to use!

## Testing the Bot

Once your bot is running, you can test it with the following commands in your Discord server:

1. Register yourself:
   ```
   /register name:Your Name phone:1234567890
   ```
   Then upload your resume when prompted.

2. Find a connection:
   ```
   /connect looking_for:software engineer
   ```

## Troubleshooting

- If your bot doesn't respond to commands, make sure you've enabled the correct intents in the Developer Portal.
- If slash commands don't work, make sure you've synced the commands by running the bot at least once.
- Check the console output for any error messages.
- Verify that your environment variables are set correctly. 