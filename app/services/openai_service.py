import os
from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Tuple, Optional
from app.models.user import User

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def find_best_match(request_description: str, candidates: List[User]) -> Tuple[Optional[User], Optional[str]]:
    """
    Find the best match for a connection request using OpenAI's 4o API.
    
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
        return candidates[0], "This is the only candidate available in the database."
    
    # Prepare the prompt for OpenAI
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
    
    If none of the candidates are a good match, please explicitly state "No good match found" and explain why.
    """
    
    try:
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
        print(f"OpenAI response: {ai_response}")
        
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
            print("OpenAI indicated no good match was found")
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
            # Clean up the explanation by removing candidate number references
            clean_explanation = ai_response
            for i in range(len(candidates)):
                candidate_prefix = f"Candidate {i+1}"
                if candidate_prefix in clean_explanation:
                    # We'll keep the original explanation to avoid issues
                    pass
            
            return selected_candidate, clean_explanation
        
        # If no specific candidate was found but the response doesn't indicate no match,
        # try to find the best candidate based on the first few words
        first_word = ai_response.split()[0] if ai_response else ""
        if first_word.isdigit() and 1 <= int(first_word) <= len(candidates):
            # If the response starts with a number, use that as the candidate index
            candidate_index = int(first_word) - 1
            return candidates[candidate_index], ai_response
        
        # Last resort: return the first candidate with a warning
        print("No specific candidate found in OpenAI response, defaulting to first candidate")
        return candidates[0], f"Based on the available information, this person might be a match. Original AI response: {ai_response}"
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # Return the first candidate with an error message
        if candidates:
            return candidates[0], f"Error processing match, defaulting to first available candidate. Error: {str(e)}"
        return None, f"Error processing match and no candidates available. Error: {str(e)}" 