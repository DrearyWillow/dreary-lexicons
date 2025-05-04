import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv


def linkify(text, link=None, file=False):
    return f"\033]8;;{'file://' if file else ''}{link if link else text}\033\\{text}\033]8;;\033\\"

def safe_request(req_type, url, headers=None, params=None, data=None, json=None):
    try:
        if req_type.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params)
        elif req_type.upper() == 'POST':
            response = requests.post(url, headers=headers, data=data, json=json)
        else:
            return None
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        print(f"Request failed. Status code: {response.status_code}. Response: {response.text}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise
    return response.json()

def resolve_handle(handle):
    if handle.startswith("did:"):
        return handle
    if handle.startswith("@"):
        handle = handle[1:]
    if not handle:
        return None
    url = f'https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle={handle}'
    return (safe_request('get', url) or {}).get('did')

def get_session(username, password, service_endpoint):
    url = f'{service_endpoint}/xrpc/com.atproto.server.createSession'
    payload = {
        'identifier': username,
        'password': password,
    }
    return safe_request('post', url, json=payload)

def get_did_doc(did):
    if did.startswith('did:web:'):
        url = f'https://{did[8:]}/.well-known/did.json'
    else:
        url = f'https://plc.directory/{did}'
    return safe_request('get', url)

def get_service_endpoint(did):
    for service in (get_did_doc(did).get('service') or []):
        if service.get('type') == 'AtprotoPersonalDataServer':
            return service.get('serviceEndpoint')
    return None

def create_record(session, service_endpoint, collection, record):
    token = session.get('accessJwt')
    did = session.get('did')
    api = f"{service_endpoint}/xrpc/com.atproto.repo.createRecord"
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    payload = {
        "repo": did,
        "collection": collection,
        "record": record
    }
    payload = json.dumps(payload)
    response = safe_request('post', api, headers=headers, data=payload)
    return response.get('uri')

def upload_blob(session, service_endpoint, blob_location, mimetype):
    with open(blob_location, "rb") as f:
        blob_bytes = f.read()
    
    res = safe_request('post',
        f"{service_endpoint}/xrpc/com.atproto.repo.uploadBlob",
        headers={
            "Content-Type": mimetype,
            "Authorization": "Bearer " + session["accessJwt"],
        },
        data=blob_bytes,
    )
    return res.get("blob") if res else None

def apply_writes_create(session, service_endpoint, records):
    token = session.get('accessJwt')
    did = session.get('did')
    api = f"{service_endpoint}/xrpc/com.atproto.repo.applyWrites"
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    payload = json.dumps({
        "repo": did,
        "writes": [{
            "$type": "com.atproto.repo.applyWrites#create",
            "collection": record['$type'],
            "value": record,
        } for record in records]
    })
    return safe_request('post', api, headers=headers, data=payload)

def get_record(did, collection, rkey, service_endpoint):
    api = f"{service_endpoint}/xrpc/com.atproto.repo.getRecord"
    params = {
        'repo': did,
        'collection': collection,
        'rkey': rkey
    }
    return safe_request('get', api, params=params)

def decompose_uri(uri):
    parts = uri.replace("at://", "").split("/")
    if len(parts) > 3:
        raise ValueError(f"AT URI '{uri}' has too many segments.")
    elif len(parts) < 3:
        raise ValueError(f"AT URI '{uri}' does not have enough segments.")
    return (*parts,)

def generate_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def create_project_record(session, service, name):
    record = {
        "$type": "dev.dreary.renpy.project",
        "name": name,
        "createdAt": generate_timestamp(),
    }
    return create_record(session, service, record['$type'], record)

def name_prompt(name=None):
    # copied from renpy/launcher/game
    while True:
        if not name:
            name = input("Enter a project name: ")

        if ("[" in name) or ("{" in name):
            print("Project name may not contain the {{ or [[ characters.")
            name = None
            continue
        if ("\\" in name) or ("/" in name):
            print("Project name may not contain / or \\.")
            name = None
            continue

        try:
            name.encode("ascii")
        except Exception:
            print("Project name must consist of ASCII characters.")
            name = None
            continue

        return name

def draft_asset_record(session, service, root, fullpath, project_uri):
    # not exhaustive - really just to exclude undesirable compiled files
    # could use `import mimetypes.guess_type` and proceed by exclusion
    mimetypes = {
        '.mp3': 'audio/mpeg',
        '.png': 'image/png',
        '.ttf': 'font/ttf',
    }
    text_exts = ['.rpy']
    valid_exts = text_exts + list(mimetypes.keys())
    _, ext = os.path.splitext(fullpath)
    if ext not in valid_exts:
        return
    
    record = {
        "$type": "dev.dreary.renpy.asset",
        "path": os.path.relpath(fullpath, root),
        "project": project_uri,
        "createdAt": generate_timestamp()
    }

    if ext in text_exts:
        with open(fullpath, 'r') as f:
            contents = f.read()
        record['contents'] = contents
    else:
        blob = upload_blob(session, service, fullpath, mimetypes[ext])
        if not blob:
            print(f"Blob upload failed for {fullpath}. Canceling record creation.")
            return
        record['file'] = blob
    
    return record

def draft_asset_records(session, service, root, project_uri):
    records = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            fullpath = os.path.join(dirpath, filename)
            record = draft_asset_record(session, service, root, fullpath, project_uri)
            if record:
                records.append(record)
    return records

def apply_writes_batch(session, service, records):
    if len(records) == 0:
        print("No records to write.")
        return []
    split_batches = split_list(records, 200)
    total_batches = len(split_batches)
    for i, batch in enumerate(split_batches):
        apply_writes_create(session, service, batch)
        print(f"{i+1}/{total_batches} applyWrites complete")

def download_blob(service, did, cid, path):
    api = f'{service}/xrpc/com.atproto.sync.getBlob'
    params = {
        "did": did,
        "cid": cid
    }
    response = requests.get(api, params=params)
    response.raise_for_status()
    with open(path, 'wb') as file:
        file.write(response.content)

def list_records(service, did, nsid, filter_uri):
    api = f'{service}/xrpc/com.atproto.repo.listRecords'
    params = {
        'repo': did,
        'collection': nsid,
        'limit': 100,
    }
    while True:
        res = safe_request('get', api, params=params)
        filtered = [
            record for record in res.get('records', [])
            if record.get('value', {}).get('project') == filter_uri
        ]
        yield from filtered

        cursor = res.get('cursor')
        if not cursor:
            break
        params['cursor'] = cursor

def download_asset(service, did, dl_dir, record):
    uri = record.get('uri', '[invalid uri]')
    print(f"Downloading asset: {uri}")
    asset = record.get('value', {})
    if not (relpath := asset.get('path')):
        print(f"{uri} missing required field 'path'.")
        return
    fullpath = os.path.normpath(os.path.join(dl_dir, relpath))
    if not fullpath.startswith(os.path.abspath(dl_dir)):
        print(f"Rejected unsafe path: {relpath} from {uri}")
        return
    if os.path.isfile(fullpath):
        print(f"File already exists. Skipping redownload.")
        return
    os.makedirs(os.path.dirname(fullpath), exist_ok=True)
    if (file := asset.get('file')):
        cid = file.get('ref', {}).get('$link')
        download_blob(service, did, cid, fullpath)
    elif (contents := asset.get('contents')):
        with open(fullpath, 'w') as file:
            file.write(contents)
    else:
        print(f"{uri} has no data to download.")

def upload_renpy():
    # python atp-renpy.py upload [DIR] [NAME]
    root = sys.argv[2] if (len(sys.argv) >= 3) else input("Enter a Ren'Py game directory: ")
    if not os.path.isdir(root):
        print("Enter a valid directory.")
        return

    project_name = sys.argv[3] if (len(sys.argv) >= 4) else None
    project_name = name_prompt(project_name)
    if not project_name:
        print("No name provided. Quitting.")
        return

    load_dotenv()
    handle = os.getenv("HANDLE")
    password = os.getenv("PASSWORD")
    if not (handle or password):
        print("Credentials ('HANDLE' and 'PASSWORD') not defined in .env")
    if not handle:
        handle = input("Enter handle: ")
    if not handle:
        return
    if not password:
        password = input("Enter password: ")
    if not password:
        return

    did = resolve_handle(handle)
    if not did:
        print("Unable to resolve handle.")
        return
    service = get_service_endpoint(did)
    if not service:
        print("Unable to retrieve service endpoint.")
        return
    session = get_session(did, password, service)
    if not session:
        print("Invalid credentials.")
        return

    project_uri = create_project_record(session, service, project_name)
    if not project_uri:
        print("Project record creation failed.")
        return
    print(f"Project record created: https://pdsls.dev/{project_uri}")

    records = draft_asset_records(session, service, root, project_uri)
    apply_writes_batch(session, service, records)
    print(f"Writes applied. https://pdsls.dev/at://{did}/dev.dreary.renpy.asset")

def download_renpy():
    # python atp-renpy.py download [DOWNLOAD DIR] [PROJECT AT-URI]
    dl_dir = sys.argv[2] if (len(sys.argv) >= 3) else input("Enter a download directory: ")
    if not os.path.isdir(dl_dir):
        print("Enter a valid directory.")
        return

    project_uri = sys.argv[3] if (len(sys.argv) >= 4) else input("Enter a project AT-URI: ")
    if not project_uri.startswith("at://"):
        print("AT-URI not provided.")
        return
    
    did, nsid, rkey = decompose_uri(project_uri)
    service = get_service_endpoint(did)
    if not service:
        print("Unable to resolve service endpoint.")
        return
    project_record = get_record(did, nsid, rkey, service)
    if not project_record:
        print("No project record found.")
        return
    project_name = project_record.get('value', {}).get('name')
    if not project_name:
        print("Project record missing required field 'name'.")
        return

    for record in list_records(service, did, 'dev.dreary.renpy.asset', project_uri):
        download_asset(service, did, os.path.join(dl_dir, project_name, 'game'), record)

    print(f'Downloads complete. {linkify(dl_dir, file=True)}')

def main():
    mode = sys.argv[1] if (len(sys.argv) >= 2) else "--help"
    if mode == "--help":
        print(textwrap.dedent(f"""
            To upload:
            python atp-renpy.py upload [GAME FILES DIRECTORY] [PROJECT NAME]

            To download:
            python atp-renpy.py download [DOWNLOAD DIRECTORY] [PROJECT AT-URI]

            Specify 'HANDLE' and 'PASSWORD' in a .env file in the same
            directory as this script to avoid being prompted on upload

            Download the Ren'Py SDK to run downloaded games:
            {linkify('https://www.renpy.org/latest.html')}
        """))
    elif mode.upper().startswith("U"):
        upload_renpy()
    elif mode.upper().startswith("D"):
        download_renpy()

if __name__ == "__main__":
    main()