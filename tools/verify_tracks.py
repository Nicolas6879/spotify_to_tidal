"""Verify candidate tracks exist on Spotify.

Run from the project root (where config.yml lives):
  python tools/verify_tracks.py candidates.json results.json

Searches in the market given by the SPOTIFY_MARKET env var (default US).

candidates.json: [{"artist": "...", "title": "...", "block": "..."}]
results.json: same items plus found/uri/sp_name/sp_artists
"""
import json
import os
import sys
import unicodedata

import yaml
from spotify_to_tidal.auth import open_spotify_session

MARKET = os.environ.get("SPOTIFY_MARKET", "US")


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return "".join(c for c in s.casefold() if c.isalnum() or c == " ").strip()


def artist_ok(wanted, artists):
    w = norm(wanted)
    return any(w in norm(a) or norm(a) in w for a in artists)


def title_ok(wanted, name):
    w, n = norm(wanted), norm(name)
    return w in n or n in w or w.split(" ")[0] in n


def find(sp, artist, title):
    for q in (f'track:"{title}" artist:"{artist}"', f"{title} {artist}"):
        items = sp.search(q=q, type="track", limit=10, market=MARKET)["tracks"]["items"]
        for it in items:
            names = [a["name"] for a in it["artists"]]
            if artist_ok(artist, names) and title_ok(title, it["name"]):
                return it
    return None


def main():
    cand_path, out_path = sys.argv[1], sys.argv[2]
    with open("config.yml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    sp = open_spotify_session(config["spotify"])
    with open(cand_path, encoding="utf-8") as f:
        cands = json.load(f)
    out = []
    for c in cands:
        try:
            it = find(sp, c["artist"], c["title"])
        except Exception as e:  # keep going on API errors
            it = None
            c["error"] = str(e)
        r = dict(c, found=bool(it))
        if it:
            r.update(uri=it["uri"], sp_name=it["name"], sp_artists=[a["name"] for a in it["artists"]])
        out.append(r)
        print(("OK  " if it else "NO  ") + f'{c["artist"]} - {c["title"]}' + (f' -> {it["name"]}' if it else ""))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"found {sum(r['found'] for r in out)}/{len(out)}")


if __name__ == "__main__":
    main()
