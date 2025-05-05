from soundcloud import SoundCloud, MiniTrack
import json
from pathlib import Path
import datetime
import subprocess
import sys
from bsky_utils import *
import requests
import bs4
import demjson3
from yt_dlp import YoutubeDL

class BandcampJSON:
    def __init__(self, body, debugging: bool = False):
        self.body = body
        self.json_data = []

    def generate(self):
        self.get_pagedata()
        self.get_js()
        return self.json_data

    def get_pagedata(self):
        pagedata = self.body.find('div', {'id': 'pagedata'})['data-blob']
        self.json_data.append(pagedata)

    def get_js(self):
        embedded_scripts_raw = [self.body.find("script", {"type": "application/ld+json"}).string]
        for script in self.body.find_all('script'):
            try:
                album_info = script['data-tralbum']
                embedded_scripts_raw.append(album_info)
            except Exception:
                continue
        for script in embedded_scripts_raw:
            js_data = self.js_to_json(script)
            self.json_data.append(js_data)

    def js_to_json(self, js_data):
        decoded_js = demjson3.decode(js_data)
        return demjson3.encode(decoded_js)

def bc_playlist(playlist_url):
    session = requests.Session()
    response = session.get(playlist_url)

    if not response.ok:
        print(f"Status code: {response.status_code}", )
        print(f"The Album/Track requested does not exist at: {playlist_url}")
        return None, None

    try:
        soup = bs4.BeautifulSoup(response.text, "lxml")
    except bs4.FeatureNotFound:
        soup = bs4.BeautifulSoup(response.text, "html.parser")

    bandcamp_json = BandcampJson(soup, False).generate()
    page_json = {}
    for entry in bandcamp_json:
        page_json = {**page_json, **json.loads(entry)}

    if not (tracklist := traverse(page_json, ['track', 'itemListElement'])):
        print("No tracks found in the playlist.")
        return None, None

    thumbnail_url = page_json.get('image')

    playlist_record = {
        "$type": "dev.dreary.tunes.playlist",
        "thumbnail": thumbnail_url,
        "name": page_json.get('name'),
        "description": page_json.get('description'),
        "createdAt": generate_timestamp(),
        "reference": {
            "source": "Bandcamp",
            "link": page_json.get('url'),
            "id": page_json.get('id')
        }
    }

    uploader_info = {
        "name": traverse(page_json, ['artist'], ['byArtist', 'name'], ['publisher', 'name']),
        "id": traverse(page_json, ['current', ['band_id', 'selling_band_id']], ['publisher', 'additionalProperty', {'name': 'band_id'}, 'value']),
        "url": traverse(page_json, ['byArtist', '@id'], ['publisher', '@id']),
    }
    trackinfos = page_json['trackinfo']

    tracks = []
    for track in tracklist:
        track = track['item']
        track_id = traverse(track, ['additionalProperty', {'name': 'track_id'}, 'value'])
        trackinfo = traverse(trackinfos, [{'id': track_id}], [{'track_id': track_id}])
        record = {
            "$type": "dev.dreary.tunes.track",
            "title": track.get('name') or trackinfo.get('title'),
            "uploader": uploader_info,
            "thumbnail": thumbnail_url,
            "duration": round(trackinfo['duration']),
            "lyrics": traverse(track, ['recordingOf', 'lyrics', 'text']),
            "url": traverse(track, ['@id'], ['mainEntityOfPage']),
            "id": traverse(track, ['additionalProperty', {'name': 'track_id'}, 'value']),
            "source": "Bandcamp",
            "createdAt": generate_timestamp(),
        }
        tracks.append(record)
    return playlist_record, tracks

def sc_playlist(playlist_url):
    client = SoundCloud(client_id=None)
    playlist = client.resolve(playlist_url)

    if not playlist.tracks:
        print("No tracks found in the playlist.")
        return None, None

    playlist_record = {
        "$type": "dev.dreary.tunes.playlist",
        "thumbnail": playlist.artwork_url, # not working as expected, https://soundcloud.com/syzymusic2/sets/mgztop0qnt1x
        "name": playlist.title,
        "description": playlist.description,
        "createdAt": generate_timestamp(),
        "reference": {
            "source": "SoundCloud",
            "link": playlist.permalink_url,
            "id": playlist.id
        }
    }

    tracks = []
    for track in playlist.tracks:
        if isinstance(track, MiniTrack):
            if playlist.secret_token:
                track = client.get_tracks([track.id], playlist.id, playlist.secret_token)[0]
            else:
                track = client.get_track(track.id)

        record = {
            "$type": "dev.dreary.tunes.track",
            "title": track.title,
            "uploader": {
                "name": track.user.username,
                "id": str(track.user.id),
                "url": track.user.permalink_url,
            },
            "thumbnail": track.artwork_url, # not working as expected, https://soundcloud.com/syzymusic2/sets/mgztop0qnt1x
            "duration": track.duration // 1000,
            "description": track.description,
            "url": track.permalink_url,
            "id": str(track.id),
            "source": "SoundCloud",
            "createdAt": generate_timestamp(),
        }
        tracks.append(record)

    return playlist_record, tracks

def yt_playlist(playlist_url):
    print("Retrieving YouTube playlist data (yt-dlp)...")

    ydl_opts = {
        'quiet': True,
        'extract_flat': False,
        'dump_single_json': True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        try:
            playlist = ydl.extract_info(playlist_url, download=False)
            print("Playlist data retrieved successfully")
        except Exception as e:
            print(f"Failed to retrieve playlist: {e}")
            return None, None

    if not playlist.get('entries'):
        print("No tracks found in the playlist.")
        return None, None

    playlist_id = playlist.get('id')

    playlist_record = {
        "$type": "dev.dreary.tunes.playlist",
        "thumbnail": traverse(playlist, ['thumbnail'], ['thumbnails', -2, 'url']),
        "name": playlist.get('title'),
        "description": playlist.get('description'),
        "createdAt": generate_timestamp(),
        "reference": {
            "source": "YouTube",
            "link": f'https://www.youtube.com/playlist?list={playlist_id}' if playlist_id else None,
            "id": playlist_id
        }
    }

    tracks = []
    for track in playlist.get('entries'):
        if not track:
            continue
        tracks.append({
            "$type": "dev.dreary.tunes.track",
            "title": track.get('title'),
            "uploader": {
                "name": track.get('uploader'),
                "id": track.get('channel_id'),
                "url": track.get('channel_url'),
            },
            "thumbnail": track.get('thumbnail'),
            "duration": track.get('duration'),
            "description": track.get('description'),
            "url": track.get('webpage_url'),
            "id": track.get('id'),
            "source": "YouTube",
            "createdAt": generate_timestamp(),
        })

    return playlist_record, tracks

def process_playlist(url):
    hostname = url.split('/')[2]
    if 'soundcloud' in hostname:
        return sc_playlist(url)
    if 'bandcamp' in hostname:
        return bc_playlist(url)
    elif 'youtu' in hostname:
        return yt_playlist(url)
    else:
        print("Invalid URL")
        return None, None

def find_or_create_playlist_uri(playlist_record, did, session, service):
    if not playlist_record:
        return None

    print("Searching for existing playlist record matches...")
    existing_playlist_records = list_records(did, service, "dev.dreary.tunes.playlist")

    for p in existing_playlist_records:
        if not isinstance((ref := traverse(p, ['value', 'reference'])), dict):
            continue
        if all(k in ref and ref[k] == v for k, v in playlist_record['reference'].items()):
            playlist_uri = p['uri']
            print('No playlist record creation')
            break
    else:
        playlist_uri = create_record(session, service, playlist_record)
    return playlist_uri

def split_list(lst, chunk_size):
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def apply_writes_batch(session, service, records):
    if len(records) == 0:
        return []

    writes = []
    for record in records:
        if record['$type'].split('#')[0] == 'com.atproto.repo.applyWrites':
            # if the record is an applyWrites record, use it directly
            # this allows for non-creation writes
            writes.append(record)
        else:
            writes.append({
                "$type": "com.atproto.repo.applyWrites#create",
                "collection": record['$type'],
                "value": record,
            })

    uri = []
    split_batches = split_list(writes, 200)
    total_batches = len(split_batches)
    for i, batch in enumerate(split_batches):
        response = apply_writes(session, service, batch)
        uri.extend(traverse(response, ['results', 'uri'], get_all=True) or [])
        print(f"{i+1}/{total_batches} applyWrites complete")
    return uri

def filter_track_uri(playlist_item_records, playlist_uri, track_uris):
    filtered_items = traverse(playlist_item_records, ['value', {'playlist': playlist_uri, 'track': track_uris}, 'track'], get_all=True, default=[])
    return [t for t in track_uris if t not in filtered_items]

def main():
    with open('../../config.json') as f:
        config = json.load(f)
    handle = config.get('HANDLE')
    password = config.get('PASSWORD')
    if not (handle and password):
        print('Enter credentials in config.json')
        return

    did = resolve_handle(handle)
    service = get_service_endpoint(did)
    session = get_session(did, password, service)

    if len(sys.argv) < 2:
        playlist_url = input('Input a URL: ')
        if playlist_url == '':
            return
    else:
        playlist_url = sys.argv[1]

    playlist_record, tracks = process_playlist(playlist_url)
    if not playlist_record:
        return

    playlist_uri = find_or_create_playlist_uri(playlist_record, did, session, service)
    if not playlist_uri:
        return

    print("Retrieving existing track records...")
    track_records = list_records(did, service, "dev.dreary.tunes.track")

    writes = []
    track_uris = []
    track_record_url_map = {url: track["uri"] for track in track_records if (url := traverse(track, ['value', 'url']))}
    for track in tracks:
        if (track_uri := track_record_url_map.get(track.get('url'))):
            track_uris.append(track_uri)
        else:
            writes.append(track)

    if writes:
        track_uris.extend(apply_writes_batch(session, service, writes))
        print("Track applyWrites complete")
    else:
        print("No track record creation required")

    print("Retrieving existing playlistitem records...")
    playlist_item_records = list_records(did, service, "dev.dreary.tunes.playlistitem")

    final_playlist_item = traverse(playlist_item_records, [{'value': {'playlist': playlist_uri, 'nodes': {'nextUri': None}}}])
    track_uris = filter_track_uri(playlist_item_records, playlist_uri, track_uris)
    last_index = len(track_uris) - 1
    writes = []
    for i, track_uri in enumerate(track_uris):

        previous_uri = None
        if final_playlist_item:
            previous_uri = final_playlist_item['uri']
            final_playlist_item = final_playlist_item['value']
            final_playlist_item['nodes']['nextUri'] = track_uri
            writes.append({
                "$type": "com.atproto.repo.applyWrites#update",
                "collection": "dev.dreary.tunes.playlistitem",
                "rkey": decompose_uri(previous_uri)[2],
                "value": final_playlist_item,
            })
            final_playlist_item = None
        else:
            previous_uri = track_uris[i-1] if i > 0 else None

        writes.append({
            "$type": "dev.dreary.tunes.playlistitem",
            "playlist": playlist_uri,
            "track": track_uri,
            "createdAt": generate_timestamp(),
            "nodes": {
                "previousUri": previous_uri,
                "nextUri": track_uris[i+1] if i < last_index else None
            }
        })

    if writes:
        apply_writes_batch(session, service, writes)
        print("playlistitem applyWrites complete")
    else:
        print("No playlistitem record creation required")

if __name__ == "__main__":
    main()
