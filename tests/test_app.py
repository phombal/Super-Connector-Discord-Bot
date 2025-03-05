import pytest
from fastapi.testclient import TestClient
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.models.user import User


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_supabase():
    """Mock the Supabase client."""
    with patch("app.services.database.supabase") as mock:
        # Mock the insert method
        mock.table().insert().execute.return_value.data = [{"id": "test-id", "name": "Test User", "phone": "1234567890"}]
        
        # Mock the select method
        mock.table().select().eq().execute.return_value.data = [{"id": "test-id", "name": "Test User", "phone": "1234567890"}]
        
        # Mock the update method
        mock.table().update().eq().execute.return_value.data = [{"id": "test-id", "name": "Test User", "phone": "1234567890", "resume_url": "test-url", "resume_text": "test-text"}]
        
        # Mock the select all method
        mock.table().select().execute.return_value.data = [
            {"id": "test-id-1", "name": "Test User 1", "phone": "1234567890", "resume_text": "software engineer with 5 years experience"},
            {"id": "test-id-2", "name": "Test User 2", "phone": "0987654321", "resume_text": "marketing expert with 10 years experience"}
        ]
        
        yield mock


@pytest.fixture
def mock_openai():
    """Mock the OpenAI client."""
    with patch("app.services.openai_service.client") as mock:
        # Mock the chat.completions.create method
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Candidate 1 is the best match because they have experience as a software engineer."
        mock.chat.completions.create.return_value = mock_response
        
        yield mock


@pytest.fixture
def mock_mistral():
    """Mock the Mistral API client."""
    with patch("httpx.AsyncClient.post") as mock_post:
        # Create a mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Candidate 1 is the best match because they have experience as a software engineer with relevant skills in programming and problem-solving."
                    }
                }
            ]
        }
        mock_post.return_value = mock_response
        
        yield mock_post


def test_root(client):
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Discord Super Connector Bot API is running"}


@patch("app.routers.discord_commands.create_user")
async def test_register_user(mock_create_user, client, mock_supabase):
    """Test the register_user endpoint."""
    # Mock the create_user function
    mock_create_user.return_value = User(id="test-id", name="Test User", phone="1234567890")
    
    # Make the request
    response = client.post(
        "/api/discord/register",
        data={"name": "Test User", "phone": "1234567890"}
    )
    
    # Check the response
    assert response.status_code == 200
    assert response.json()["id"] == "test-id"
    assert response.json()["name"] == "Test User"
    assert response.json()["phone"] == "1234567890"


@patch("app.routers.discord_commands.get_all_users")
@patch("app.routers.discord_commands.find_best_match")
async def test_find_connection(mock_find_best_match, mock_get_users, client, mock_supabase, mock_mistral):
    """Test the find_connection endpoint."""
    # Mock the get_users_by_category function
    test_users = [
        User(id="test-id-1", name="Test User 1", phone="1234567890", resume_text="software engineer with 5 years experience"),
        User(id="test-id-2", name="Test User 2", phone="0987654321", resume_text="marketing expert with 10 years experience")
    ]
    mock_get_users.return_value = test_users
    
    # Mock the find_best_match function
    test_user = User(id="test-id-1", name="Test User 1", phone="1234567890", resume_text="software engineer with 5 years experience")
    explanation = "Test User 1 is the best match because they have experience as a software engineer with relevant skills in programming and problem-solving."
    mock_find_best_match.return_value = (test_user, explanation)
    
    # Make the request
    response = client.post(
        "/api/discord/connect",
        json={"user_id": "requester-id", "looking_for": "software engineer"}
    )
    
    # Check the response
    assert response.status_code == 200
    assert response.json()["user"]["id"] == "test-id-1"
    assert response.json()["user"]["name"] == "Test User 1"
    assert response.json()["user"]["phone"] == "1234567890"
    assert "Test User 1 is the best match" in response.json()["explanation"]
    assert "programming and problem-solving" in response.json()["explanation"]


@patch("app.routers.discord_commands.get_all_users")
@patch("app.routers.discord_commands.find_best_match")
async def test_find_connection_no_match(mock_find_best_match, mock_get_users, client, mock_supabase, mock_mistral):
    """Test the find_connection endpoint when no match is found."""
    # Mock the get_users_by_category function
    mock_get_users.return_value = [
        User(id="test-id-1", name="Test User 1", phone="1234567890", resume_text="software engineer with 5 years experience"),
        User(id="test-id-2", name="Test User 2", phone="0987654321", resume_text="marketing expert with 10 years experience")
    ]
    
    # Mock the find_best_match function to return None (no match found)
    explanation = "No good match found because none of the candidates have the required skills in data science or machine learning."
    mock_find_best_match.return_value = (None, explanation)
    
    # Make the request
    response = client.post(
        "/api/discord/connect",
        json={"user_id": "requester-id", "looking_for": "data scientist"}
    )
    
    # Check the response
    assert response.status_code == 404
    assert "No users matching your specific requirements" in response.json()["detail"]
    assert "data science or machine learning" in response.json()["detail"]


@patch("app.routers.discord_commands.get_all_users")
@patch("app.routers.discord_commands.find_best_match")
async def test_find_connection_error(mock_find_best_match, mock_get_users, client, mock_supabase, mock_mistral):
    """Test the find_connection endpoint when an error occurs."""
    # Mock the get_users_by_category function
    test_users = [
        User(id="test-id-1", name="Test User 1", phone="1234567890", resume_text="software engineer with 5 years experience"),
        User(id="test-id-2", name="Test User 2", phone="0987654321", resume_text="marketing expert with 10 years experience")
    ]
    mock_get_users.return_value = test_users
    
    # Mock the find_best_match function to raise an exception
    mock_find_best_match.side_effect = Exception("Test error")
    
    # Make the request
    response = client.post(
        "/api/discord/connect",
        json={"user_id": "requester-id", "looking_for": "software engineer"}
    )
    
    # Check the response - should return the first candidate with an error message
    assert response.status_code == 200
    assert response.json()["user"]["id"] == "test-id-1"
    assert "Error finding best match" in response.json()["explanation"]
    assert "Please try again with more specific criteria" in response.json()["explanation"] 