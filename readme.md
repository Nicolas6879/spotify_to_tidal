A command line tool for importing your Spotify playlists into Tidal. Due to various performance optimisations, it is particularly suited for periodic synchronisation of very large collections.

> **This is a fork of [spotify2tidal/spotify_to_tidal](https://github.com/spotify2tidal/spotify_to_tidal)** that adds:
> - **Two-way favorites sync**: `--sync-favorites` also saves your Tidal favorites to Spotify Liked Songs (add-only, never removes).
> - **Fix for `412 Precondition Failed`** when syncing playlists longer than 20 tracks to Tidal.
> - **Tools to build curated playlists** (see [Building playlists](#building-playlists)), using the Spotify Web API endpoints from the February 2026 changes.

Installation
-----------
Clone this git repository and then run:

```bash
python3 -m pip install -e .
```

Setup
-----
0. Rename the file example_config.yml to config.yml
0. Go [here](https://developer.spotify.com/documentation/general/guides/authorization/app-settings/) and register a new app on developer.spotify.com.
0. Copy and paste your client ID and client secret to the Spotify part of the config file
0. Copy and paste the value in 'redirect_uri' of the config file to Redirect URIs at developer.spotify.com and press ADD
0. Enter your Spotify username to the config file

Usage
----
To synchronize all of your Spotify playlists with your Tidal account run the following from the project root directory
Windows ignores python module paths by default, but you can run them using `python3 -m spotify_to_tidal`

```bash
spotify_to_tidal
```

You can also just synchronize a specific playlist by doing the following:

```bash
spotify_to_tidal --uri 1ABCDEqsABCD6EaABCDa0a # accepts playlist id or full playlist uri
```

or sync just your 'Liked Songs' with:

```bash
spotify_to_tidal --sync-favorites
```

See example_config.yml for more configuration options, and `spotify_to_tidal --help` for more options.

Building playlists
----
Write the tracks you want in a JSON file (see [playlists/covers_cuerdas_saxo_vientos.json](playlists/covers_cuerdas_saxo_vientos.json)):

```json
{"name": "My playlist", "description": "", "public": false,
 "tracks": [{"artist": "2CELLOS", "title": "Thunderstruck"}, {"uri": "spotify:track:0PQfyDuJBxQhx3NTUsAYiC"}]}
```

Check every match first, then create it and copy it to Tidal:

```bash
python tools/build_playlist.py playlists/my_playlist.json --dry-run
python tools/build_playlist.py playlists/my_playlist.json
spotify_to_tidal --uri <playlist id printed above>
```

Searches use the market in the `SPOTIFY_MARKET` environment variable (default `US`). The first run asks you to authorize the playlist-modify scopes. For tracks the sync could not find on Tidal, `python tools/tidal_find.py "artist title"` lists candidates and `python tools/tidal_find.py --add <tidal playlist id> <track id>` adds them.

Note: Spotify apps in Development Mode need the app owner to have Premium and allow at most 5 users, so each user should register their own app.

---

#### Join our amazing community as a code contributor
<br><br>
<a href="https://github.com/spotify2tidal/spotify_to_tidal/graphs/contributors">
  <img class="dark-light" src="https://contrib.rocks/image?repo=spotify2tidal/spotify_to_tidal&anon=0&columns=25&max=100&r=true" />
</a>
