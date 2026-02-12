"""
Add Patients to Telegram Channel by Phone Number
Reads patient CSV (Name + Phone), imports contacts to Telegram, 
and adds them directly to the target channel.
"""

import asyncio
import os
import csv
import random
import sys
import re
from datetime import datetime
from typing import List, Dict, Set
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest
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
    UserNotParticipantError,
    SessionPasswordNeededError,
)

# Load environment variables
load_dotenv()

# Configuration from .env
API_ID = os.getenv('TG_API_ID')
API_HASH = os.getenv('TG_API_HASH')
PHONE = os.getenv('TG_PHONE')
SESSION_NAME = os.getenv('TG_SESSION_NAME', 'telegram_session')
TARGET_CHANNEL = os.getenv('TG_TARGET_CHANNEL')  # e.g. @SunDentalClinic_mekelle
CSV_FILE = os.getenv('TG_CSV', r'Patient History (Autosaved).csv')
OUTPUT_FILE = 'patient_invite_results.csv'

# Safety Settings
DAILY_LIMIT = 9999        # Max invites per day (Telegram will enforce server-side limit ~50)
BATCH_SIZE = 5            # Users per batch
MIN_DELAY = 15            # Min seconds between individual invites (lowered for faster adding)
MAX_DELAY = 45            # Max seconds between individual invites
BATCH_DELAY = 60          # Seconds to wait between batches

# Validate
if not API_ID or not API_HASH:
    print("Error: Please set TG_API_ID and TG_API_HASH in .env")
    sys.exit(1)

if not TARGET_CHANNEL:
    print("Error: Please set TG_TARGET_CHANNEL in .env")
    sys.exit(1)

# Initialize Client
client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)


def normalize_phone(phone: str) -> str:
    """Normalize Ethiopian phone numbers to international format (+251...)."""
    phone = phone.strip().replace(' ', '').replace('-', '')
    
    # Skip empty or too-short numbers
    if not phone or len(phone) < 8:
        return ''
    
    # Remove non-digit characters except leading +
    if phone.startswith('+'):
        digits = '+' + re.sub(r'[^\d]', '', phone[1:])
    else:
        digits = re.sub(r'[^\d]', '', phone)
    
    # Ethiopian numbers: convert 09xx to +2519xx
    if digits.startswith('09') and len(digits) == 10:
        return '+251' + digits[1:]
    
    # Already international format
    if digits.startswith('+251') and len(digits) == 13:
        return digits
    
    # Without + but starts with 251
    if digits.startswith('251') and len(digits) == 12:
        return '+' + digits
    
    # Some numbers may be malformed (too short/long) — skip them
    return ''


def read_patient_csv(file_path: str) -> List[Dict[str, str]]:
    """
    Read patient CSV. The file has:
      - Row 1: Clinic title row
      - Row 2: Sub-title row  
      - Row 3: Headers (Card No., Date of Treatment, Name, Age, Sex, Address, C-Phone)
      - Row 4+: Data
    """
    patients = []
    seen_phones: Set[str] = set()
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"CSV file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        # Skip the first 2 non-header rows
        next(f, None)  # Row 1: Clinic title
        next(f, None)  # Row 2: Sub-title
        
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('Name', '').strip()
            phone = row.get('C-Phone', '').strip()
            card_no = row.get('Card No.', '').strip()
            
            # Skip rows without phone numbers
            if not phone:
                continue
            
            # Normalize phone
            normalized = normalize_phone(phone)
            if not normalized:
                continue
            
            # Skip duplicate phone numbers
            if normalized in seen_phones:
                continue
            seen_phones.add(normalized)
            
            # Split name into first_name and last_name
            name_parts = name.split()
            first_name = name_parts[0] if name_parts else 'Patient'
            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
            
            patients.append({
                'card_no': card_no,
                'name': name,
                'first_name': first_name,
                'last_name': last_name,
                'phone': normalized,
            })
    
    print(f"✓ Loaded {len(patients)} patients with valid phone numbers")
    return patients


def get_processed_phones(output_file: str) -> Set[str]:
    """Load phone numbers that have already been processed."""
    processed = set()
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                phone = row.get('phone', '')
                if phone:
                    processed.add(phone)
    return processed


def write_result(result: dict):
    """Append a single result to the output CSV."""
    file_exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['card_no', 'name', 'phone', 'status', 'reason', 'timestamp']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(result)


async def resolve_phone_to_user(phone: str, first_name: str, last_name: str):
    """
    Import a phone number as a contact to resolve it to a Telegram user.
    Returns the user entity or None.
    """
    try:
        contact = InputPhoneContact(
            client_id=random.randint(0, 2**31 - 1),
            phone=phone,
            first_name=first_name,
            last_name=last_name
        )
        result = await client(ImportContactsRequest([contact]))
        
        if result.users:
            return result.users[0]
        else:
            return None
    except Exception as e:
        print(f"    Error importing contact: {e}")
        return None


async def main():
    print("=" * 60)
    print("  Add Patients to Telegram Channel by Phone Number")
    print("=" * 60)
    
    # Check for --dry-run flag
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("!!! DRY RUN MODE: No actual invites will be sent !!!\n")
    
    # 1. Authenticate
    await client.start(phone=PHONE)
    if not await client.is_user_authorized():
        print("Not authorized. Please run again and enter the code.")
        return
    
    me = await client.get_me()
    print(f"✓ Logged in as: {me.first_name} ({me.phone})\n")
    
    # 2. Read patients
    try:
        patients = read_patient_csv(CSV_FILE)
    except Exception as e:
        print(f"✗ Error reading CSV: {e}")
        return
    
    # 3. Filter already processed
    processed_phones = get_processed_phones(OUTPUT_FILE)
    remaining = [p for p in patients if p['phone'] not in processed_phones]
    
    print(f"Total patients with phone: {len(patients)}")
    print(f"Already processed: {len(processed_phones)}")
    print(f"Remaining to process: {len(remaining)}")
    
    if not remaining:
        print("\nNo new patients to process.")
        return
    
    # 4. Connect to channel
    try:
        print(f"\nConnecting to channel: {TARGET_CHANNEL}")
        channel = await client.get_entity(TARGET_CHANNEL)
        print(f"✓ Connected to: {channel.title}\n")
    except Exception as e:
        print(f"✗ Could not connect to channel: {e}")
        return
    
    # 5. Process patients
    success_count = 0
    fail_count = 0
    not_on_telegram = 0
    already_member = 0
    count = 0
    
    print(f"Starting... Daily limit: {DAILY_LIMIT}\n")
    
    for i, patient in enumerate(remaining):
        if count >= DAILY_LIMIT:
            print(f"\n⚠ Reached daily limit of {DAILY_LIMIT}. Run again tomorrow.")
            break
        
        name = patient['name']
        phone = patient['phone']
        card = patient['card_no']
        
        print(f"[{count+1}/{DAILY_LIMIT}] {name} ({phone}, Card: {card})")
        
        if dry_run:
            print(f"  ✓ [DRY RUN] Would import and add to channel")
            count += 1
            write_result({
                'card_no': card, 'name': name, 'phone': phone,
                'status': 'DryRun', 'reason': 'Simulated',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            await asyncio.sleep(0.5)
            continue
        
        status = "Failed"
        reason = "Unknown"
        
        try:
            # Step A: Import phone as contact to get Telegram user
            user = await resolve_phone_to_user(phone, patient['first_name'], patient['last_name'])
            
            if not user:
                status = "Failed"
                reason = "NotOnTelegram"
                not_on_telegram += 1
                print(f"  ✗ Phone not registered on Telegram")
            else:
                # Step B: Check if already in channel
                try:
                    await client(GetParticipantRequest(channel=channel, participant=user))
                    status = "Skipped"
                    reason = "AlreadyMember"
                    already_member += 1
                    print(f"  ⚠ Already a member")
                except UserNotParticipantError:
                    # Step C: Invite to channel
                    try:
                        await client(InviteToChannelRequest(channel, [user]))
                        status = "Success"
                        reason = "Added"
                        success_count += 1
                        count += 1
                        print(f"  ✓ Added to channel!")
                    except UserPrivacyRestrictedError:
                        status = "Failed"
                        reason = "PrivacyRestricted"
                        fail_count += 1
                        print(f"  ✗ User's privacy prevents adding")
                    except UserAlreadyParticipantError:
                        status = "Skipped"
                        reason = "AlreadyMember"
                        already_member += 1
                        print(f"  ⚠ Already a member")
                    except UserNotMutualContactError:
                        status = "Failed"
                        reason = "NotMutualContact"
                        fail_count += 1
                        print(f"  ✗ Not mutual contact")
                    except UserChannelsTooMuchError:
                        status = "Failed"
                        reason = "TooManyChannels"
                        fail_count += 1
                        print(f"  ✗ User in too many channels")
                    except UserKickedError:
                        status = "Failed"
                        reason = "PreviouslyKicked"
                        fail_count += 1
                        print(f"  ✗ User was previously kicked")
                    except InputUserDeactivatedError:
                        status = "Failed"
                        reason = "Deactivated"
                        fail_count += 1
                        print(f"  ✗ Account deactivated")
                except Exception as e:
                    # Participant check failed, try to invite anyway
                    try:
                        await client(InviteToChannelRequest(channel, [user]))
                        status = "Success"
                        reason = "Added"
                        success_count += 1
                        count += 1
                        print(f"  ✓ Added to channel!")
                    except UserAlreadyParticipantError:
                        status = "Skipped"
                        reason = "AlreadyMember"
                        already_member += 1
                        print(f"  ⚠ Already a member")
                    except Exception as invite_err:
                        status = "Failed"
                        reason = str(invite_err)[:50]
                        fail_count += 1
                        print(f"  ✗ {reason}")
        
        except PeerFloodError:
            print(f"\n!!!! PEER FLOOD — Telegram rate limit hit. STOP for today.")
            write_result({
                'card_no': card, 'name': name, 'phone': phone,
                'status': 'Failed', 'reason': 'PeerFlood',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            break
        
        except FloodWaitError as e:
            wait = e.seconds
            print(f"\n⚠ FloodWait: must wait {wait} seconds")
            if wait > 600:
                print("Wait too long, stopping for today.")
                write_result({
                    'card_no': card, 'name': name, 'phone': phone,
                    'status': 'Failed', 'reason': f'FloodWait_{wait}s',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                break
            print(f"  Waiting {wait} seconds...")
            await asyncio.sleep(wait)
            continue
        
        except Exception as e:
            status = "Failed"
            reason = str(e)[:50]
            fail_count += 1
            print(f"  ✗ Unexpected: {reason}")
        
        # Log result
        write_result({
            'card_no': card, 'name': name, 'phone': phone,
            'status': status, 'reason': reason,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # Random delay between invites (look human)
        if count < DAILY_LIMIT and i < len(remaining) - 1:
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            print(f"  ⏳ Waiting {delay}s...\n")
            await asyncio.sleep(delay)
            
        # Cleanup: Remove from contacts to keep list clean
        if user:
            try:
                await client(DeleteContactsRequest(id=[user.id]))
            except Exception:
                pass
    
    # Summary
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Successfully added: {success_count}")
    print(f"  Already members:    {already_member}")
    print(f"  Not on Telegram:    {not_on_telegram}")
    print(f"  Failed:             {fail_count}")
    print(f"  Results saved to:   {OUTPUT_FILE}")
    print(f"{'=' * 60}")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
