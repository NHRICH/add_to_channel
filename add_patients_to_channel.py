"""
Telegram Channel Patient Inviter
Adds patients from CSV file (with phone numbers) to a Telegram channel.
Uses phone number lookup via ImportContactsRequest to find Telegram users.
"""

import asyncio
import os
import csv
import random
import re
from datetime import datetime
from typing import List, Dict, Set
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact
from telethon.errors import (
    UserPrivacyRestrictedError,
    FloodWaitError,
    UserNotMutualContactError,
    UserChannelsTooMuchError,
    UserKickedError,
    InputUserDeactivatedError,
    PeerFloodError,
    UserAlreadyParticipantError,
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
TARGET_CHANNEL = os.getenv('TG_TARGET_CHANNEL')
CSV_FILE = os.getenv('TG_CSV', 'Patient History (Autosaved).csv')
OUTPUT_FILE = os.getenv('OUTPUT_FILE', 'patient_invite_results.csv')
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '5'))       # Smaller batches for phone-based invites
BATCH_DELAY = int(os.getenv('BATCH_DELAY', '30'))     # Longer delay between batches to avoid flood
INVITE_DELAY_MIN = int(os.getenv('INVITE_DELAY_MIN', '3'))   # Min seconds between individual invites
INVITE_DELAY_MAX = int(os.getenv('INVITE_DELAY_MAX', '8'))   # Max seconds between individual invites

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


def normalize_phone(phone: str) -> str:
    """Normalize phone number to international format.
    
    Ethiopian numbers: 09XXXXXXXX -> +2519XXXXXXXX
    Already international: +251... -> +251...
    """
    phone = phone.strip().replace(' ', '').replace('-', '')
    
    if not phone:
        return ''
    
    # Already has country code
    if phone.startswith('+'):
        return phone
    
    # Ethiopian format: 09XXXXXXXX -> +2519XXXXXXXX
    if phone.startswith('0') and len(phone) == 10:
        return '+251' + phone[1:]
    
    # Short/malformed numbers - try adding +251 prefix
    if phone.startswith('9') and len(phone) == 9:
        return '+251' + phone
    
    # Return as-is with + prefix if nothing matches
    return '+' + phone


def read_patients_from_csv(file_path: str) -> List[Dict[str, str]]:
    """Read patients from CSV file, deduplicate by phone number."""
    patients = []
    seen_phones: Set[str] = set()
    skipped_no_phone = 0
    skipped_duplicate = 0

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        
        # Skip header rows (first 3 lines: clinic name, subtitle, column headers)
        header_lines = []
        for i, row in enumerate(reader):
            header_lines.append(row)
            if i >= 2:  # Read 3 rows (indices 0, 1, 2)
                break
        
        # The actual column headers are in row 3 (index 2)
        # Columns: Card No., Date of Treatment, Name, Age, Sex, Address, C-Phone
        
        for row in reader:
            if len(row) < 7:
                continue
            
            card_no = row[0].strip()
            name = row[2].strip()
            phone_raw = row[6].strip() if len(row) > 6 else ''
            
            # Skip if no name
            if not name:
                continue
            
            # Skip if no phone number
            if not phone_raw:
                skipped_no_phone += 1
                continue
            
            phone = normalize_phone(phone_raw)
            
            # Skip invalid/too-short numbers
            if len(phone) < 8:
                skipped_no_phone += 1
                continue
            
            # Skip duplicates
            if phone in seen_phones:
                skipped_duplicate += 1
                continue
            
            seen_phones.add(phone)
            
            patients.append({
                'card_no': card_no,
                'name': name,
                'phone': phone,
                'phone_raw': phone_raw,
            })

    print(f"✓ Loaded {len(patients)} unique patients with phone numbers")
    print(f"  Skipped {skipped_no_phone} entries with no/invalid phone")
    print(f"  Skipped {skipped_duplicate} duplicate phone numbers")
    return patients


async def resolve_phone_to_user(phone: str, name: str):
    """
    Use ImportContactsRequest to resolve a phone number to a Telegram user.
    Returns the user entity if found, None otherwise.
    """
    try:
        # Import the contact temporarily
        contact = InputPhoneContact(
            client_id=random.randrange(-2**63, 2**63),
            phone=phone,
            first_name=name,
            last_name=''
        )
        
        result = await client(ImportContactsRequest([contact]))

        if result.users:
            user = result.users[0]
            
            # Clean up: delete the imported contact to keep contact list clean
            try:
                await client(DeleteContactsRequest(id=[user]))
            except Exception:
                pass  # Non-critical, continue
            
            return user
        
        return None
        
    except FloodWaitError as e:
        raise  # Re-raise so caller can handle
    except Exception as e:
        print(f"    ⚠ Error resolving phone {phone}: {str(e)[:60]}")
        return None


async def add_user_to_channel(channel, user_entity) -> tuple:
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
        return False, f"Error: {str(e)[:80]}"


async def is_user_in_channel(channel, user_entity) -> bool:
    """Check if the user is already a member of the channel."""
    try:
        await client(GetParticipantRequest(channel=channel, participant=user_entity))
        return True
    except UserNotParticipantError:
        return False
    except Exception:
        return False


def write_result_to_csv(results: List[Dict], output_file: str):
    """Write invite results to CSV file."""
    if not results:
        return

    file_exists = os.path.exists(output_file)

    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['card_no', 'name', 'phone', 'status', 'reason', 'timestamp']
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerows(results)


async def invite_patients_to_channel():
    """Main function to invite patients by phone number to channel."""
    # Authenticate
    if not await authenticate():
        return

    # Read patients from CSV
    try:
        patients = read_patients_from_csv(CSV_FILE)
    except Exception as e:
        print(f"✗ Error reading CSV: {e}")
        return

    if not patients:
        print("✗ No patients with phone numbers found in CSV file")
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

    # Process patients in batches
    total_patients = len(patients)
    results = []
    success_count = 0
    failure_count = 0
    skipped_count = 0
    not_on_telegram = 0

    print(f"\nStarting to invite {total_patients} patients in batches of {BATCH_SIZE}...")
    print(f"Delay between batches: {BATCH_DELAY} seconds")
    print(f"Delay between invites: {INVITE_DELAY_MIN}-{INVITE_DELAY_MAX} seconds\n")

    for i in range(0, total_patients, BATCH_SIZE):
        batch = patients[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total_patients + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} patients)...")

        for patient in batch:
            name = patient['name']
            phone = patient['phone']
            card_no = patient['card_no']

            print(f"  [{card_no}] {name} ({phone})", end=" ... ")

            # Step 1: Resolve phone number to Telegram user
            try:
                user_entity = await resolve_phone_to_user(phone, name)
            except FloodWaitError as e:
                wait_time = e.seconds
                print(f"\n  ⚠ FLOOD WAIT during phone lookup! Waiting {wait_time} seconds...")
                await asyncio.sleep(wait_time + 5)
                # Retry once after flood wait
                try:
                    user_entity = await resolve_phone_to_user(phone, name)
                except Exception:
                    user_entity = None

            if not user_entity:
                status = "Failed"
                reason = "NotOnTelegram"
                print(f"✗ Not found on Telegram")
                not_on_telegram += 1
            else:
                # Step 2: Check if already in channel
                if await is_user_in_channel(channel, user_entity):
                    status = "Skipped"
                    reason = "AlreadyMember"
                    print(f"⚠ Already in channel")
                    skipped_count += 1
                else:
                    # Step 3: Add user to channel
                    success, reason = await add_user_to_channel(channel, user_entity)

                    if success:
                        status = "Success"
                        print(f"✓ Added!")
                        success_count += 1
                    else:
                        status = "Failed"
                        print(f"✗ {reason}")
                        failure_count += 1

                        # Handle FloodWait
                        if reason.startswith("FloodWait_"):
                            wait_seconds = int(reason.split("_")[1].rstrip("s"))
                            print(f"  ⚠ Rate limited! Waiting {wait_seconds} seconds...")
                            await asyncio.sleep(wait_seconds + 5)
                        
                        # Handle PeerFlood - stop entirely
                        if reason == "PeerFlood":
                            print("\n  🛑 PEER FLOOD detected! Telegram is blocking invites.")
                            print("  Saving progress and stopping. Try again tomorrow.")
                            results.append({
                                'card_no': card_no,
                                'name': name,
                                'phone': phone,
                                'status': status,
                                'reason': reason,
                                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            })
                            write_result_to_csv(results, OUTPUT_FILE)
                            return

            # Record result
            results.append({
                'card_no': card_no,
                'name': name,
                'phone': phone,
                'status': status,
                'reason': reason,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })

            # Random delay between individual invites (mimics human behavior)
            delay = random.uniform(INVITE_DELAY_MIN, INVITE_DELAY_MAX)
            await asyncio.sleep(delay)

        # Write results after each batch
        write_result_to_csv(results, OUTPUT_FILE)
        results = []

        # Wait between batches (except for the last batch)
        if i + BATCH_SIZE < total_patients:
            print(f"\n  Waiting {BATCH_DELAY} seconds before next batch...\n")
            await asyncio.sleep(BATCH_DELAY)

    # Final summary
    print(f"\n{'='*60}")
    print(f"Invitation Summary:")
    print(f"  Total patients processed:  {total_patients}")
    print(f"  Successful invites:        {success_count}")
    print(f"  Failed invites:            {failure_count}")
    print(f"  Skipped (already member):  {skipped_count}")
    print(f"  Not on Telegram:           {not_on_telegram}")
    print(f"  Results saved to:          {OUTPUT_FILE}")
    print(f"{'='*60}\n")

    if not_on_telegram > 0:
        print(f"💡 {not_on_telegram} patients were not found on Telegram.")
        print("   These users either:")
        print("   - Don't have a Telegram account")
        print("   - Registered with a different phone number")
        print("   - Have strict privacy settings\n")


async def main():
    """Main entry point."""
    try:
        await invite_patients_to_channel()
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
