import os
import httpx
from dotenv import load_dotenv
from typing import List, Tuple, Optional
import json
import re
from app.models.user import User

# Load environment variables
load_dotenv()

# Mistral API configuration
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"


async def find_best_match(request_description: str, candidates: List[User]) -> Tuple[Optional[User], Optional[str]]:
    """
    Find the best match for a connection request using Mistral AI API.
    
    Args:
        request_description: Description of what the user is looking for
        candidates: List of potential candidates
        
    Returns:
        Tuple of (best matching User object or None if no good match is found, explanation)
    """
    if not candidates:
        return None, "No candidates available in the database."
    
    # If there's only one candidate, return them
    if len(candidates) == 1:
        return candidates[0], f"{candidates[0].name} is the only candidate available in the database."
    
    # Prepare the prompt for Mistral
    prompt = f"""
    I need to find the best person to connect with someone who is looking for: {request_description}
    
    Here are the potential candidates based on their resumes:
    
    """
    
    # Add each candidate's resume to the prompt
    for i, candidate in enumerate(candidates):
        prompt += f"Candidate {i+1}:\n"
        prompt += f"Name: {candidate.name}\n"
        resume_text = candidate.resume_text or "No resume provided"
        # Limit resume text to avoid token limits
        if len(resume_text) > 1000:
            resume_text = resume_text[:1000] + "..."
        prompt += f"Resume: {resume_text}\n\n"
    
    prompt += """
    Based on the request and the candidates' resumes, which candidate would be the best match?
    Please respond with the candidate number (e.g., "Candidate 1") at the beginning of your response, 
    followed by a clear and concise explanation of why they are the best match.
    
    Format your response like this:
    "Candidate X is the best match because [explanation]"
    
    If none of the candidates are a good match, please explicitly state "No good match found" and explain why.
    """
    
    try:
        # Prepare the request payload for Mistral API
        payload = {
            "model": "mistral-large-latest",  # Using Mistral's large model
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that matches people based on their skills and experience."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MISTRAL_API_KEY}"
        }
        
        # Call Mistral API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                MISTRAL_API_URL,
                headers=headers,
                json=payload,
                timeout=30.0  # Increased timeout for API call
            )
            
            # Check if the request was successful
            response.raise_for_status()
            
            # Parse the response
            response_data = response.json()
            ai_response = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            print(f"Mistral response: {ai_response}")
            
            # Check if the response indicates no good match was found
            no_match_indicators = [
                "no good match",
                "no suitable match",
                "no appropriate match",
                "none of the candidates",
                "not a good match",
                "no match found"
            ]
            
            # Check if any of the no-match indicators are in the response (case insensitive)
            if any(indicator.lower() in ai_response.lower() for indicator in no_match_indicators):
                print("Mistral indicated no good match was found")
                return None, ai_response
            
            # Parse the response to get the candidate number and explanation
            selected_candidate = None
            
            # Try to find a candidate number in the response
            for i, candidate in enumerate(candidates):
                candidate_marker = f"Candidate {i+1}"
                if candidate_marker in ai_response:
                    selected_candidate = candidate
                    break
            
            # If we found a candidate, return them with the explanation
            if selected_candidate:
                # Clean up the explanation to focus on the reasoning
                explanation = ai_response
                
                # Try to extract just the explanation part if it follows a standard format
                match = re.search(r'Candidate \d+ is the best match because (.*)', explanation, re.IGNORECASE)
                if match:
                    explanation = f"{selected_candidate.name} is the best match because {match.group(1)}"
                
                return selected_candidate, explanation
            
            # If no specific candidate was found but the response doesn't indicate no match,
            # try to find the best candidate based on the first few words
            first_word = ai_response.split()[0] if ai_response else ""
            if first_word.isdigit() and 1 <= int(first_word) <= len(candidates):
                # If the response starts with a number, use that as the candidate index
                candidate_index = int(first_word) - 1
                candidate = candidates[candidate_index]
                return candidate, f"{candidate.name} is the best match based on the analysis."
            
            # Last resort: return the first candidate with a warning
            print("No specific candidate found in Mistral response, defaulting to first candidate")
            return candidates[0], f"{candidates[0].name} might be a match based on the available information."
    except Exception as e:
        print(f"Error calling Mistral API: {e}")
        # Return the first candidate with an error message
        if candidates:
            return candidates[0], f"Error processing match, defaulting to {candidates[0].name}. Error: {str(e)}"
        return None, f"Error processing match and no candidates available. Error: {str(e)}" 