# Telegram Channel User Inviter

This script adds users from a CSV file to a Telegram channel. It includes proper error handling, rate limiting, and logging.

## Features

- ✅ Adds users from CSV to Telegram channel
- ✅ Handles duplicate users automatically
- ✅ Batch processing with configurable delays
- ✅ Comprehensive error handling (privacy restrictions, rate limits, etc.)
- ✅ Detailed logging to CSV file
- ✅ Progress tracking and summary reports

## Prerequisites

1. Python 3.7 or higher
2. Telegram API credentials (API ID and API Hash)
3. Admin permissions on the target channel
4. A CSV file with user data

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. Copy your `api_id` and `api_hash`

### 3. Configure Environment Variables

1. Copy `.env.example` to `.env`:
   ```bash
   copy .env.example .env
   ```

2. Edit `.env` and fill in your credentials:
   ```
   TG_API_ID=your_api_id_here
   TG_API_HASH=your_api_hash_here
   TG_PHONE=+1234567890
   TG_TARGET_CHANNEL=@your_channel_name
   ```

### 4. Prepare Your CSV File

Your CSV file should have at least these columns:
- `user_id` - Telegram user ID (numeric)
- `username` - Telegram username (optional, without @)

Example CSV structure:
```csv
user_id,username,first_name,last_name
6205262721,Visionary30,Tewelde,ⓨ Ⓜ
5779220927,Bencamus,BEN G,
```

## Usage

### Basic Usage

```bash
python invite_users_to_channel.py
```

### Configuration Options

You can customize the script behavior via environment variables in `.env`:

- `TG_CSV` - Path to your CSV file (default: `telegram_users.csv`)
- `OUTPUT_FILE` - Path to results CSV (default: `invite_results.csv`)
- `BATCH_SIZE` - Number of users per batch (default: `10`)
- `BATCH_DELAY` - Seconds to wait between batches (default: `5`)

## How It Works

1. **Authentication**: The script authenticates with Telegram using your credentials
2. **CSV Reading**: Reads and deduplicates users from your CSV file
3. **Batch Processing**: Processes users in small batches to avoid rate limits
4. **Error Handling**: Handles various errors gracefully:
   - `UserPrivacyRestricted` - User's privacy settings prevent adding
   - `AlreadyParticipant` - User is already in the channel
   - `FloodWait` - Rate limited by Telegram (automatically waits)
   - `UserNotFound` - User ID/username not found
5. **Logging**: Saves all results to `invite_results.csv`

## Output

The script creates `invite_results.csv` with the following columns:
- `user_id` - User ID from CSV
- `username` - Username from CSV
- `first_name` - First name from CSV
- `last_name` - Last name from CSV
- `status` - Success or Failed
- `reason` - Reason for success/failure
- `timestamp` - When the invite was attempted

## Error Handling

### Common Errors and Solutions

| Error | Meaning | Solution |
|-------|---------|----------|
| `UserPrivacyRestricted` | User's privacy prevents adding | Message them the invite link manually |
| `FloodWait_Xs` | Rate limited by Telegram | Script automatically waits, but you may need to reduce batch size |
| `AlreadyParticipant` | User is already in channel | Safe to ignore |
| `UserNotFound` | Invalid user ID/username | Verify the CSV entry |
| `NotMutualContact` | User hasn't added you | They need to add you first or use invite link |

## Safety Features

- ✅ Processes users in small batches to avoid rate limits
- ✅ Automatic delays between batches
- ✅ Handles FloodWait errors automatically
- ✅ Skips duplicate users
- ✅ Comprehensive logging for audit trail

## Important Notes

⚠️ **Rate Limits**: Telegram has strict rate limits. If you encounter many `FloodWait` errors:
- Reduce `BATCH_SIZE` (try 5 instead of 10)
- Increase `BATCH_DELAY` (try 10-15 seconds)
- Process in smaller chunks over multiple sessions

⚠️ **Privacy Settings**: Users with restricted privacy settings cannot be added automatically. You'll need to send them an invite link manually.

⚠️ **Admin Permissions**: Make sure you have admin permissions with the ability to invite members to the channel.

⚠️ **Testing**: Always test with a small batch (5-10 users) first before processing large lists.

## Troubleshooting

### "TG_API_ID and TG_API_HASH must be set"
- Make sure you created a `.env` file
- Check that your `.env` file has the correct variable names

### "Error connecting to channel"
- Verify you have admin permissions
- Check that `TG_TARGET_CHANNEL` is correct (use @username or -100... ID format)
- Make sure you're already a member of the channel

### "User not found"
- Verify the user ID or username in your CSV is correct
- Some users may have deleted their accounts

### Session file issues
- If authentication fails, delete the `.session` file and try again
- Make sure you have 2FA disabled or provide the password when prompted

## License

This script is provided as-is for educational and legitimate use only. Always respect Telegram's Terms of Service and user privacy.

