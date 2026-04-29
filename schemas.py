# schemas.py

from pydantic import BaseModel

class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class RatingCreate(BaseModel):
    tmdb_id: int
    rating: int