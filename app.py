import os
from flask import Flask, redirect, session, request, render_template
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

sp_oauth = SpotifyOAuth(
    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI").strip(),
    scope="user-top-read playlist-read-private playlist-modify-public playlist-modify-private"
)

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/login")
def login():
    return redirect(sp_oauth.get_authorize_url())

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "No code returned from Spotify.", 400

    token_info = sp_oauth.get_access_token(code, as_dict=True)
    if not token_info or "access_token" not in token_info:
        return "Could not authenticate with Spotify.", 400

    session["token_info"] = token_info
    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    token_info = session.get("token_info")
    if not token_info:
        return redirect("/")

    sp = Spotify(auth=token_info["access_token"])

    top_tracks = sp.current_user_top_tracks(limit=50)["items"]
    top_artists = sp.current_user_top_artists(limit=30)["items"]

    genres = [g for artist in top_artists for g in artist.get("genres", [])]

    track_names = [f"{t['name']} - {t['artists'][0]['name']}" for t in top_tracks[:20]]
    artist_names = [a["name"] for a in top_artists[:20]]
    unique_genres = list(set(genres))

    repeat_rate = len(artist_names) / max(len(set(artist_names)), 1)
    genre_diversity = len(unique_genres) / max(len(genres), 1)
    dominant_genre = max(set(genres), key=genres.count) if genres else "unknown"

    summary = {
        "tracks": track_names,
        "artists": artist_names,
        "genres": unique_genres,
        "repeat_rate": round(repeat_rate, 2),
        "genre_diversity": round(genre_diversity, 2),
        "dominant_genre": dominant_genre
    }

    session["dashboard_data"] = summary
    return render_template("dashboard.html", summary=summary)

@app.route("/roast", methods=["POST"])
def roast():
    data = session.get("dashboard_data")
    if not data:
        return {"error": "No Spotify data"}, 400

    prompt = f"""
You are Spotiscan — a culturally fluent, emotionally-aware musical psychologist
with razor-sharp observational humor and deep understanding of music subcultures.

Analyze the user's music identity using ONLY the provided data.

### 🔥 Roast (2–4 lines)
Make it painfully accurate, funny, and specific to their artists, genres, and patterns.

### 🎧 Music Taste Score (0–10)
Give a brutally honest score with one short explanation.

### 🧠 Psychological Breakdown
Interpret:
- Repeat rate = {data['repeat_rate']}
- Genre diversity = {data['genre_diversity']}
- Dominant genre = {data['dominant_genre']}

Explain their emotional patterns, coping style, attachment vibes, and main-character energy.

### 🎵 5 Niche Recommendations
Rules:
- REAL songs only
- Format: Song – Artist
- No TikTok overplayed garbage unless it fits the vibe
- Prioritize underground, cinematic, indie, alternative, or cult-classic tracks

Tracks: {data['tracks']}
Artists: {data['artists']}
Genres: {data['genres']}
"""

    res = client.models.generate_content(
        model="models/gemini-2.5-flash",
        contents=prompt
    )

    return {"roast": res.text}

@app.route("/generate_playlist", methods=["POST"])
def generate_playlist():
    token_info = session.get("token_info")
    if not token_info:
        return {"error": "User not logged in"}, 401

    sp = Spotify(auth=token_info["access_token"])
    data = request.get_json()
    user_prompt = data.get("prompt")

    if not user_prompt:
        return {"error": "Prompt missing"}, 400

    ai_prompt = f"""
You are a world-class playlist curator with deep taste and zero tolerance for mid songs.

Generate **40 real, high-quality, vibe-accurate songs** for the theme: "{user_prompt}".

Your job:
- Understand the emotional tone, mood, tempo, and sub-genre
- Choose songs that FEEL like the vibe
- Avoid generic radio + TikTok unless perfect for the prompt
- Prefer cinematic, niche, cult-classic, global, indie, electronic, alternative, or aesthetic tracks

FORMAT (STRICT):
Song Title - Artist
One per line
No numbers
No quotes
No extra text
"""

    res = client.models.generate_content(
        model="models/gemini-2.5-flash",
        contents=ai_prompt
    )

    raw_list = res.text.strip().split("\n")
    songs = list(dict.fromkeys([s.strip() for s in raw_list if " - " in s]))

    track_ids = []
    for s in songs:
        try:
            r = sp.search(q=s, type="track", limit=1)
            if r["tracks"]["items"]:
                track_ids.append(r["tracks"]["items"][0]["id"])
        except:
            pass

    if not track_ids:
        return {"error": "No valid songs found"}, 400

    user_id = sp.current_user()["id"]
    playlist = sp.user_playlist_create(
        user_id,
        name=f"Spotiscan: {user_prompt}",
        public=True,
        description=f"AI-generated playlist for vibe: {user_prompt}"
    )

    sp.user_playlist_add_tracks(user_id, playlist["id"], track_ids[:40])

    return {
        "playlist_url": playlist["external_urls"]["spotify"],
        "tracks_added": len(track_ids[:40])
    }

if __name__ == "__main__":
    app.run()
