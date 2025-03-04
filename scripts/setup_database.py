import os
import sys
import asyncio
from dotenv import load_dotenv
from supabase import create_client, Client

# Add the parent directory to the path so we can import the app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)


async def setup_database():
    """Set up the Supabase database schema."""
    try:
        # Create the users table
        print("Creating users table...")
        
        # Note: In Supabase, you typically create tables through the web interface
        # or using SQL migrations. This is a simplified example of how you might
        # create a table programmatically, but in practice, you'd use the Supabase
        # dashboard or SQL migrations.
        
        # Execute SQL to create the users table
        # This is just an example and may not work directly with Supabase's API
        sql = """
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            resume_url TEXT,
            resume_text TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
        
        # In a real application, you'd execute this SQL through the Supabase dashboard
        # or use their SQL API if available
        print("SQL to execute in Supabase dashboard:")
        print(sql)
        
        print("\nDatabase setup complete!")
        print("\nIMPORTANT: Please execute the above SQL in your Supabase dashboard to create the users table.")
        
    except Exception as e:
        print(f"Error setting up database: {e}")


if __name__ == "__main__":
    asyncio.run(setup_database()) 