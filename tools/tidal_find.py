"""Search Tidal for tracks that the sync could not match, and optionally add them to a playlist.

Run from the project root (where .session.yml lives):
  python tools/tidal_find.py "artist title" ["another query" ...]
  python tools/tidal_find.py --add <tidal_playlist_id> <track_id> [<track_id> ...]
"""
import sys

import tidalapi

from spotify_to_tidal.auth import open_tidal_session


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    session = open_tidal_session()
    if args[0] == "--add":
        playlist = session.playlist(args[1])
        playlist.add([int(track_id) for track_id in args[2:]])
        playlist = session.playlist(args[1])
        print(f"'{playlist.name}' now has {playlist.num_tracks} tracks")
        return
    for query in args:
        print("##", query)
        for track in session.search(query, models=[tidalapi.Track], limit=6)["tracks"]:
            artist = track.artist.name if track.artist else ""
            print(f"   {track.id} | {artist} - {track.name}")


if __name__ == "__main__":
    main()
