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
        return candidates[0], f"{candidates[0].name} is the best match available in our network."
    
    # Prepare the system prompt with clear instructions - now more lenient
    system_prompt = """You are a professional networking assistant that helps match people based on their skills, experience, and background.
    
Your task is to analyze candidate resumes and determine the best match for a specific request.

IMPORTANT: Be GENEROUS in your matching. Look for ANY relevant skills or experience that might be valuable, even if it's not a perfect match. Your goal is to FIND connections, not reject them.

Guidelines:
1. Focus on the candidate's skills, experience, education, and relevant background
2. Look for transferable skills and adjacent experience that could be relevant
3. If someone has even PARTIAL experience in the requested area, consider them a potential match
4. Be creative in identifying how a candidate's background could be valuable to the requester
5. DO NOT mention file names, database information, or any technical details about how the data is stored
6. DO NOT reveal personal contact information beyond what's explicitly provided
7. ALWAYS try to find at least one candidate who could be a reasonable match
8. Only in the most extreme cases (completely unrelated fields with no transferable skills) should you indicate no match

Format your response exactly as follows:
- "Candidate X is the best match because [professional reasons, highlighting relevant skills and experience]"
- Only in extreme cases: "No good match found because [explanation of skills/experience gap without naming any individuals]"
"""

    # Prepare the user prompt
    user_prompt = f"""I need to find the best person to connect with someone who is looking for: {request_description}

Here are the potential candidates based on their resumes:

"""
    
    # Add each candidate's resume to the prompt
    for i, candidate in enumerate(candidates):
        user_prompt += f"Candidate {i+1}:\n"
        user_prompt += f"Name: {candidate.name}\n"
        resume_text = candidate.resume_text or "No resume provided"
        # Limit resume text to avoid token limits
        if len(resume_text) > 1000:
            resume_text = resume_text[:1000] + "..."
        user_prompt += f"Resume: {resume_text}\n\n"
    
    user_prompt += """Based on the request and the candidates' resumes, which candidate would be the best match?
Remember to be generous in your matching - look for ANY relevant skills or experience that might be valuable.
Only indicate "No good match found" in extreme cases where there is absolutely no relevant connection possible.
"""
    
    try:
        # Prepare the request payload for Mistral API
        payload = {
            "model": "mistral-large-latest",  # Using Mistral's large model
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.5  # Increased temperature for more creative matching
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
            
            # Reduced list of no_match_indicators to be less strict
            no_match_indicators = [
                "no good match found",
                "no suitable candidates",
                "none of the candidates have any"
            ]
            
            # Check if any of the no-match indicators are in the response (case insensitive)
            # Only exact phrases will trigger a no-match
            if any(indicator.lower() in ai_response.lower() for indicator in no_match_indicators):
                print("Mistral indicated no good match was found")
                
                # Even if Mistral says no match, try to find the most relevant candidate anyway
                # This makes the system more lenient
                most_relevant_candidate = candidates[0]  # Default to first candidate
                
                # Clean up the explanation to remove any technical details
                explanation = "While there isn't a perfect match, this person might have some relevant skills or experience that could be valuable. I recommend reaching out to explore potential synergies."
                
                # Return the first candidate as a fallback
                return most_relevant_candidate, explanation
            
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
                
                # Remove any mentions of database, files, etc.
                explanation = re.sub(r'(?i)(database|file|stored|record|system)', 'network', explanation)
                
                return selected_candidate, explanation
            
            # If no specific candidate was found but the response doesn't indicate no match,
            # try to find the best candidate based on the first few words
            first_word = ai_response.split()[0] if ai_response else ""
            if first_word.isdigit() and 1 <= int(first_word) <= len(candidates):
                # If the response starts with a number, use that as the candidate index
                candidate_index = int(first_word) - 1
                candidate = candidates[candidate_index]
                return candidate, f"{candidate.name} is the best match based on their professional experience and skills."
            
            # Last resort: return the first candidate with a positive message
            print("No specific candidate found in Mistral response, defaulting to first candidate")
            return candidates[0], f"{candidates[0].name} has experience that could be relevant to your needs. While not a perfect match, they might offer valuable insights or connections."
    except Exception as e:
        print(f"Error calling Mistral API: {e}")
        # Return the first candidate with an error message
        if candidates:
            return candidates[0], f"I found {candidates[0].name} who might be able to help with your request. Please connect with them to explore potential synergies."
        return None, f"Error processing match and no candidates available. Please try again later." 