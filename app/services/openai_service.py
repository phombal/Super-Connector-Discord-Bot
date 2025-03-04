import os
from openai import OpenAI
from dotenv import load_dotenv
from typing import List
from app.models.user import User

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def find_best_match(request_description: str, candidates: List[User]) -> User:
    """
    Find the best match for a connection request using OpenAI's 4o API.
    
    Args:
        request_description: Description of what the user is looking for
        candidates: List of potential candidates
        
    Returns:
        Best matching User object
    """
    if not candidates:
        return None
    
    # If there's only one candidate, return them
    if len(candidates) == 1:
        return candidates[0]
    
    # Prepare the prompt for OpenAI
    prompt = f"""
    I need to find the best person to connect with someone who is looking for: {request_description}
    
    Here are the potential candidates based on their resumes:
    
    """
    
    # Add each candidate's resume to the prompt
    for i, candidate in enumerate(candidates):
        prompt += f"Candidate {i+1}:\n"
        prompt += f"Name: {candidate.name}\n"
        prompt += f"Resume: {candidate.resume_text}\n\n"
    
    prompt += """
    Based on the request and the candidates' resumes, which candidate would be the best match?
    Please respond with just the candidate number (e.g., "Candidate 1") and a brief explanation of why they are the best match.
    """
    
    # Call OpenAI API
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that matches people based on their skills and experience."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=500
    )
    
    # Extract the response
    ai_response = response.choices[0].message.content.strip()
    
    # Parse the response to get the candidate number
    try:
        # Look for "Candidate X" in the response
        for i, candidate in enumerate(candidates):
            if f"Candidate {i+1}" in ai_response:
                return candidate
        
        # If no specific candidate was found, return the first one
        return candidates[0]
    except Exception as e:
        print(f"Error parsing OpenAI response: {e}")
        # Default to the first candidate if there's an error
        return candidates[0] 