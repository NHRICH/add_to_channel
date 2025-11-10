"""
Telegram Channel User Inviter
Adds users from CSV file to a Telegram channel with proper error handling and logging.
"""

import asyncio
import os
import csv
from datetime import datetime
from typing import List, Dict, Optional, Set
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest
from telethon.errors import (
    UserPrivacyRestrictedError,
    FloodWaitError,
    UserNotMutualContactError,
    UserChannelsTooMuchError,
    UserKickedError,
    InputUserDeactivatedError,
    PeerFloodError,
    UserAlreadyParticipantError,
    UsernameNotOccupiedError,
    SessionPasswordNeededError,
    UserNotParticipantError
)

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = os.getenv('TG_API_ID')
API_HASH = os.getenv('TG_API_HASH')
PHONE = os.getenv('TG_PHONE')
SESSION_NAME = os.getenv('TG_SESSION_NAME', 'telegram_session')
TARGET_CHANNEL = os.getenv('TG_TARGET_CHANNEL')  # Channel username or ID (e.g., @channelname or -1001234567890)
CSV_FILE = os.getenv('TG_CSV', 'telegram_users.csv')
OUTPUT_FILE = os.getenv('OUTPUT_FILE', 'invite_results.csv')
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '10'))  # Number of users to add per batch
BATCH_DELAY = int(os.getenv('BATCH_DELAY', '5'))  # Seconds to wait between batches

# Validate required credentials
if not API_ID or not API_HASH:
    raise ValueError("TG_API_ID and TG_API_HASH must be set in .env file")

if not TARGET_CHANNEL:
    raise ValueError("TG_TARGET_CHANNEL must be set in .env file")

if not API_ID.isdigit():
    raise ValueError("TG_API_ID must be a numeric string")

# Initialize Telegram client
client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)


async def authenticate():
    """Authenticate with Telegram API."""
    await client.start()
    
    if not await client.is_user_authorized():
        if PHONE:
            await client.send_code_request(PHONE)
            try:
                code = input('Enter the code you received: ')
                await client.sign_in(PHONE, code)
            except SessionPasswordNeededError:
                password = input('Enter your 2FA password: ')
                await client.sign_in(password=password)
        else:
            print("Please set TG_PHONE in .env file")
            return False
    
    print("✓ Authenticated successfully")
    return True


def read_users_from_csv(file_path: str) -> List[Dict[str, str]]:
    """Read users from CSV file and return unique users."""
    users = []
    seen_user_ids: Set[str] = set()
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"CSV file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = row.get('user_id', '').strip()
            username = row.get('username', '').strip()
            
            # Skip empty rows
            if not user_id and not username:
                continue
            
            # Skip duplicates based on user_id
            if user_id and user_id in seen_user_ids:
                continue
            
            if user_id:
                seen_user_ids.add(user_id)
            
            users.append({
                'user_id': user_id,
                'username': username,
                'first_name': row.get('first_name', ''),
                'last_name': row.get('last_name', '')
            })
    
    print(f"✓ Loaded {len(users)} unique users from CSV")
    return users


async def get_user_entity(user_id: Optional[str], username: Optional[str]):
    """Get user entity by ID or username. Tries username first, then ID."""
    from telethon.tl.types import InputUser
    from telethon.errors import UserPrivacyRestrictedError
    
    # Try username first (more reliable if available)
    if username:
        try:
            username_clean = username.lstrip('@').strip()
            if username_clean:  # Make sure username is not empty
                return await client.get_entity(username_clean)
        except UsernameNotOccupiedError:
            pass  # Username doesn't exist, try user ID
        except UserPrivacyRestrictedError:
            # User exists but privacy prevents lookup - we can still try to invite by ID
            pass
        except (ValueError, TypeError):
            pass  # Invalid format, try user ID
        except Exception:
            pass  # Other error, try user ID
    
    # Try user ID if username failed or not available
    if user_id:
        try:
            user_id_int = int(user_id)
            # Try direct entity lookup
            try:
                return await client.get_entity(user_id_int)
            except (ValueError, TypeError, UserPrivacyRestrictedError):
                # If entity lookup fails, try to create InputUser directly
                # This might work if we have the user ID even without access_hash
                # Note: This may not work for all cases, but worth trying
                try:
                    # Try to resolve user by making a request that might give us access_hash
                    # If that fails, we'll return None and handle it in the invite function
                    return await client.get_entity(user_id_int)
                except:
                    # Last resort: return the user ID as a string for potential direct invite
                    # But actually, we need a proper entity, so return None
                    return None
        except (ValueError, TypeError):
            return None  # Invalid user ID format
        except Exception:
            return None  # Other error
    
    return None


async def add_user_to_channel(channel, user_entity) -> tuple[bool, str]:
    """Add a user to the channel and return (success, reason)."""
    try:
        await client(InviteToChannelRequest(channel, [user_entity]))
        return True, "Success"
    except UserPrivacyRestrictedError:
        return False, "UserPrivacyRestricted"
    except UserAlreadyParticipantError:
        return False, "AlreadyParticipant"
    except UserNotMutualContactError:
        return False, "NotMutualContact"
    except UserChannelsTooMuchError:
        return False, "ChannelsTooMuch"
    except UserKickedError:
        return False, "UserKicked"
    except InputUserDeactivatedError:
        return False, "UserDeactivated"
    except PeerFloodError:
        return False, "PeerFlood"
    except FloodWaitError as e:
        wait_time = e.seconds
        return False, f"FloodWait_{wait_time}s"
    except Exception as e:
        return False, f"Error: {str(e)[:50]}"


async def is_user_in_channel(channel, user_entity) -> bool:
    """Check if the user is already a member of the channel."""
    try:
        await client(GetParticipantRequest(channel=channel, participant=user_entity))
        return True
    except UserNotParticipantError:
        return False
    except (ValueError, TypeError):
        return False
    except Exception:
        return False


def write_result_to_csv(results: List[Dict], output_file: str):
    """Write invite results to CSV file."""
    if not results:
        return
    
    file_exists = os.path.exists(output_file)
    
    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['user_id', 'username', 'first_name', 'last_name', 'status', 'reason', 'timestamp']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerows(results)


async def invite_users_to_channel():
    """Main function to invite users from CSV to channel."""
    # Authenticate
    if not await authenticate():
        return
    
    # Read users from CSV
    try:
        users = read_users_from_csv(CSV_FILE)
    except Exception as e:
        print(f"✗ Error reading CSV: {e}")
        return
    
    if not users:
        print("✗ No users found in CSV file")
        return
    
    # Get channel entity
    try:
        print(f"\nConnecting to channel: {TARGET_CHANNEL}")
        channel = await client.get_entity(TARGET_CHANNEL)
        print(f"✓ Connected to channel: {channel.title}")
    except Exception as e:
        print(f"✗ Error connecting to channel: {e}")
        print("Make sure you have admin permissions and the channel identifier is correct")
        return
    
    # Process users in batches
    total_users = len(users)
    results = []
    success_count = 0
    failure_count = 0
    skipped_count = 0
    
    print(f"\nStarting to invite {total_users} users in batches of {BATCH_SIZE}...")
    print(f"Delay between batches: {BATCH_DELAY} seconds\n")
    
    for i in range(0, total_users, BATCH_SIZE):
        batch = users[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total_users + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} users)...")
        
        for user in batch:
            user_id = user['user_id']
            username = user['username']
            display_name = f"{user['first_name']} {user['last_name']}".strip() or username or user_id
            
            print(f"  Adding: {display_name} (ID: {user_id}, Username: {username or 'N/A'})", end=" ... ")
            
            # Get user entity
            user_entity = await get_user_entity(user_id, username)
            
            if not user_entity:
                status = "Failed"
                reason = "UserNotFound"
                print(f"✗ User not found (may have privacy restrictions or account deleted)")
                failure_count += 1
            else:
                if await is_user_in_channel(channel, user_entity):
                    status = "Skipped"
                    reason = "AlreadyMember"
                    print(f"⚠ Already in channel, skipping")
                    skipped_count += 1
                else:
                    # Add user to channel
                    success, reason = await add_user_to_channel(channel, user_entity)
                    
                    if success:
                        status = "Success"
                        print(f"✓ Added successfully")
                        success_count += 1
                    else:
                        status = "Failed"
                        print(f"✗ {reason}")
                        failure_count += 1
                        
                        # Handle FloodWait
                        if reason.startswith("FloodWait_"):
                            wait_seconds = int(reason.split("_")[1].rstrip("s"))
                            print(f"  ⚠ Rate limited! Waiting {wait_seconds} seconds...")
                            await asyncio.sleep(wait_seconds)
            
            # Record result
            results.append({
                'user_id': user_id,
                'username': username or '',
                'first_name': user['first_name'],
                'last_name': user['last_name'],
                'status': status,
                'reason': reason,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            # Small delay between individual invites
            await asyncio.sleep(1)
        
        # Write results after each batch
        write_result_to_csv(results, OUTPUT_FILE)
        results = []  # Clear results to avoid duplicates
        
        # Wait between batches (except for the last batch)
        if i + BATCH_SIZE < total_users:
            print(f"\nWaiting {BATCH_DELAY} seconds before next batch...\n")
            await asyncio.sleep(BATCH_DELAY)
    
    # Final summary
    print(f"\n{'='*60}")
    print(f"Invitation Summary:")
    print(f"  Total users processed: {total_users}")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {failure_count}")
    print(f"  Skipped (already member): {skipped_count}")
    print(f"  Results saved to: {OUTPUT_FILE}")
    print(f"{'='*60}\n")
    
    # Show failure breakdown
    if failure_count > 0:
        print("Failure reasons (check invite_results.csv for details):")
        print("  - UserPrivacyRestricted: User's privacy settings prevent adding")
        print("  - AlreadyParticipant: User is already in the channel")
        print("  - UserNotFound: User ID/username not found (privacy restrictions or deleted account)")
        print("  - FloodWait: Rate limited by Telegram (wait and retry)")
        print("  - Other errors: Check the reason column in CSV")
        print("\n💡 TIP: For users that can't be found, you can:")
        print("   1. Send them the channel invite link manually")
        print("   2. Ask them to join using the channel username")
        print("   3. Check if the user IDs are correct and accounts still exist\n")


async def main():
    """Main entry point."""
    try:
        await invite_users_to_channel()
    except KeyboardInterrupt:
        print("\n\n⚠ Process interrupted by user")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        print("✓ Disconnected from Telegram")


if __name__ == "__main__":
    asyncio.run(main())

