from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, File, UploadFile, Form
from typing import Optional
import os
import tempfile
from pydantic import BaseModel
import re

from app.models.user import User, ConnectionRequest
from app.services.database import create_user, get_user, update_user_resume, get_users_by_category, get_all_users
from app.services.openai_service import find_best_match
from app.utils.resume_parser import process_resume

router = APIRouter(
    prefix="/api/discord",
    tags=["discord"],
    responses={404: {"description": "Not found"}},
)


class MatchResponse(BaseModel):
    """Response model for connection matches."""
    user: User
    explanation: str


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


@router.post("/connect", response_model=MatchResponse)
async def find_connection(request: ConnectionRequest):
    """
    Find a connection for a user.
    
    Args:
        request: ConnectionRequest object containing the user's request
        
    Returns:
        MatchResponse object containing the best matching User and explanation
    """
    try:
        # Get all users
        candidates = await get_all_users()
        
        if not candidates:
            raise HTTPException(status_code=404, detail="No users found in the database")
        
        # Find the best match using OpenAI
        try:
            best_match, explanation = await find_best_match(request.looking_for, candidates)
        except Exception as e:
            print(f"Error in find_best_match: {e}")
            # If there's an error, return the first candidate with an error message
            if candidates:
                return MatchResponse(
                    user=candidates[0], 
                    explanation=f"Error finding best match, defaulting to {candidates[0].name}. Error: {str(e)}"
                )
            else:
                raise HTTPException(status_code=500, detail=f"Error finding match: {str(e)}")
        
        if not best_match:
            raise HTTPException(
                status_code=404, 
                detail=f"No users matching your specific requirements for '{request.looking_for}' were found. {explanation}"
            )
        
        # Clean up the explanation by replacing "Candidate X" references with the person's name
        clean_explanation = explanation
        for i, candidate in enumerate(candidates):
            candidate_ref = f"Candidate {i+1}"
            if candidate_ref in clean_explanation:
                clean_explanation = clean_explanation.replace(candidate_ref, candidate.name)
        
        # Remove any remaining "Candidate X" references (for candidates not in our list)
        clean_explanation = re.sub(r'Candidate \d+', best_match.name, clean_explanation)
        
        return MatchResponse(user=best_match, explanation=clean_explanation)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in find_connection: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 