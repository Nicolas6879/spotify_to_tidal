"""Create a Spotify playlist from a JSON track list.

Run from the project root (where config.yml lives):
  python tools/build_playlist.py playlists/my_list.json [--dry-run]

JSON format:
  {"name": "...", "description": "...", "public": false,
   "tracks": [{"artist": "...", "title": "..."}, {"uri": "spotify:track:..."}]}

Tracks given as artist/title are resolved with tools/verify_tracks.find; always
review the dry-run output for false matches before creating the playlist.
Prints the new playlist id, ready for `python -m spotify_to_tidal --uri <id>`.
"""
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_tracks import find  # noqa: E402
from spotify_to_tidal.auth import open_spotify_session  # noqa: E402


def resolve(sp, tracks):
    uris, missing = [], []
    for t in tracks:
        uri = t.get("uri")
        if not uri:
            it = find(sp, t["artist"], t["title"])
            if it:
                uri = it["uri"]
                print(f"OK  {t['artist']} - {t['title']} -> {it['name']} ({', '.join(a['name'] for a in it['artists'])})")
            else:
                missing.append(t)
                print(f"NO  {t['artist']} - {t['title']}")
        if uri and uri not in uris:
            uris.append(uri)
    return uris, missing


def create(sp, name, description, public, uris):
    # Endpoints from the February 2026 Web API changes; spotipy still calls the old ones
    playlist = sp._post("me/playlists", payload={"name": name, "public": public, "description": description})
    for i in range(0, len(uris), 100):
        sp._post(f"playlists/{playlist['id']}/items", payload={"uris": uris[i:i + 100]})
    return playlist


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    with open(args[0], encoding="utf-8") as f:
        spec = json.load(f)
    with open("config.yml", encoding="utf-8") as f:
        sp = open_spotify_session(yaml.safe_load(f)["spotify"])

    uris, missing = resolve(sp, spec["tracks"])
    print(f"resolved {len(uris)} unique tracks, missing {len(missing)}")
    if "--dry-run" in sys.argv:
        return
    playlist = create(sp, spec["name"], spec.get("description", ""), spec.get("public", False), uris)
    print(f"created '{spec['name']}' with {len(uris)} tracks: {playlist['id']}")
    print(playlist["external_urls"]["spotify"])


if __name__ == "__main__":
    main()
