import os
import pickle
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import httpx
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from jose import jwt

from auth import hash_password, verify_password
from db import supabase
from schemas import UserCreate, UserLogin, RatingCreate




# =========================
# ENV
# =========================
load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_500 = "https://image.tmdb.org/t/p/w500"

TMDB_GENRE_MAP = {
    "Action": 28,
    "Adventure": 12,
    "Animation": 16,
    "Comedy": 35,
    "Crime": 80,
    "Drama": 18,
    "Family": 10751,
    "Fantasy": 14,
    "Horror": 27,
    "Mystery": 9648,
    "Romance": 10749,
    "Science": 878,
    "Science Fiction": 878,
    "Thriller": 53,
}

# =========================
# JWT CONFIG
# =========================
SECRET_KEY = "personaflix_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

security = HTTPBearer()

if not TMDB_API_KEY:
    # Don't crash import-time in production if you prefer; but for you better fail early:
    raise RuntimeError("TMDB_API_KEY missing. Put it in .env as TMDB_API_KEY=xxxx")


# =========================
# FASTAPI APP
# =========================
app = FastAPI(title="Movie Recommender API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for local streamlit
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# PICKLE GLOBALS
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DF_PATH = os.path.join(BASE_DIR, "df.pkl")
INDICES_PATH = os.path.join(BASE_DIR, "indices.pkl")
TFIDF_MATRIX_PATH = os.path.join(BASE_DIR, "tfidf_matrix.pkl")
TFIDF_PATH = os.path.join(BASE_DIR, "tfidf.pkl")

df: Optional[pd.DataFrame] = None
indices_obj: Any = None
tfidf_matrix: Any = None
tfidf_obj: Any = None

TITLE_TO_IDX: Optional[Dict[str, int]] = None


# =========================
# MODELS
# =========================
class TMDBMovieCard(BaseModel):
    tmdb_id: int
    title: str
    poster_url: Optional[str] = None
    release_date: Optional[str] = None
    vote_average: Optional[float] = None


class TMDBMovieDetails(BaseModel):
    tmdb_id: int
    title: str
    overview: Optional[str] = None
    release_date: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    genres: List[dict] = []


class TFIDFRecItem(BaseModel):
    title: str
    score: float
    tmdb: Optional[TMDBMovieCard] = None


class SearchBundleResponse(BaseModel):
    query: str
    movie_details: TMDBMovieDetails
    tfidf_recommendations: List[TFIDFRecItem]
    genre_recommendations: List[TMDBMovieCard]


# =========================
# UTILS
# =========================

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        user_id = payload.get("user_id")
        username = payload.get("username")

        if not user_id or not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        return {
            "user_id": user_id,
            "username": username
        }

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def _norm_title(t: str) -> str:
    return str(t).strip().lower()


def make_img_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"{TMDB_IMG_500}{path}"


async def tmdb_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safe TMDB GET with retry:
    - Network timeout -> retry
    - TMDB API errors -> 502
    """
    q = dict(params)
    q["api_key"] = TMDB_API_KEY

    last_error = None

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{TMDB_BASE}{path}", params=q)

            if r.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"TMDB error {r.status_code}: {r.text}"
                )

            return r.json()

        except httpx.RequestError as e:
            last_error = e

    raise HTTPException(
        status_code=502,
        detail=f"TMDB request error after retries: {type(last_error).__name__} | {repr(last_error)}",
    )


async def tmdb_cards_from_results(
    results: List[dict], limit: int = 20
) -> List[TMDBMovieCard]:
    out: List[TMDBMovieCard] = []
    for m in (results or [])[:limit]:
        out.append(
            TMDBMovieCard(
                tmdb_id=int(m["id"]),
                title=m.get("title") or m.get("name") or "",
                poster_url=make_img_url(m.get("poster_path")),
                release_date=m.get("release_date"),
                vote_average=m.get("vote_average"),
            )
        )
    return out


async def tmdb_movie_details(movie_id: int) -> TMDBMovieDetails:
    data = await tmdb_get(f"/movie/{movie_id}", {"language": "en-US"})
    return TMDBMovieDetails(
        tmdb_id=int(data["id"]),
        title=data.get("title") or "",
        overview=data.get("overview"),
        release_date=data.get("release_date"),
        poster_url=make_img_url(data.get("poster_path")),
        backdrop_url=make_img_url(data.get("backdrop_path")),
        genres=data.get("genres", []) or [],
    )


async def tmdb_search_movies(query: str, page: int = 1) -> Dict[str, Any]:
    """
    Raw TMDB response for keyword search (MULTIPLE results).
    Streamlit will use this for suggestions and grid.
    """
    return await tmdb_get(
        "/search/movie",
        {
            "query": query,
            "include_adult": "false",
            "language": "en-US",
            "page": page,
        },
    )


async def tmdb_search_first(query: str) -> Optional[dict]:
    data = await tmdb_search_movies(query=query, page=1)
    results = data.get("results", [])
    return results[0] if results else None


# =========================
# TF-IDF Helpers
# =========================
def build_title_to_idx_map(indices: Any) -> Dict[str, int]:
    """
    indices.pkl can be:
    - dict(title -> index)
    - pandas Series (index=title, value=index)
    We normalize into TITLE_TO_IDX.
    """
    title_to_idx: Dict[str, int] = {}

    if isinstance(indices, dict):
        for k, v in indices.items():
            title_to_idx[_norm_title(k)] = int(v)
        return title_to_idx

    # pandas Series or similar mapping
    try:
        for k, v in indices.items():
            title_to_idx[_norm_title(k)] = int(v)
        return title_to_idx
    except Exception:
        # last resort: if it's a list-like etc.
        raise RuntimeError(
            "indices.pkl must be dict or pandas Series-like (with .items())"
        )


def get_local_idx_by_title(title: str) -> int:
    global TITLE_TO_IDX
    if TITLE_TO_IDX is None:
        raise HTTPException(status_code=500, detail="TF-IDF index map not initialized")
    key = _norm_title(title)
    if key in TITLE_TO_IDX:
        return int(TITLE_TO_IDX[key])
    raise HTTPException(
        status_code=404, detail=f"Title not found in local dataset: '{title}'"
    )

def get_local_genres_by_title(title: str) -> List[str]:
    """
    Returns genre list for a movie title from local df.pkl.
    Example genre text: 'Animation Comedy Family'
    """
    global df

    if df is None or "title" not in df.columns or "genres" not in df.columns:
        return []

    key = _norm_title(title)

    try:
        matches = df[df["title"].apply(lambda x: _norm_title(x) == key)]
    except Exception:
        return []

    if matches.empty:
        return []

    genre_text = str(matches.iloc[0].get("genres", "") or "")

    return [g.strip() for g in genre_text.split() if g.strip()]

def get_local_title_by_tmdb_id(tmdb_id: int) -> Optional[str]:
    """
    Returns local movie title from df.pkl using TMDB/movie id if available.
    This helps For You work even when TMDB API is temporarily unavailable.
    """
    global df

    if df is None:
        return None

    possible_id_columns = ["tmdb_id", "id", "movie_id"]

    for col in possible_id_columns:
        if col in df.columns:
            try:
                matches = df[df[col].astype(str) == str(tmdb_id)]
                if not matches.empty and "title" in df.columns:
                    return str(matches.iloc[0]["title"])
            except Exception:
                pass

    return None

def tfidf_recommend_titles(
    query_title: str, top_n: int = 10
) -> List[Tuple[str, float]]:
    """
    Returns list of (title, score) from local df using cosine similarity on TF-IDF matrix.
    Safe against missing columns/rows.
    """
    global df, tfidf_matrix
    if df is None or tfidf_matrix is None:
        raise HTTPException(status_code=500, detail="TF-IDF resources not loaded")

    idx = get_local_idx_by_title(query_title)

    # query vector
    qv = tfidf_matrix[idx]
    scores = (tfidf_matrix @ qv.T).toarray().ravel()

    # sort descending
    order = np.argsort(-scores)

    out: List[Tuple[str, float]] = []
    for i in order:
        if int(i) == int(idx):
            continue
        try:
            title_i = str(df.iloc[int(i)]["title"])
        except Exception:
            continue
        out.append((title_i, float(scores[int(i)])))
        if len(out) >= top_n:
            break
    return out


async def attach_tmdb_card_by_title(title: str) -> Optional[TMDBMovieCard]:
    """
    Uses TMDB search by title to fetch poster for a local title.
    If not found, returns None (never crashes the endpoint).
    """
    try:
        m = await tmdb_search_first(title)
        if not m:
            return None
        return TMDBMovieCard(
            tmdb_id=int(m["id"]),
            title=m.get("title") or title,
            poster_url=make_img_url(m.get("poster_path")),
            release_date=m.get("release_date"),
            vote_average=m.get("vote_average"),
        )
    except Exception:
        return None


# =========================
# STARTUP: LOAD PICKLES
# =========================
@app.on_event("startup")
def load_pickles():
    global df, indices_obj, tfidf_matrix, tfidf_obj, TITLE_TO_IDX

    # Load df
    with open(DF_PATH, "rb") as f:
        df = pickle.load(f)

    # Load indices
    with open(INDICES_PATH, "rb") as f:
        indices_obj = pickle.load(f)

    # Load TF-IDF matrix (usually scipy sparse)
    with open(TFIDF_MATRIX_PATH, "rb") as f:
        tfidf_matrix = pickle.load(f)

    # Load tfidf vectorizer (optional, not used directly here)
    with open(TFIDF_PATH, "rb") as f:
        tfidf_obj = pickle.load(f)

    # Build normalized map
    TITLE_TO_IDX = build_title_to_idx_map(indices_obj)

    # sanity
    if df is None or "title" not in df.columns:
        raise RuntimeError("df.pkl must contain a DataFrame with a 'title' column")


# =========================
# ROUTES
# =========================
@app.get("/health")
def health():
    return {"status": "ok"}


# ---------- HOME FEED (TMDB) ----------
@app.get("/home", response_model=List[TMDBMovieCard])
async def home(
    category: str = Query("popular"),
    limit: int = Query(24, ge=1, le=50),
):
    """
    Home feed for Streamlit.
    Primary: TMDB API.
    Fallback: local df.pkl titles if TMDB is unavailable.
    """
    try:
        if category == "trending":
            data = await tmdb_get("/trending/movie/day", {"language": "en-US"})
            return await tmdb_cards_from_results(data.get("results", []), limit=limit)

        if category not in {"popular", "top_rated", "upcoming", "now_playing"}:
            raise HTTPException(status_code=400, detail="Invalid category")

        data = await tmdb_get(f"/movie/{category}", {"language": "en-US", "page": 1})
        return await tmdb_cards_from_results(data.get("results", []), limit=limit)

    except Exception:
        global df

        if df is None or "title" not in df.columns:
            raise HTTPException(status_code=503, detail="Home feed unavailable")

        fallback_movies = df.head(limit)

        cards = []
        for _, row in fallback_movies.iterrows():
            vote_average = None
            if "vote_average" in df.columns and pd.notna(row.get("vote_average")):
                try:
                    vote_average = float(row.get("vote_average"))
                except Exception:
                    vote_average = None

            cards.append(
                TMDBMovieCard(
                    tmdb_id=0,
                    title=str(row["title"]),
                    poster_url=None,
                    release_date=None,
                    vote_average=vote_average,
                )
            )

        return cards


# ---------- TMDB KEYWORD SEARCH (MULTIPLE RESULTS) ----------
@app.get("/tmdb/search")
async def tmdb_search(
    query: str = Query(..., min_length=1),
    page: int = Query(1, ge=1, le=10),
):
    """
    Returns RAW TMDB shape with 'results' list.
    Streamlit will use it for:
      - dropdown suggestions
      - grid results
    """
    return await tmdb_search_movies(query=query, page=page)


# ---------- MOVIE DETAILS (SAFE ROUTE) ----------
@app.get("/movie/id/{tmdb_id}", response_model=TMDBMovieDetails)
async def movie_details_route(tmdb_id: int):
    return await tmdb_movie_details(tmdb_id)


# ---------- GENRE RECOMMENDATIONS ----------
@app.get("/recommend/genre", response_model=List[TMDBMovieCard])
async def recommend_genre(
    tmdb_id: int = Query(...),
    limit: int = Query(18, ge=1, le=50),
):
    """
    Given a TMDB movie ID:
    - fetch details
    - pick first genre
    - discover movies in that genre (popular)
    """
    details = await tmdb_movie_details(tmdb_id)
    if not details.genres:
        return []

    genre_id = details.genres[0]["id"]
    discover = await tmdb_get(
        "/discover/movie",
        {
            "with_genres": genre_id,
            "language": "en-US",
            "sort_by": "popularity.desc",
            "page": 1,
        },
    )
    cards = await tmdb_cards_from_results(discover.get("results", []), limit=limit)
    return [c for c in cards if c.tmdb_id != tmdb_id]


# ---------- TF-IDF ONLY (debug/useful) ----------
@app.get("/recommend/tfidf")
async def recommend_tfidf(
    title: str = Query(..., min_length=1),
    top_n: int = Query(10, ge=1, le=50),
):
    recs = tfidf_recommend_titles(title, top_n=top_n)
    return [{"title": t, "score": s} for t, s in recs]


# ---------- BUNDLE: Details + TF-IDF recs + Genre recs ----------
@app.get("/movie/search", response_model=SearchBundleResponse)
async def search_bundle(
    query: str = Query(..., min_length=1),
    tfidf_top_n: int = Query(12, ge=1, le=30),
    genre_limit: int = Query(12, ge=1, le=30),
):
    """
    This endpoint is for when you have a selected movie and want:
      - movie details
      - TF-IDF recommendations (local) + posters
      - Genre recommendations (TMDB) + posters

    NOTE:
    - It selects the BEST match from TMDB for the given query.
    - If you want MULTIPLE matches, use /tmdb/search
    """
    best = await tmdb_search_first(query)
    if not best:
        raise HTTPException(
            status_code=404, detail=f"No TMDB movie found for query: {query}"
        )

    tmdb_id = int(best["id"])
    details = await tmdb_movie_details(tmdb_id)

    # 1) TF-IDF recommendations (never crash endpoint)
    tfidf_items: List[TFIDFRecItem] = []

    recs: List[Tuple[str, float]] = []
    try:
        # try local dataset by TMDB title
        recs = tfidf_recommend_titles(details.title, top_n=tfidf_top_n)
    except Exception:
        # fallback to user query
        try:
            recs = tfidf_recommend_titles(query, top_n=tfidf_top_n)
        except Exception:
            recs = []

    for title, score in recs:
        card = await attach_tmdb_card_by_title(title)
        tfidf_items.append(TFIDFRecItem(title=title, score=score, tmdb=card))

    # 2) Genre recommendations (TMDB discover by first genre)
    genre_recs: List[TMDBMovieCard] = []
    if details.genres:
        genre_id = details.genres[0]["id"]
        discover = await tmdb_get(
            "/discover/movie",
            {
                "with_genres": genre_id,
                "language": "en-US",
                "sort_by": "popularity.desc",
                "page": 1,
            },
        )
        cards = await tmdb_cards_from_results(
            discover.get("results", []), limit=genre_limit
        )
        genre_recs = [c for c in cards if c.tmdb_id != details.tmdb_id]

    return SearchBundleResponse(
        query=query,
        movie_details=details,
        tfidf_recommendations=tfidf_items,
        genre_recommendations=genre_recs,
    )

@app.post("/register")
def register(user: UserCreate):
    hashed_pw = hash_password(user.password)

    data = {
        "username": user.username,
        "password_hash": hashed_pw
    }

    supabase.table("users").insert(data).execute()

    return {"message": "User registered successfully"}

@app.post("/login")
def login(user: UserLogin):
    response = supabase.table("users").select("*").eq("username", user.username).execute()

    if not response.data:
        raise HTTPException(status_code=400, detail="User not found")

    db_user = response.data[0]

    if not verify_password(user.password, db_user["password_hash"]):
        raise HTTPException(status_code=400, detail="Invalid password")

    token = create_access_token({
        "user_id": db_user["id"],
        "username": db_user["username"]
    })

    return {
        "message": "Login successful",
        "access_token": token,
        "token_type": "bearer",
        "username": db_user["username"]
    }    

@app.post("/rate")
def rate_movie(
    rating_data: RatingCreate,
    current_user: dict = Depends(get_current_user)
):
    if rating_data.rating < 1 or rating_data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    data = {
        "user_id": current_user["user_id"],
        "tmdb_id": rating_data.tmdb_id,
        "rating": rating_data.rating
    }

    supabase.table("ratings").upsert(data,on_conflict="user_id,tmdb_id").execute()

    return {
        "message": "Rating saved successfully",
        "user": current_user["username"],
        "tmdb_id": rating_data.tmdb_id,
        "rating": rating_data.rating
    }

@app.get("/my-ratings")
def my_ratings(current_user: dict = Depends(get_current_user)):
    response = (
        supabase
        .table("ratings")
        .select("*")
        .eq("user_id", current_user["user_id"])
        .execute()
    )

    return {
        "user": current_user["username"],
        "ratings": response.data
    }

@app.get("/my-ratings/details")
async def my_ratings_details(current_user: dict = Depends(get_current_user)):
    """
    Returns logged-in user's ratings with TMDB movie details.
    Used by Streamlit My Ratings page.
    """
    response = (
        supabase
        .table("ratings")
        .select("*")
        .eq("user_id", current_user["user_id"])
        .order("created_at", desc=True)
        .execute()
    )

    ratings = response.data or []

    detailed_ratings = []

    for item in ratings:
        tmdb_id = item.get("tmdb_id")

        try:
            details = await tmdb_movie_details(int(tmdb_id))

            detailed_ratings.append({
                "rating_id": item.get("id"),
                "tmdb_id": tmdb_id,
                "rating": item.get("rating"),
                "created_at": item.get("created_at"),
                "movie": {
                    "tmdb_id": details.tmdb_id,
                    "title": details.title,
                    "poster_url": details.poster_url,
                    "release_date": details.release_date,
                    "vote_average": details.vote_average if hasattr(details, "vote_average") else None,
                }
            })

        except Exception:
            # Fallback if TMDB fails for any movie
            detailed_ratings.append({
                "rating_id": item.get("id"),
                "tmdb_id": tmdb_id,
                "rating": item.get("rating"),
                "created_at": item.get("created_at"),
                "movie": {
                    "tmdb_id": tmdb_id,
                    "title": f"Movie ID {tmdb_id}",
                    "poster_url": None,
                    "release_date": None,
                    "vote_average": None,
                }
            })

    return {
        "user": current_user["username"],
        "ratings": detailed_ratings
    }

@app.get("/for-you")
async def for_you(
    genres: Optional[List[str]] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Personalized recommendations based on:
    - user's high-rated movies
    - TF-IDF similarity when movie exists in local dataset
    - TMDB genre fallback when movie is not in local dataset
    - optional genre preference filter
    """

    # 1. Get all ratings for this user
    all_ratings_response = (
        supabase
        .table("ratings")
        .select("*")
        .eq("user_id", current_user["user_id"])
        .execute()
    )

    all_user_ratings = all_ratings_response.data or []

    if not all_user_ratings:
        return {
            "user": current_user["username"],
            "selected_genres": genres or [],
            "message": "Rate your first movie to unlock personalized recommendations.",
            "recommendations": []
        }

    already_rated_tmdb_ids = {
        int(r["tmdb_id"])
        for r in all_user_ratings
        if r.get("tmdb_id") is not None
    }

    # 2. Use only 4 or 5 star ratings as recommendation seeds
    liked_ratings = [
        r for r in all_user_ratings
        if int(r.get("rating", 0)) >= 4
    ]

    if not liked_ratings:
        return {
            "user": current_user["username"],
            "selected_genres": genres or [],
            "message": "Rate at least one movie 4 or 5 stars to unlock personalized recommendations.",
            "recommendations": []
        }

    selected_genres = [g.lower() for g in (genres or [])]

    all_recs = []
    seen_tmdb_ids = set()
    seen_titles = set()

    # 3. Generate recommendations from up to 5 liked movies
    for item in liked_ratings[:5]:
        liked_tmdb_id = item.get("tmdb_id")

        liked_details = None
        liked_title = None

        # First try TMDB details
        try:
            liked_details = await tmdb_movie_details(int(liked_tmdb_id))
            liked_title = liked_details.title
        except Exception:
            # If TMDB is unavailable, fall back to local dataset title
            liked_title = get_local_title_by_tmdb_id(int(liked_tmdb_id))

        if not liked_title:
            continue

        # ==================================================
        # PRIMARY PATH: TF-IDF recommendations
        # ==================================================
        tfidf_added_count = 0

        try:
            recs = tfidf_recommend_titles(liked_title, top_n=15)

            for rec_title, score in recs:
                # Skip weak recommendations
                if score < 0.17:
                    continue
                normalized_title = _norm_title(rec_title)


                if normalized_title in seen_titles:
                    continue


                local_genres = get_local_genres_by_title(rec_title)
                local_genres_lower = [g.lower() for g in local_genres]

                # Apply genre preference filter if selected
                if selected_genres:
                    if not any(g in local_genres_lower for g in selected_genres):
                        continue


                card = await attach_tmdb_card_by_title(rec_title)

                if not card:
                    continue


                if not card.poster_url:
                    continue


                if card.vote_average is not None and card.vote_average == 0:
                    continue


                if int(card.tmdb_id) in already_rated_tmdb_ids:
                    continue


                if int(card.tmdb_id) in seen_tmdb_ids:
                    continue

                seen_titles.add(normalized_title)
                seen_tmdb_ids.add(int(card.tmdb_id))
                tfidf_added_count += 1

                all_recs.append({
                    "source": "tfidf",
                    "because_you_liked": liked_title,
                    "title": rec_title,
                    "score": score,
                    "local_genres": local_genres,
                    "tmdb": card.dict()
                })

        except Exception:
            # Movie probably not found in local df.pkl
            tfidf_added_count = 0

                # ==================================================
        # FALLBACK PATH: TMDB genre recommendations
        # Used when TF-IDF produces no useful result.
        #
        # Strict genre rule:
        # - If user selected genres, fallback must use selected genres.
        # - If no genre selected, fallback uses liked movie's first genre.
        # ==================================================
        if tfidf_added_count == 0:
            try:
                fallback_genre_ids = []

                # User-selected genre filter has highest priority
                if genres:
                    for genre_name in genres:
                        genre_id = TMDB_GENRE_MAP.get(genre_name)
                        if genre_id:
                            fallback_genre_ids.append(genre_id)

                # If no selected genre is available, use liked movie's first TMDB genre
                if not fallback_genre_ids:
                    if not liked_details or not liked_details.genres:
                        continue
                    fallback_genre_ids.append(liked_details.genres[0]["id"])

                for fallback_genre_id in fallback_genre_ids:
                    fallback_data = await tmdb_get(
                        "/discover/movie",
                        {
                            "with_genres": fallback_genre_id,
                            "language": "en-US",
                            "sort_by": "popularity.desc",
                            "page": 1,
                        },
                    )

                    fallback_cards = await tmdb_cards_from_results(
                        fallback_data.get("results", []),
                        limit=15
                    )

                    for card in fallback_cards:
                        if not card:
                            continue

                        if not card.poster_url:
                            continue

                        if card.vote_average is not None and card.vote_average == 0:
                            continue

                        if int(card.tmdb_id) in already_rated_tmdb_ids:
                            continue

                        if int(card.tmdb_id) in seen_tmdb_ids:
                            continue

                        seen_tmdb_ids.add(int(card.tmdb_id))
                        seen_titles.add(_norm_title(card.title))

                        # If selected genres exist, record them as fallback genres.
                        # This keeps frontend/debug response understandable.
                        fallback_genres = genres or []

                        all_recs.append({
                            "source": "tmdb_genre_fallback",
                            "because_you_liked": liked_title,
                            "title": card.title,
                            "score": None,
                            "local_genres": fallback_genres,
                            "tmdb": card.dict()
                        })

            except Exception:
                continue

    if not all_recs:
        return {
            "user": current_user["username"],
            "selected_genres": genres or [],
            "message": "No personalized recommendations found yet. Try rating a few more movies 4 or 5 stars.",
            "recommendations": []
        }

    return {
        "user": current_user["username"],
        "selected_genres": genres or [],
        "recommendations": all_recs[:30]
    }

@app.get("/test-db")
def test_db():
    return {"message": "Supabase connected successfully"}
