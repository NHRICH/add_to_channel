"""
Safe Telegram DM Inviter
Sends direct messages to users from CSV with randomized delays and daily limits to prevent bans.
"""

import asyncio
import os
import csv
import random
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Optional, Set
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    UserPrivacyRestrictedError,
    FloodWaitError,
    UserNotMutualContactError,
    UserKickedError,
    InputUserDeactivatedError,
    PeerFloodError,
    UserIsBlockedError,
)

# Load environment variables
load_dotenv()

# Configuration
API_ID = os.getenv('TG_API_ID')
API_HASH = os.getenv('TG_API_HASH')
PHONE = os.getenv('TG_PHONE')
SESSION_NAME = os.getenv('TG_SESSION_NAME', 'telegram_session')
TARGET_CHANNEL_LINK = os.getenv('TG_TARGET_CHANNEL_LINK') # Full link e.g., https://t.me/yourchannel
CSV_FILE = os.getenv('TG_CSV', 'telegram_users.csv')
OUTPUT_FILE = 'dm_invite_results.csv'
MESSAGES_FILE = 'messages.txt'

# Safety Settings
DAILY_LIMIT = 35         # Max DMs per day
MIN_DELAY = 60           # Minimum seconds between messages
MAX_DELAY = 300          # Maximum seconds between messages

# Validate
if not API_ID or not API_HASH:
    print("Error: Please set TG_API_ID and TG_API_HASH in .env")
    sys.exit(1)

# Initialize Client
client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)

def load_messages():
    """Load messages from file or return default."""
    if os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
            msgs = [line.strip() for line in f if line.strip()]
        if msgs:
            return msgs
    return ["Hello! Join our channel here: {link}"]

def get_processed_users(output_file):
    """Load IDs of users who have already been processed (Success or specific failures)."""
    processed = set()
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # We skip anyone we've already tried, regardless of result, 
                # to avoid harassing them or retrying failed cases repeatedly daily.
                if row.get('user_id'):
                    processed.add(row['user_id'])
    return processed

def write_result(result):
    """Append a single result to CSV."""
    file_exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['user_id', 'username', 'first_name', 'status', 'reason', 'timestamp']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(result)

async def main():
    parser = argparse.ArgumentParser(description='Safe Telegram DM Inviter')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without sending messages')
    args = parser.parse_args()

    print("--- Safe Telegram DM Inviter ---")
    if args.dry_run:
        print("!!! DRY RUN MODE: No messages will be sent !!!")
    
    # 1. Authenticate
    await client.start()
    if not await client.is_user_authorized():
        print("Not authorized. Run the main invite script first to log in or handle login here.")
        return

    # 2. Preparation
    messages = load_messages()
    processed_ids = get_processed_users(OUTPUT_FILE)
    
    # Read Users
    users_to_contact = []
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row.get('user_id')
                if uid and uid not in processed_ids:
                    users_to_contact.append(row)
    except FileNotFoundError:
        print(f"Error: Could not find {CSV_FILE}")
        return

    print(f"Total users in CSV: {len(processed_ids) + len(users_to_contact)}")
    print(f"Already processed: {len(processed_ids)}")
    print(f"Candidates for today: {len(users_to_contact)}")
    
    if not users_to_contact:
        print("No new users to contact.")
        return

    # 3. Main Loop
    count = 0
    print(f"\nStarting... Limit is {DAILY_LIMIT} messages today.")
    
    for user in users_to_contact:
        if count >= DAILY_LIMIT:
            print(f"\nreached daily limit of {DAILY_LIMIT}. Stopping for today.")
            break

        user_id = user.get('user_id')
        username = user.get('username')
        first_name = user.get('first_name', 'Friend')
        
        # Select random message
        msg_template = random.choice(messages)
        message_text = msg_template.replace("{link}", TARGET_CHANNEL_LINK or "[LINK]").replace("{first_name}", first_name)
        
        display_name = f"{first_name} ({username})" if username else f"{first_name} ({user_id})"
        print(f"[{count+1}/{DAILY_LIMIT}] Messaging {display_name}...", end=" ", flush=True)

        status = "Failed"
        reason = "Unknown"

        if args.dry_run:
            print(f"✓ [Functionality Check] Would send: {message_text[:30]}...")
            status = "DryRun"
            reason = "Simulated"
            count += 1
            # Sleep less for dry run
            await asyncio.sleep(1)
            continue

        try:
            # Resolve entity
            entity = None
            if username:
                try:
                    entity = await client.get_entity(username)
                except:
                    pass
            
            if not entity and user_id:
                try:
                    entity = await client.get_entity(int(user_id))
                except:
                    pass

            if entity:
                await client.send_message(entity, message_text)
                status = "Success"
                reason = "Sent"
                print("✓ Sent")
                count += 1
            else:
                reason = "UserNotFound"
                print("✗ User not found")

        except PeerFloodError:
            print("\n!!! FLOOD LIMIT REACHED. Stopping immediately.")
            write_result({
                'user_id': user_id, 'username': username, 'first_name': first_name,
                'status': 'Failed', 'reason': 'PeerFlood', 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            break
        except UserPrivacyRestrictedError:
            print("✗ Privacy Restricted")
            reason = "PrivacyRestricted"
        except UserIsBlockedError:
            print("✗ User Blocked Bot")
            reason = "Blocked"
        except FloodWaitError as e:
            print(f"\n!!! FloodWait: {e.seconds} seconds. Stopping for safety.")
            break
        except Exception as e:
            print(f"✗ Error: {e}")
            reason = str(e)[:50]

        # Log result
        write_result({
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'status': status,
            'reason': reason,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

        # Wait if successful or even if failed (to look human)
        # Only wait if we are not at the limit and not stopping
        if count < DAILY_LIMIT:
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            print(f"   Sleeping {delay}s...")
            await asyncio.sleep(delay)

    print("\nDone.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
