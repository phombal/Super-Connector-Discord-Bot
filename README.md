# Discord Super Connector Bot

A Discord bot that serves as a super connector, allowing users to register their information and get connected with relevant people based on their needs.

## Features

- Users can register their name, phone number, and upload their resume
- Users can request to be connected with specific types of people
- Bot uses Mistral AI's API to intelligently match users based on resume content
- Data is stored securely in Supabase

## Setup

### Prerequisites

- Python 3.8+
- Discord Developer Account
- Supabase Account
- Mistral AI API Key

### Installation

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the root directory with the following variables:
   ```
   DISCORD_TOKEN=your_discord_bot_token
   DISCORD_CLIENT_ID=your_discord_client_id
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_key
   MISTRAL_API_KEY=your_mistral_api_key
   ```

### Discord Developer Portal Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Navigate to the "Bot" tab and create a bot
4. Enable the following Privileged Gateway Intents:
   - Server Members Intent
   - Message Content Intent
5. Under the "OAuth2" tab, select the following scopes:
   - bot
   - applications.commands
6. Select the following bot permissions:
   - Read Messages/View Channels
   - Send Messages
   - Attach Files
   - Read Message History
7. Use the generated URL to invite the bot to your server

### Running the Bot

```
uvicorn app.main:app --reload
```

## Testing

Run tests using pytest:

```
pytest
```

## Usage

### User Registration
Use the `/register` command to register your information:
```
/register name:John Doe phone:1234567890
```
Then attach your resume when prompted.

### Finding Connections
Use the `/connect` command to find relevant connections:
```
/connect looking_for:software engineer
```

### Updating Information
Use the `/update` command to update your information:
```
/update name:New Name phone:9876543210
```

### Getting Help
Use the `/help` command to see all available commands and how to use them.

## License

MIT 