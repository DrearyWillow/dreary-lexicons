import base64
import json
import os
import sys
import webbrowser
from urllib.parse import urlparse

import requests
from bsky_utils import *
from dotenv import load_dotenv

def get_token():
    load_dotenv()
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    auth_bytes = f"{client_id}:{client_secret}".encode()
    auth_string = base64.b64encode(auth_bytes).decode()
    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        headers={
            "Authorization": f"Basic {auth_string}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )
    response.raise_for_status()
    return response.json()["access_token"]

def get_api(token, api):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(api, headers=headers)
    response.raise_for_status()
    return response.json()

def create_playlist_record(data, owners, thumbnail):
    return {
        "$type": "dev.dreary.tunes.playlist",
        "thumbnail": thumbnail,
        "name": data.get('name'),
        "owners": owners,
        "createdAt": generate_timestamp(),
        "reference": {
            "source": "Spotify",
            "link": traverse(data, ['external_urls', 'spotify']),
            "id": data.get('id')
        }
    }

def create_track_records(token, tracks, thumbnail):
    if not tracks.get('items'):
        print("No tracks provided.")
        return None

    records = [{
        "$type": "dev.dreary.tunes.track",
        "title": track.get('name'),
        "artists": [{
            "name": artist.get('name'),
            "id": artist.get('id'),
            "url": traverse(artist, ['external_urls', 'spotify']),
        } for artist in track.get('artists', [])],
        "thumbnail": thumbnail or traverse(track, ['album', 'images', 'url']),
        "duration": ms // 1000 if (ms := track.get('duration_ms')) else None,
        "url": traverse(track, ['external_urls', 'spotify']),
        "id": track.get('id'),
        "source": "Spotify",
        "createdAt": generate_timestamp(),
    } for track in tracks.get('items', [])]
    
    if url := tracks.get('next'):
        records.append(process_tracks(token, url, thumbnail))

    return records

def process_playlist(token, playlist_id):
    # https://open.spotify.com/playlist/2HuVbuhG6UwyM0Ygegghxc?pi=u-yOp1Xya2T8aX
    data = get_api(token, f"https://api.spotify.com/v1/playlists/{playlist_id}?limit=50")
    if not data:
        return None, None
    save_json(data)
    
    thumbnail = traverse(data, ['images', 'url'])
    owners = [{
        "name": traverse(data, ['owner', 'display_name']),
        "link": traverse(data, ['owner', 'external_urls', 'spotify']),
        "id": traverse(data, ['owner', 'id'])
    }]

    return (
        create_playlist_record(data, owners, thumbnail),
        create_track_records(token, {"items": traverse(data, ['tracks', 'items', 'track'], get_all=True)}, None)
    )

def process_tracks(token, url, thumbnail):
    return create_track_records(token, get_api(token, url), thumbnail)

def process_album(token, album_id):
    # https://open.spotify.com/album/5QJlwvAXmPBLymGvbqKzdQ
    album = get_api(token, f"https://api.spotify.com/v1/albums/{album_id}")
    if not album:
        return None
    
    thumbnail = traverse(album, ['images', 'url'])
    owners = [{
        "name": artist.get('name'),
        "id": artist.get('id'),
        "link": traverse(artist, ['external_urls', 'spotify']),
    } for artist in album.get('artists')]

    return (
        create_playlist_record(album, owners, thumbnail),
        create_track_records(token, album.get('tracks'), thumbnail)
    )

def process_track(token, track_id):
    # https://open.spotify.com/track/6hzwfFKrTabeUsW5SWti17
    track = get_api(token, f"https://api.spotify.com/v1/tracks/{track_id}")
    return create_track_records(token, {'items': [track]}, None)

def main():
    if len(sys.argv) < 2:
        print("Enter a URL")
        return
    link = sys.argv[1]

    parsed = None
    try:
        parsed = urlparse(link)
    except Exception as e:
        print(f"Bad url input: {e}")
        return
    if parsed.netloc != "open.spotify.com":
        print("URL is not a Spotify link")
        return

    token = get_token()

    parts = parsed.path.split("/")
    if parts[1] == "playlist":
        playlist, tracks = process_playlist(token, parts[2])
    elif parts[1] == "album":
        playlist, tracks = process_album(token, parts[2])
    elif parts[1] == "track":
        record = process_track(token, parts[2])
        # if not record: return
        # create_record(session, service, 'dev.dreary.tunes.track', record)
        return
    else:
        print(f"Link type not supported: {parts[1]}")
        return
    
    if not tracks:
        print("No tracks record returned.")
        return
    elif not playlist:
        print("No playlist record returned.")
        # apply_writes_create(tracks)
        return

    print_json(tracks)
    print("Here's where I pass on the logic to my existing tunes script")

if __name__ == "__main__":
    main()