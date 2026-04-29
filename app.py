import requests
import streamlit as st

# =============================
# CONFIG
# =============================
API_BASE = "http://127.0.0.1:8000"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

GENRE_OPTIONS = [
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Drama",
    "Family",
    "Fantasy",
    "Horror",
    "Mystery",
    "Romance",
    "Science",
    "Thriller",
]

st.set_page_config(page_title="Movie Recommender", page_icon="🎬", layout="wide")

# =============================
# STYLES (minimal modern)
# =============================
st.markdown(
    """
<style>
.block-container { padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px; }
.small-muted { color:#6b7280; font-size: 0.92rem; }
.movie-title { font-size: 0.9rem; line-height: 1.15rem; height: 2.3rem; overflow: hidden; }
.card { border: 1px solid rgba(0,0,0,0.08); border-radius: 16px; padding: 14px; background: rgba(255,255,255,0.7); }
</style>
""",
    unsafe_allow_html=True,
)

# =============================
# STATE + ROUTING (single-file pages)
# =============================
if "view" not in st.session_state:
    st.session_state.view = "home"  # home | details
if "selected_tmdb_id" not in st.session_state:
    st.session_state.selected_tmdb_id = None

# =============================
# AUTH SESSION STATE
# =============================
if "token" not in st.session_state:
    st.session_state.token = None

if "username" not in st.session_state:
    st.session_state.username = None

if "is_logged_in" not in st.session_state:
    st.session_state.is_logged_in = False

if "for_you_page" not in st.session_state:
    st.session_state.for_you_page = 1

qp_view = st.query_params.get("view")
qp_id = st.query_params.get("id")
if qp_view in ("home", "details"):
    st.session_state.view = qp_view
if qp_id:
    try:
        st.session_state.selected_tmdb_id = int(qp_id)
        st.session_state.view = "details"
    except:
        pass


def goto_home():
    st.session_state.view = "home"
    st.query_params["view"] = "home"
    if "id" in st.query_params:
        del st.query_params["id"]
    st.rerun()


def goto_details(tmdb_id: int):
    st.session_state.view = "details"
    st.session_state.selected_tmdb_id = int(tmdb_id)
    st.query_params["view"] = "details"
    st.query_params["id"] = str(int(tmdb_id))
    st.rerun()


# =============================
# API HELPERS
# =============================
@st.cache_data(ttl=30)  # short cache for autocomplete
def api_get_json(path: str, params: dict | None = None):
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=120)
        if r.status_code >= 400:
            return None, f"HTTP {r.status_code}: {r.text[:300]}"
        return r.json(), None
    except Exception as e:
        return None, f"Request failed: {e}"

def api_post_json(path: str, payload: dict, token: str | None = None):
    try:
        headers = {}

        if token:
            headers["Authorization"] = f"Bearer {token}"

        r = requests.post(
            f"{API_BASE}{path}",
            json=payload,
            headers=headers,
            timeout=60
        )

        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            return None, f"HTTP {r.status_code}: {detail}"

        return r.json(), None

    except Exception as e:
        return None, f"Request failed: {e}"

def api_get_json_auth(path: str, params: dict | None = None, token: str | None = None):
    try:
        headers = {}

        if token:
            headers["Authorization"] = f"Bearer {token}"

        r = requests.get(
            f"{API_BASE}{path}",
            params=params,
            headers=headers,
            timeout=120,
        )

        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            return None, f"HTTP {r.status_code}: {detail}"

        return r.json(), None

    except Exception as e:
        return None, f"Request failed: {e}"

def show_auth_screen():
    st.title("🎬 PersonaFlix Login")
    st.markdown(
        "<div class='small-muted'>Login or create an account to get personalized movie recommendations.</div>",
        unsafe_allow_html=True,
    )

    st.divider()

    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        st.subheader("Login")

        login_username = st.text_input("Username", key="login_username")
        login_password = st.text_input("Password", type="password", key="login_password")

        if st.button("Login", key="login_button"):
            if not login_username.strip() or not login_password.strip():
                st.warning("Please enter username and password.")
            else:
                data, err = api_post_json(
                    "/login",
                    {
                        "username": login_username.strip(),
                        "password": login_password.strip(),
                    },
                )

                if err:
                    st.error(f"Login failed: {err}")
                else:
                    st.session_state.token = data.get("access_token")
                    st.session_state.username = data.get("username", login_username)
                    st.session_state.is_logged_in = True

                    st.success("Login successful!")
                    st.rerun()

    with register_tab:
        st.subheader("Create Account")

        reg_username = st.text_input("Choose Username", key="reg_username")
        reg_password = st.text_input("Choose Password", type="password", key="reg_password")

        if st.button("Register", key="register_button"):
            if not reg_username.strip() or not reg_password.strip():
                st.warning("Please enter username and password.")
            elif len(reg_password.strip()) < 4:
                st.warning("Password should be at least 4 characters.")
            else:
                data, err = api_post_json(
                    "/register",
                    {
                        "username": reg_username.strip(),
                        "password": reg_password.strip(),
                    },
                )

                if err:
                    st.error(f"Registration failed: {err}")
                else:
                    st.success("Account created successfully. Please login now.")

def poster_grid(cards, cols=6, key_prefix="grid"):
    if not cards:
        st.info("No movies to show.")
        return

    rows = (len(cards) + cols - 1) // cols
    idx = 0
    for r in range(rows):
        colset = st.columns(cols)
        for c in range(cols):
            if idx >= len(cards):
                break
            m = cards[idx]
            idx += 1

            tmdb_id = m.get("tmdb_id")
            title = m.get("title", "Untitled")
            poster = m.get("poster_url")

            with colset[c]:
                if poster:
                    st.image(poster, use_column_width=True)
                else:
                    st.write("🖼️ No poster")

                if st.button("Open", key=f"{key_prefix}_{r}_{c}_{idx}_{tmdb_id}"):
                    if tmdb_id:
                        goto_details(tmdb_id)

                st.markdown(
                    f"<div class='movie-title'>{title}</div>", unsafe_allow_html=True
                )


def to_cards_from_tfidf_items(tfidf_items):
    cards = []
    for x in tfidf_items or []:
        tmdb = x.get("tmdb") or {}
        if tmdb.get("tmdb_id"):
            cards.append(
                {
                    "tmdb_id": tmdb["tmdb_id"],
                    "title": tmdb.get("title") or x.get("title") or "Untitled",
                    "poster_url": tmdb.get("poster_url"),
                }
            )
    return cards

def to_cards_from_for_you_items(items):
    cards = []

    for item in items or []:
        tmdb = item.get("tmdb") or {}

        if tmdb.get("tmdb_id"):
            cards.append(
                {
                    "tmdb_id": tmdb.get("tmdb_id"),
                    "title": tmdb.get("title") or item.get("title") or "Untitled",
                    "poster_url": tmdb.get("poster_url"),
                    "because_you_liked": item.get("because_you_liked"),
                    "local_genres": item.get("local_genres", []),
                }
            )

    return cards


# =============================
# IMPORTANT: Robust TMDB search parsing
# Supports BOTH API shapes:
# 1) raw TMDB: {"results":[{id,title,poster_path,...}]}
# 2) list cards: [{tmdb_id,title,poster_url,...}]
# =============================
def parse_tmdb_search_to_cards(data, keyword: str, limit: int = 24):
    """
    Returns:
      suggestions: list[(label, tmdb_id)]
      cards: list[{tmdb_id,title,poster_url}]
    """
    keyword_l = keyword.strip().lower()

    # A) If API returns dict with 'results'
    if isinstance(data, dict) and "results" in data:
        raw = data.get("results") or []
        raw_items = []
        for m in raw:
            title = (m.get("title") or "").strip()
            tmdb_id = m.get("id")
            poster_path = m.get("poster_path")
            if not title or not tmdb_id:
                continue
            raw_items.append(
                {
                    "tmdb_id": int(tmdb_id),
                    "title": title,
                    "poster_url": f"{TMDB_IMG}{poster_path}" if poster_path else None,
                    "release_date": m.get("release_date", ""),
                }
            )

    # B) If API returns already as list
    elif isinstance(data, list):
        raw_items = []
        for m in data:
            # might be {tmdb_id,title,poster_url}
            tmdb_id = m.get("tmdb_id") or m.get("id")
            title = (m.get("title") or "").strip()
            poster_url = m.get("poster_url")
            if not title or not tmdb_id:
                continue
            raw_items.append(
                {
                    "tmdb_id": int(tmdb_id),
                    "title": title,
                    "poster_url": poster_url,
                    "release_date": m.get("release_date", ""),
                }
            )
    else:
        return [], []

    # Word-match filtering (contains)
    matched = [x for x in raw_items if keyword_l in x["title"].lower()]

    # If nothing matched, fallback to raw list (so never blank)
    final_list = matched if matched else raw_items

    # Suggestions = top 10 labels
    suggestions = []
    for x in final_list[:10]:
        year = (x.get("release_date") or "")[:4]
        label = f"{x['title']} ({year})" if year else x["title"]
        suggestions.append((label, x["tmdb_id"]))

    # Cards = top N
    cards = [
        {"tmdb_id": x["tmdb_id"], "title": x["title"], "poster_url": x["poster_url"]}
        for x in final_list[:limit]
    ]
    return suggestions, cards


# =============================
# AUTH GUARD
# =============================
if not st.session_state.is_logged_in:
    show_auth_screen()
    st.stop()

# =============================
# SIDEBAR (clean)
# =============================
with st.sidebar:
    st.markdown("## 🎬 PersonaFlix")

    # =============================
    # ACCOUNT SECTION
    # =============================
    st.markdown("### 👤 Account")
    st.success(f"Logged in as: {st.session_state.username}")

    if st.button("🚪 Logout"):
        st.session_state.token = None
        st.session_state.username = None
        st.session_state.is_logged_in = False
        st.session_state.view = "home"
        st.session_state.selected_tmdb_id = None
        st.session_state.for_you_page = 1
        st.rerun()

    st.markdown("---")

    # =============================
    # NAVIGATION SECTION
    # =============================
    st.markdown("### 🧭 Navigation")

    if st.button("🏠 Home"):
        st.session_state.for_you_page = 1
        goto_home()

    st.markdown("---")

    # =============================
    # HOME FEED SECTION
    # =============================
    st.markdown("### 🏠 Home Feed")

    home_category = st.selectbox(
        "Category",
        ["trending", "popular", "top_rated", "now_playing", "upcoming"],
        index=0,
    )

    grid_cols = st.slider("Grid columns", 4, 8, 6)

    st.markdown("---")

    # =============================
    # TASTE CONTROLS SECTION
    # =============================
    st.markdown("### 🎭 Taste Controls")

    selected_genres = st.multiselect(
        "Preferred genres",
        GENRE_OPTIONS,
        default=[],
        help="Optional: refine your personalized recommendations by genre."
    )

    show_for_you = st.toggle(
        "Show For You recommendations",
        value=True,
        help="Turn this off if you want a cleaner home page."
    )

# =============================
# HEADER
# =============================
st.title("🎬 Movie Recommender")
st.markdown(
    "<div class='small-muted'>Type keyword → dropdown suggestions + matching results → open → details + recommendations</div>",
    unsafe_allow_html=True,
)
st.divider()

# ==========================================================
# VIEW: HOME
# ==========================================================
if st.session_state.view == "home":
    typed = st.text_input(
        "Search by movie title (keyword)", placeholder="Type: avenger, batman, love..."
    )

    st.divider()

    # SEARCH MODE (Autocomplete + word-match results)
    if typed.strip():
        if len(typed.strip()) < 2:
            st.caption("Type at least 2 characters for suggestions.")
        else:
            data, err = api_get_json("/tmdb/search", params={"query": typed.strip()})

            if err or data is None:
                st.error(f"Search failed: {err}")
            else:
                suggestions, cards = parse_tmdb_search_to_cards(
                    data, typed.strip(), limit=24
                )

                # Dropdown
                if suggestions:
                    labels = ["-- Select a movie --"] + [s[0] for s in suggestions]
                    selected = st.selectbox("Suggestions", labels, index=0)

                    if selected != "-- Select a movie --":
                        # map label -> id
                        label_to_id = {s[0]: s[1] for s in suggestions}
                        goto_details(label_to_id[selected])
                else:
                    st.info("No suggestions found. Try another keyword.")

                st.markdown("### Results")
                poster_grid(cards, cols=grid_cols, key_prefix="search_results")

        st.stop()
    
    # =============================
    # PERSONALIZED FOR YOU SECTION
    # =============================
    if show_for_you:
        st.markdown(f"### 🎯 For You, {st.session_state.username}")

        for_you_params = {}

        if selected_genres:
            for_you_params["genres"] = selected_genres

        for_you_data, for_you_err = api_get_json_auth(
            "/for-you",
            params=for_you_params,
            token=st.session_state.token,
        )

        if for_you_err:
            st.info("Rate a few movies to unlock personalized recommendations.")

        elif for_you_data and for_you_data.get("recommendations"):
            all_for_you_cards = to_cards_from_for_you_items(
                for_you_data.get("recommendations")
            )

            if selected_genres:
                st.caption(f"Filtered by: {', '.join(selected_genres)}")

            # Netflix-style pagination setup
            FOR_YOU_PAGE_SIZE = 12
            total_items = len(all_for_you_cards)
            total_pages = max(1, (total_items + FOR_YOU_PAGE_SIZE - 1) // FOR_YOU_PAGE_SIZE)

            # Safety: if current page becomes invalid after genre filter change
            if st.session_state.for_you_page > total_pages:
                st.session_state.for_you_page = 1

            start_idx = (st.session_state.for_you_page - 1) * FOR_YOU_PAGE_SIZE
            end_idx = start_idx + FOR_YOU_PAGE_SIZE

            current_page_cards = all_for_you_cards[start_idx:end_idx]

            poster_grid(
                current_page_cards,
                cols=grid_cols,
                key_prefix=f"for_you_page_{st.session_state.for_you_page}",
            )

            # Pagination controls
            st.markdown("")

            prev_col, page_col, next_col = st.columns([1, 2, 1])

            with prev_col:
                if st.button("⬅ Previous", disabled=st.session_state.for_you_page <= 1):
                    st.session_state.for_you_page -= 1
                    st.rerun()

            with page_col:
                st.markdown(
                    f"<div style='text-align:center; padding-top:0.5rem;'>Page {st.session_state.for_you_page} of {total_pages}</div>",
                    unsafe_allow_html=True
                )

            with next_col:
                if st.button("Next ➡", disabled=st.session_state.for_you_page >= total_pages):
                    st.session_state.for_you_page += 1
                    st.rerun()

        else:
            st.info(
                for_you_data.get("message", "Rate a few movies to unlock personalized recommendations.")
                if for_you_data else
                "Rate a few movies to unlock personalized recommendations."
            )

        st.divider()

    else:
        st.caption("🎯 For You recommendations are hidden. Enable them from the sidebar.")
        st.divider()

    # =============================
    # HOME FEED MODE
    # =============================
    st.markdown(f"### 🏠 Home — {home_category.replace('_',' ').title()}")

    home_cards, err = api_get_json(
        "/home", params={"category": home_category, "limit": 24}
    )
    if err or not home_cards:
        st.error(f"Home feed failed: {err or 'Unknown error'}")
        st.stop()

    poster_grid(home_cards, cols=grid_cols, key_prefix="home_feed")

# ==========================================================
# VIEW: DETAILS
# ==========================================================
elif st.session_state.view == "details":
    tmdb_id = st.session_state.selected_tmdb_id
    if not tmdb_id:
        st.warning("No movie selected.")
        if st.button("← Back to Home"):
            goto_home()
        st.stop()

    # Top bar
    a, b = st.columns([3, 1])
    with a:
        st.markdown("### 📄 Movie Details")
    with b:
        if st.button("← Back to Home"):
            goto_home()

    # Details (your FastAPI safe route)
    data, err = api_get_json(f"/movie/id/{tmdb_id}")
    if err or not data:
        st.error(f"Could not load details: {err or 'Unknown error'}")
        st.stop()

    # Layout: Poster LEFT, Details RIGHT
    left, right = st.columns([1, 2.4], gap="large")

    with left:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        if data.get("poster_url"):
            st.image(data["poster_url"], use_column_width=True)
        else:
            st.write("🖼️ No poster")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown(f"## {data.get('title','')}")
        release = data.get("release_date") or "-"
        genres = ", ".join([g["name"] for g in data.get("genres", [])]) or "-"

        st.markdown(
            f"<div class='small-muted'>Release: {release}</div>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<div class='small-muted'>Genres: {genres}</div>",
            unsafe_allow_html=True
        )

        st.markdown("---")
        st.markdown("### Overview")
        st.write(data.get("overview") or "No overview available.")

        st.markdown("---")
        st.markdown("### ⭐ Rate this movie")

        user_rating = st.slider(
            "Select your rating",
            min_value=1,
            max_value=5,
            value=3,
            key=f"rating_slider_{tmdb_id}"
        )

        if st.button("Save Rating", key=f"save_rating_{tmdb_id}"):
            if not st.session_state.token:
                st.error("Please login first.")
            elif not tmdb_id or int(tmdb_id) == 0:
                st.warning("Cannot rate this movie because TMDB ID is missing.")
            else:
                rate_data, rate_err = api_post_json(
                    "/rate",
                    {
                        "tmdb_id": int(tmdb_id),
                        "rating": int(user_rating),
                    },
                    token=st.session_state.token,
                )

                if rate_err:
                    st.error(f"Rating failed: {rate_err}")
                else:
                    st.success("Rating saved successfully!")

        st.markdown("</div>", unsafe_allow_html=True)

    if data.get("backdrop_url"):
        st.markdown("#### Backdrop")
        st.image(data["backdrop_url"], use_column_width=True)

    st.divider()
    st.markdown("### ✅ Recommendations")

    # Recommendations (TF-IDF + Genre) via your bundle endpoint
    title = (data.get("title") or "").strip()
    if title:
        bundle, err2 = api_get_json(
            "/movie/search",
            params={"query": title, "tfidf_top_n": 12, "genre_limit": 12},
        )

        if not err2 and bundle:
            st.markdown("#### 🔎 Similar Movies (TF-IDF)")
            poster_grid(
                to_cards_from_tfidf_items(bundle.get("tfidf_recommendations")),
                cols=grid_cols,
                key_prefix="details_tfidf",
            )

            st.markdown("#### 🎭 More Like This (Genre)")
            poster_grid(
                bundle.get("genre_recommendations", []),
                cols=grid_cols,
                key_prefix="details_genre",
            )
        else:
            st.info("Showing Genre recommendations (fallback).")
            genre_only, err3 = api_get_json(
                "/recommend/genre", params={"tmdb_id": tmdb_id, "limit": 18}
            )
            if not err3 and genre_only:
                poster_grid(
                    genre_only, cols=grid_cols, key_prefix="details_genre_fallback"
                )
            else:
                st.warning("No recommendations available right now.")
    else:
        st.warning("No title available to compute recommendations.")
