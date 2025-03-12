import os
from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Tuple, Optional
import re
from app.models.user import User

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def find_best_match(request_description: str, candidates: List[User]) -> Tuple[Optional[User], Optional[str]]:
    """
    Find the best match for a connection request using OpenAI's API.
    
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
    
    # Prepare the system prompt with clear instructions - balanced approach
    system_prompt = """You are a professional networking assistant that helps match people based on their skills, experience, and background.
    
Your task is to analyze candidate resumes and determine the best match for a specific request.

Guidelines:
1. Focus on the candidate's skills, experience, education, and relevant background
2. Look for transferable skills and adjacent experience that could be relevant
3. If someone has even PARTIAL experience in the requested area, consider them a potential match
4. Be creative in identifying how a candidate's background could be valuable to the requester
5. DO NOT mention file names, database information, or any technical details about how the data is stored
6. DO NOT reveal personal contact information beyond what's explicitly provided
7. Try to find a candidate who could be a reasonable match
8. IMPORTANT: If none of the candidates have relevant experience or skills for the request, it's better to indicate "No good match found" than to force an inappropriate match
9. Be honest in your assessment - if there truly is no good match, say so and explain why

Your goal is to make meaningful connections, not force matches that don't make sense."""
    
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
Please respond with the candidate number (e.g., "Candidate 1") at the beginning of your response, 
followed by a clear and concise explanation of why they are the best match.

Format your response like this:
"Candidate X is the best match because [explanation]"

If none of the candidates have relevant experience or skills for the request, please explicitly state "No good match found" and explain why.
"""
    
    try:
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=500,
            temperature=0.4  # Slightly reduced temperature for more accurate matching
        )
        
        # Extract the response
        ai_response = response.choices[0].message.content.strip()
        print(f"OpenAI response: {ai_response}")
        
        # Comprehensive list of no_match_indicators
        no_match_indicators = [
            "no good match found",
            "no suitable candidates",
            "none of the candidates have",
            "no appropriate match",
            "not a good match",
            "no match found",
            "no candidate matches",
            "no relevant match",
            "no candidate has the",
            "no candidate possesses",
            "no candidate with",
            "couldn't find a match",
            "could not find a match",
            "unable to find a match"
        ]
        
        # Check if any of the no-match indicators are in the response (case insensitive)
        if any(indicator.lower() in ai_response.lower() for indicator in no_match_indicators):
            print("OpenAI indicated no good match was found")
            
            # Clean up the explanation to remove any technical details
            explanation = ai_response
            
            # Remove any mentions of database, files, etc.
            explanation = re.sub(r'(?i)(database|file|stored|record|system)', 'network', explanation)
            
            # Remove any candidate names from the explanation to protect privacy
            for candidate in candidates:
                if candidate.name and len(candidate.name) > 2:  # Avoid replacing very short names that might be common words
                    explanation = re.sub(r'(?i)\b' + re.escape(candidate.name) + r'\b', "a candidate", explanation)
            
            # Remove any "Candidate X" references
            explanation = re.sub(r'Candidate \d+', "a candidate", explanation)
            
            # Return None to indicate no match was found
            return None, explanation
        
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
        
        # If we can't determine a match from the response, assume no match was found
        print("No specific candidate found in OpenAI response, assuming no match")
        return None, "No good match found. The candidates in our network don't appear to have the specific experience or skills requested."
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # In case of error, return None to indicate no match
        return None, f"Error processing match: {str(e)}. Please try again with different criteria." 