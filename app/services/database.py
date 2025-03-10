import os
from supabase import create_client, Client
from dotenv import load_dotenv
from app.models.user import User, ConnectionRequest

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)


async def create_user(user: User, discord_id: str = None) -> User:
    """
    Create a new user in the database.
    
    Args:
        user: User object containing user information
        discord_id: Discord user ID (optional)
        
    Returns:
        User object with ID
    """
    try:
        # Create the user data dictionary
        user_data = {
            "name": user.name,
            "phone": user.phone,
            "resume_url": user.resume_url,
            "resume_text": user.resume_text,
            "has_resume": user.has_resume,
            "connection_requests": user.connection_requests or []
        }
        
        # Add Discord ID if provided
        if discord_id:
            user_data["discord_id"] = discord_id
        
        # Insert the user
        response = supabase.table("users").insert(user_data).execute()
        
        if not response.data:
            print("No data returned from user creation")
            return None
        
        data = response.data[0]
        user.id = data.get("id")
        return user
    except Exception as e:
        print(f"Error creating user: {e}")
        return None


async def get_user(user_id: str) -> User:
    """
    Get a user by ID or Discord ID.
    
    Args:
        user_id: User ID or Discord ID
        
    Returns:
        User object or None if not found
    """
    try:
        # Check if this looks like a Discord ID (numeric string)
        is_discord_id = user_id.isdigit()
        
        if is_discord_id:
            print(f"Looking up user by Discord ID: {user_id}")
            # Query by discord_id field
            response = supabase.table("users").select("*").eq("discord_id", user_id).execute()
        else:
            print(f"Looking up user by database ID: {user_id}")
            # Query by id field (UUID)
            response = supabase.table("users").select("*").eq("id", user_id).execute()
        
        # Check if we found a user
        if not response.data:
            print(f"No user found for ID: {user_id}")
            return None
        
        # Create and return the user object
        user_data = response.data[0]
        return User(
            id=user_data.get("id"),
            name=user_data.get("name"),
            phone=user_data.get("phone"),
            resume_url=user_data.get("resume_url"),
            resume_text=user_data.get("resume_text"),
            has_resume=user_data.get("has_resume", False),
            connection_requests=user_data.get("connection_requests", [])
        )
    except Exception as e:
        print(f"Error getting user: {e}")
        return None


async def update_user_resume(user_id: str, resume_url: str, resume_text: str) -> User:
    """
    Update a user's resume.
    
    Args:
        user_id: User ID or Discord ID
        resume_url: URL to the resume file
        resume_text: Extracted text from the resume
        
    Returns:
        Updated User object
    """
    try:
        # First get the user to ensure we have the correct database ID
        user = await get_user(user_id)
        if not user:
            print(f"No user found for ID: {user_id}")
            return None
        
        # Now update the user with the correct database ID
        response = supabase.table("users").update({
            "resume_url": resume_url,
            "resume_text": resume_text,
            "has_resume": True
        }).eq("id", user.id).execute()
        
        if not response.data:
            print(f"No data returned from resume update for user: {user_id}")
            return None
        
        user_data = response.data[0]
        return User(
            id=user_data.get("id"),
            name=user_data.get("name"),
            phone=user_data.get("phone"),
            resume_url=user_data.get("resume_url"),
            resume_text=user_data.get("resume_text"),
            has_resume=user_data.get("has_resume", False),
            connection_requests=user_data.get("connection_requests", [])
        )
    except Exception as e:
        print(f"Error updating user resume: {e}")
        return None


async def update_user(user: User) -> User:
    """
    Update a user's information.
    
    Args:
        user: User object with updated information
        
    Returns:
        Updated User object
    """
    update_data = {}
    
    # Only include fields that are not None
    if user.name is not None:
        update_data["name"] = user.name
    
    if user.phone is not None:
        update_data["phone"] = user.phone
    
    if user.resume_url is not None:
        update_data["resume_url"] = user.resume_url
    
    if user.resume_text is not None:
        update_data["resume_text"] = user.resume_text
        
    if user.has_resume is not None:
        update_data["has_resume"] = user.has_resume
        
    if user.connection_requests is not None:
        update_data["connection_requests"] = user.connection_requests
    
    # If there's nothing to update, return the user as is
    if not update_data:
        return user
    
    response = supabase.table("users").update(update_data).eq("id", user.id).execute()
    
    if not response.data:
        return None
    
    user_data = response.data[0]
    return User(
        id=user_data.get("id"),
        name=user_data.get("name"),
        phone=user_data.get("phone"),
        resume_url=user_data.get("resume_url"),
        resume_text=user_data.get("resume_text"),
        has_resume=user_data.get("has_resume", False),
        connection_requests=user_data.get("connection_requests", [])
    )


async def get_users_by_category(category: str):
    """
    Get users that match a specific category based on their resume content.
    
    Args:
        category: Category to search for
        
    Returns:
        List of User objects
    """
    # This is a simplified implementation. In a real-world scenario,
    # you might want to use more sophisticated search techniques.
    response = supabase.table("users").select("*").execute()
    
    users = []
    for user_data in response.data:
        # Include all users who have a resume_text
        if user_data.get("resume_text"):
            users.append(User(
                id=user_data.get("id"),
                name=user_data.get("name"),
                phone=user_data.get("phone"),
                resume_url=user_data.get("resume_url"),
                resume_text=user_data.get("resume_text")
            ))
    
    return users


async def get_all_users():
    """
    Get all users from the database.
    
    Returns:
        List of User objects
    """
    response = supabase.table("users").select("*").execute()
    
    users = []
    for user_data in response.data:
        users.append(User(
            id=user_data.get("id"),
            name=user_data.get("name"),
            phone=user_data.get("phone"),
            resume_url=user_data.get("resume_url"),
            resume_text=user_data.get("resume_text")
        ))
    
    return users


async def delete_user(user_id: str) -> bool:
    """
    Delete a user from the database.
    
    Args:
        user_id: User ID
        
    Returns:
        True if the user was deleted, False otherwise
    """
    try:
        response = supabase.table("users").delete().eq("id", user_id).execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"Error deleting user: {e}")
        return False


async def add_connection_request(user_id: str, requester_id: str) -> bool:
    """
    Add a connection request to a user's record.
    
    Args:
        user_id: ID of the user who was requested (database ID)
        requester_id: ID of the user who made the request (Discord ID)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get the user's current connection requests
        user = await get_user(user_id)
        if not user:
            print(f"No user found for ID: {user_id}")
            return False
            
        # Add the requester to the list if not already there
        if requester_id not in user.connection_requests:
            user.connection_requests.append(requester_id)
            
        # Update the user
        updated_user = await update_user(user)
        return updated_user is not None
    except Exception as e:
        print(f"Error adding connection request: {e}")
        return False 