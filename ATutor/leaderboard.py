from utils import initialize_firebase
from firebase_admin import credentials, firestore,auth



def tiered_leaderboard_desc(request,TIERS,GROUP_SIZE):
    """Get leaderboard for user's current tier and group"""    
    db_client = initialize_firebase()
    if db_client is None:
        print("[ERROR] Firebase client could not be initialized.")
        return {"status": "error", "message": "Internal server error. Firebase not initialized."}
    user_doc = db_client.collection('users').document(request.user_id).get()
    if not user_doc.exists:
        return []
    
    user_data = user_doc.to_dict()
    tier_id = user_data['tierID']
    group_id = user_data['groupID']
    
    # Get all users in same tier and group
    users = db_client.collection('users').where('tierID', '==', tier_id).where('groupID', '==', group_id).order_by('totalXP', direction=firestore.Query.DESCENDING).get()
    
    leaderboard = []
    for i, user in enumerate(users):
        user_data = user.to_dict()
        leaderboard.append({
            'rank': i + 1,
            'username': user_data['username'],
            'totalXP': user_data['totalXP'],
            'tierName': TIERS[tier_id]['name'],
            'isCurrentUser': user_data['userID'] == request.user_id
        })
    
    return leaderboard


def get_friend_leaderboard_desc(request,TIERS,GROUP_SIZE):
    """Get leaderboard showing points among friends"""
    db_client = initialize_firebase()
    if db_client is None:
        print("[ERROR] Firebase client could not be initialized.")
        return {"status": "error", "message": "Internal server error. Firebase not initialized."}
    user_doc = db_client.collection('users').document(request.user_id).get()
    if not user_doc.exists:
        return []
    
    user_data = user_doc.to_dict()
    friend_ids = user_data.get('friends', [])
    
    # Add current user to the list
    friend_ids.append(request.user_id)
    
    leaderboard = []
    for friend_id in friend_ids:
        friend_doc = db_client.collection('users').document(friend_id).get()
        if friend_doc.exists:
            friend_data = friend_doc.to_dict()
            leaderboard.append({
                'username': friend_data['username'],
                'totalXP': friend_data['totalXP'],
                'tierName': TIERS[friend_data['tierID']]['name'],
                'isCurrentUser': friend_id == request.user_id
            })
    
    # Sort by totalXP descending
    leaderboard.sort(key=lambda x: x['totalXP'], reverse=True)
    
    # Add ranks
    for i, friend in enumerate(leaderboard):
        friend['rank'] = i + 1
    
    return leaderboard
