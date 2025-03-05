from pydantic import BaseModel, Field, validator
from typing import Optional
import re


class User(BaseModel):
    """User model for storing user information."""
    
    id: Optional[str] = None
    name: str
    phone: str
    resume_url: Optional[str] = None
    resume_text: Optional[str] = None
    
    @validator('phone')
    def validate_phone(cls, v):
        """Validate phone number format."""
        # Remove any non-digit characters
        phone = re.sub(r'\D', '', v)
        
        # Check if the phone number has a valid length
        if len(phone) < 10 or len(phone) > 15:
            raise ValueError('Phone number must be between 10 and 15 digits')
        
        return phone

    class Config:
        orm_mode = True


class ConnectionRequest(BaseModel):
    """Model for connection requests."""
    
    user_id: str
    looking_for: str
    additional_info: Optional[str] = None
    
    class Config:
        orm_mode = True 