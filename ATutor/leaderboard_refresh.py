# cron_leaderboard_rotate.py

import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict
from datetime import datetime, timedelta
import random
import os

firebase_project_id = os.getenv('project_id')
firebase_client_email = os.getenv('client_email')
firebase_private_key = os.getenv('private_key').replace('\\n', '\n')
cred = credentials.Certificate({
    "type": "service_account",
    "project_id": firebase_project_id,
    "private_key_id": "<your-private-key-id>",
    "private_key": firebase_private_key,
    "client_email": firebase_client_email,
    "client_id": "<your-client-id>",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "<your-client-cert-url>"
})
firebase_admin.initialize_app(cred)
db = firestore.client()

TIERS = [
    {"id": 0, "name": "Broccoli"},
    {"id": 1, "name": "Cabbage"}, 
    {"id": 2, "name": "Banana"},
    {"id": 3, "name": "Strawberry"},
    {"id": 4, "name": "Apple"}
]

GROUP_SIZE = 20

def get_promotion_demotion_counts(tier_id):
    """Calculate promotion and demotion counts based on tier"""
    if tier_id == 0:  # Copper
        promote_count = 10
        demote_count = 0  # No demotion from copper
    elif tier_id == 4:  # Legendary
        promote_count = 0  # No promotion from legendary
        demote_count = 10  # All except top 3 stay in legendary
    else:
        promote_count = 10 - tier_id - 1  # Decreases by 1 per tier
        demote_count = 3 + (tier_id - 1) + 1  # Increases by 1 per tier (starting from 3)
    
    return promote_count, demote_count

def get_all_users_grouped():
    """Get all users grouped by tier and sorted by login activity"""
    all_users = db.collection('users').get()
    
    # Group users by tier
    tier_users = defaultdict(list)
    
    for user_doc in all_users:
        user_data = user_doc.to_dict()
        tier_id = user_data['tierID']
        
        # Convert lastLoginDate to datetime for sorting
        last_login = user_data.get('lastLoginDate', datetime.min)
        if isinstance(last_login, str):
            last_login = datetime.fromisoformat(last_login)
        
        user_data['lastLoginDateTime'] = last_login
        tier_users[tier_id].append(user_data)
    
    return tier_users

def shuffle_users_by_activity(users, group_size=GROUP_SIZE):
    """Shuffle users into groups while keeping recently active users together"""
    now = datetime.now()
    recent_threshold = now - timedelta(days=7)  # Consider users active in last 7 days
    
    # Separate recently active and inactive users
    recent_users = [u for u in users if u['lastLoginDateTime'] >= recent_threshold]
    inactive_users = [u for u in users if u['lastLoginDateTime'] < recent_threshold]
    
    # Sort each group by totalXP (descending) then by last login (recent first)
    recent_users.sort(key=lambda u: (-u['totalXP'], -u['lastLoginDateTime'].timestamp()))
    inactive_users.sort(key=lambda u: (-u['totalXP'], -u['lastLoginDateTime'].timestamp()))
    
    # Create mixed groups: fill each group with recent users first, then inactive users
    groups = []
    recent_idx = 0
    inactive_idx = 0
    
    while recent_idx < len(recent_users) or inactive_idx < len(inactive_users):
        group = []
        
        # Fill group with recent users first (up to 70% of group size)
        recent_slots = min(int(group_size * 0.7), len(recent_users) - recent_idx)
        for _ in range(recent_slots):
            if recent_idx < len(recent_users):
                group.append(recent_users[recent_idx])
                recent_idx += 1
        
        # Fill remaining slots with inactive users
        remaining_slots = group_size - len(group)
        for _ in range(remaining_slots):
            if inactive_idx < len(inactive_users):
                group.append(inactive_users[inactive_idx])
                inactive_idx += 1
        
        if group:  # Only add non-empty groups
            groups.append(group)
    
    return groups

def batch_update_users(updates):
    """Batch update users to avoid Firebase limits"""
    if not updates:
        return
        
    batch = db.batch()
    batch_count = 0
    
    for update in updates:
        user_ref = db.collection('users').document(update['user_id'])
        batch.update(user_ref, {
            'tierID': update['tier_id'],
            'groupID': update['group_id']
        })
        batch_count += 1
        
        # Firebase batch limit is 500 operations
        if batch_count >= 500:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    
    # Commit remaining updates
    if batch_count > 0:
        batch.commit()

def find_available_group_in_tier(tier_id, existing_groups):
    """Find next available group ID in a tier"""
    existing_group_ids = set(existing_groups.keys()) if existing_groups else set()
    group_id = 0
    while group_id in existing_group_ids:
        group_id += 1
    return group_id

def rotate_tiers():
    """Main function to promote, demote users and reshuffle groups"""
    print("Starting tier rotation with shuffling...")
    
    tier_users = get_all_users_grouped()
    all_updates = []
    
    # Process each tier
    for tier_id in range(len(TIERS)):
        tier_name = TIERS[tier_id]['name']
        users = tier_users.get(tier_id, [])
        
        if not users:
            print(f"No users in {tier_name} tier")
            continue
            
        print(f"Processing {tier_name} tier with {len(users)} users")
        
        # Shuffle users into new groups based on activity
        new_groups = shuffle_users_by_activity(users, GROUP_SIZE)
        
        promote_count, demote_count = get_promotion_demotion_counts(tier_id)
        
        promoted_users = []
        demoted_users = []
        staying_users = []
        
        # Process each group for promotions/demotions
        for group_idx, group in enumerate(new_groups):
            # Sort group by totalXP descending
            sorted_group = sorted(group, key=lambda u: u['totalXP'], reverse=True)
            
            group_promoted = 0
            group_demoted = 0
            
            # Handle promotions (except for Legendary)
            if tier_id < len(TIERS) - 1 and promote_count > 0:
                users_to_promote = min(promote_count, len(sorted_group))
                promoted_users.extend(sorted_group[:users_to_promote])
                group_promoted = users_to_promote
                
            # Handle demotions (except for Copper)
            if tier_id > 0 and demote_count > 0:
                if tier_id == 6:  # Legendary tier - keep top 3
                    if len(sorted_group) > 3:
                        demoted_users.extend(sorted_group[3:])
                        group_demoted = len(sorted_group) - 3
                else:
                    users_to_demote = min(demote_count, len(sorted_group) - group_promoted)
                    if users_to_demote > 0:
                        demoted_users.extend(sorted_group[-(users_to_demote):])
                        group_demoted = users_to_demote
            
            # Users staying in current tier
            staying_in_group = sorted_group[group_promoted:(len(sorted_group)-group_demoted if group_demoted > 0 else len(sorted_group))]
            staying_users.extend(staying_in_group)
            
        # Assign new group IDs to staying users
        staying_groups = shuffle_users_by_activity(staying_users, GROUP_SIZE)
        for group_idx, group in enumerate(staying_groups):
            for user in group:
                all_updates.append({
                    'user_id': user['userID'],
                    'tier_id': tier_id,
                    'group_id': group_idx
                })
        
        # Handle promoted users
        if promoted_users and tier_id < len(TIERS) - 1:
            target_tier_users = tier_users.get(tier_id + 1, [])
            combined_target_users = target_tier_users + promoted_users
            target_groups = shuffle_users_by_activity(combined_target_users, GROUP_SIZE)
            
            for group_idx, group in enumerate(target_groups):
                for user in group:
                    if user['userID'] in [u['userID'] for u in promoted_users]:
                        all_updates.append({
                            'user_id': user['userID'],
                            'tier_id': tier_id + 1,
                            'group_id': group_idx
                        })
                        print(f"Promoting {user['username']} to {TIERS[tier_id + 1]['name']}")
        
        # Handle demoted users  
        if demoted_users and tier_id > 0:
            target_tier_users = tier_users.get(tier_id - 1, [])
            combined_target_users = target_tier_users + demoted_users
            target_groups = shuffle_users_by_activity(combined_target_users, GROUP_SIZE)
            
            for group_idx, group in enumerate(target_groups):
                for user in group:
                    if user['userID'] in [u['userID'] for u in demoted_users]:
                        all_updates.append({
                            'user_id': user['userID'],
                            'tier_id': tier_id - 1,
                            'group_id': group_idx
                        })
                        print(f"Demoting {user['username']} to {TIERS[tier_id - 1]['name']}")
    
    # Apply all updates in batches
    if all_updates:
        print(f"Applying {len(all_updates)} updates...")
        batch_update_users(all_updates)
        print("Tier rotation and shuffling completed successfully!")
    else:
        print("No updates needed.")

if __name__ == "__main__":
    rotate_tiers()
