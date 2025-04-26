import os
import time
import logging
from jose import jwt, JWTError  # Use jose's jwt module
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Get JWT secret from environment
JWT_SECRET = os.getenv("JWT_SECRET", "your-fallback-secret-key-for-development")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours by default

class AuthError(Exception):
    """Custom exception for authentication errors"""
    def __init__(self, message: str, code: int = 401):
        self.message = message
        self.code = code
        super().__init__(self.message)

def create_token(user_id: str, additional_data: Optional[Dict[str, Any]] = None) -> str:
    """
    Create a JWT token for the given user_id
    
    Args:
        user_id: The user identifier
        additional_data: Optional additional claims to include in the token
        
    Returns:
        str: JWT token string
    """
    now = int(time.time())
    expire = now + (ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    
    # Create the token payload
    payload = {
        "sub": user_id,  # Subject (user identifier)
        "iat": now,      # Issued at time
        "exp": expire,   # Expiration time
    }
    
    # Add any additional data
    if additional_data:
        payload.update(additional_data)
    
    # Encode the token
    try:
        # Use jose's jwt.encode method
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return token
    except Exception as e:
        logger.error(f"Error creating token: {e}")
        raise AuthError("Could not create authentication token")

def validate_token(token: str) -> str:
    """
    Validate a JWT token and return the user_id
    
    Args:
        token: JWT token string
    
    Returns:
        str: User ID extracted from token
        
    Raises:
        AuthError: If token is invalid, expired, or malformed
    """
    if not token:
        logger.warning("Missing token")
        raise AuthError("Missing authentication token")
    
    try:
        # For demo room, allow a simplified token
        if token == "demo" or (len(token) < 50 and "demo" in token):
            logger.info("Using demo token")
            return "demo_user"
            
        # Decode and validate the token using jose
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Extract user_id from subject claim
        user_id = payload.get("sub")
        if not user_id:
            logger.warning("Token missing subject claim")
            raise AuthError("Invalid token: missing user identifier")
            
        # Check if token is expired
        exp = payload.get("exp")
        if exp and int(time.time()) > exp:
            logger.warning(f"Expired token for user {user_id}")
            raise AuthError("Token has expired")
            
        logger.debug(f"Token validated for user {user_id}")
        return user_id
        
    except JWTError as e:  # Use jose's JWTError instead of jwt.InvalidTokenError
        logger.warning(f"Invalid token: {e}")
        raise AuthError(f"Invalid token: {str(e)}")
        
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        raise AuthError(f"Token validation failed: {str(e)}")

def get_current_user_id(token: str) -> str:
    """
    Get the current user ID from a token without full validation
    Useful for logging and debugging
    
    Returns:
        str: User ID or "unknown" if token is invalid
    """
    try:
        return validate_token(token)
    except:
        return "unknown"

def generate_demo_token() -> str:
    """Generate a token for demo purposes"""
    return create_token("demo_user", {"demo": True})