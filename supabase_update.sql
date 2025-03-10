-- Add has_resume column with default value of false
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS has_resume BOOLEAN DEFAULT false;

-- Add connection_requests column as a JSON array with default empty array
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS connection_requests JSONB DEFAULT '[]'::jsonb;

-- Add discord_id column to store Discord user IDs
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS discord_id TEXT;

-- Create an index on discord_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id);

-- Update existing users who have a resume_url or resume_text to set has_resume to true
UPDATE users 
SET has_resume = true 
WHERE resume_url IS NOT NULL OR resume_text IS NOT NULL;

-- Add a comment explaining the purpose of the discord_id column
COMMENT ON COLUMN users.discord_id IS 'Discord user ID for direct lookups';

-- Make sure the discord_id column allows NULL values (for backward compatibility)
ALTER TABLE users 
ALTER COLUMN discord_id DROP NOT NULL;

-- Create a function to check if a string is a valid UUID
CREATE OR REPLACE FUNCTION is_uuid(text) RETURNS boolean AS $$
BEGIN
  RETURN $1 ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
EXCEPTION
  WHEN others THEN
    RETURN false;
END;
$$ LANGUAGE plpgsql IMMUTABLE; 