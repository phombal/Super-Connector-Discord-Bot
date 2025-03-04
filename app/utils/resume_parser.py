import os
import tempfile
from typing import Tuple
import httpx


async def download_file(url: str) -> str:
    """
    Download a file from a URL and save it to a temporary file.
    
    Args:
        url: URL of the file to download
        
    Returns:
        Path to the temporary file
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        
        # Create a temporary file
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(response.content)
            return path
        except Exception as e:
            os.unlink(path)
            raise e


async def extract_text_from_resume(file_path: str) -> str:
    """
    Extract text from a resume file.
    
    This is a simplified implementation. In a real-world scenario,
    you might want to use more sophisticated techniques like OCR for PDFs,
    parsing DOCX files, etc.
    
    Args:
        file_path: Path to the resume file
        
    Returns:
        Extracted text from the resume
    """
    try:
        # For simplicity, we'll just read the file as text
        # In a real implementation, you'd want to handle different file types
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            return file.read()
    except Exception as e:
        print(f"Error extracting text from resume: {e}")
        return ""


async def process_resume(file_url: str) -> Tuple[str, str]:
    """
    Process a resume file by downloading it and extracting text.
    
    Args:
        file_url: URL of the resume file
        
    Returns:
        Tuple of (file_url, extracted_text)
    """
    try:
        # Download the file
        file_path = await download_file(file_url)
        
        # Extract text from the file
        text = await extract_text_from_resume(file_path)
        
        # Clean up the temporary file
        os.unlink(file_path)
        
        return file_url, text
    except Exception as e:
        print(f"Error processing resume: {e}")
        return file_url, "" 