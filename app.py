import os
import pathlib
from flask import Flask, redirect, session, request, render_template
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from google import genai


import os


client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print([m.name for m in client.models.list()])


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")


sp_oauth = SpotifyOAuth(
    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
    scope="user-top-read playlist-read-private playlist-modify-public playlist-modify-private"
)


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login")
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")

    if not code:
        return "Spotify did not return a code.", 400

    # Correct modern token exchange
    token_info = sp_oauth.get_access_token(code, as_dict=True)

    if not token_info or "access_token" not in token_info:
        return "Failed to authenticate with Spotify.", 400

    session["token_info"] = token_info
    return redirect("/dashboard")


@app.route("/dashboard")
def dashboard():
    token_info = session.get("token_info")
    if not token_info:
        return redirect("/")

    sp = Spotify(auth=token_info["access_token"])

    # Fetch Spotify data
    top_tracks = sp.current_user_top_tracks(limit=50, time_range="medium_term")["items"]
    top_artists = sp.current_user_top_artists(limit=30, time_range="medium_term")["items"]

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
        return {"error": "No data from Spotify"}, 400

    prompt = f"""
You are Spotiscan — an emotionally-aware, culturally intelligent musical psychologist
with sharp observational humor.

Your mission:
Give the user a personality roast based ENTIRELY on their music taste.

### 🔥 Roast (funny, accurate, not generic)
Make it specific to their artists, genres, and patterns.

### 🎧 Music Taste Score (0–10)
One short justification.

### 🧠 Psychological Breakdown
Interpret:
- Repeat rate = {data['repeat_rate']}
- Genre diversity = {data['genre_diversity']}
- Dominant genre = {data['dominant_genre']}

### 🎵 5 Niche Recommendations
Rules:
- Song – Artist format
- Only REAL songs
- No TikTok generic stuff
- Match the emotional energy, not popularity

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
You are a world-class playlist curator who ONLY returns real, high-quality songs.

Generate **40 songs** for the playlist theme: "{user_prompt}"

STRICT RULES:
- All songs MUST exist
- Artists MUST be correct
- Song choices MUST deeply match the vibe, mood, sub-genre, emotional tone, tempo
- NO TikTok-pop, NO generic radio songs unless the vibe explicitly requires it
- Prefer niche, aesthetic, cinematic, cult-classic, underrated gems

FORMAT:
Song Title - Artist
(One per line, no numbering, no commentary)
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
        description=f"AI playlist for vibe: {user_prompt}"
    )

    sp.user_playlist_add_tracks(user_id, playlist["id"], track_ids[:40])

    return {
        "playlist_url": playlist["external_urls"]["spotify"],
        "tracks_added": len(track_ids[:40])
    }



if __name__ == "__main__":
    app.run()
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "None"

 
