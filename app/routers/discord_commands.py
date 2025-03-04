from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, File, UploadFile, Form
from typing import Optional
import os
import tempfile

from app.models.user import User, ConnectionRequest
from app.services.database import create_user, get_user, update_user_resume, get_users_by_category
from app.services.openai_service import find_best_match
from app.utils.resume_parser import process_resume

router = APIRouter(
    prefix="/api/discord",
    tags=["discord"],
    responses={404: {"description": "Not found"}},
)


@router.post("/register")
async def register_user(name: str = Form(...), phone: str = Form(...), resume: Optional[UploadFile] = File(None)):
    """
    Register a new user with the bot.
    
    Args:
        name: User's full name
        phone: User's phone number
        resume: User's resume file (optional)
        
    Returns:
        User object
    """
    try:
        # Create a new user
        user = User(name=name, phone=phone)
        user = await create_user(user)
        
        # Process the resume if provided
        if resume:
            # Save the file to a temporary location
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                contents = await resume.read()
                temp_file.write(contents)
                temp_file.flush()
                
                # Process the resume
                file_url = f"local://{temp_file.name}"  # In a real app, you'd upload to a storage service
                
                # Extract text from the resume
                file_url, resume_text = await process_resume(temp_file.name)
                
                # Update the user's resume
                user = await update_user_resume(user.id, file_url, resume_text)
                
                # Clean up the temporary file
                os.unlink(temp_file.name)
        
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect")
async def find_connection(request: ConnectionRequest):
    """
    Find a connection for a user.
    
    Args:
        request: ConnectionRequest object containing the user's request
        
    Returns:
        Best matching User object
    """
    try:
        # Get users that match the category
        candidates = await get_users_by_category(request.looking_for)
        
        if not candidates:
            raise HTTPException(status_code=404, detail=f"No users found matching '{request.looking_for}'")
        
        # Find the best match using OpenAI
        best_match = await find_best_match(request.looking_for, candidates)
        
        if not best_match:
            raise HTTPException(status_code=404, detail=f"No good match found for '{request.looking_for}'")
        
        return best_match
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 