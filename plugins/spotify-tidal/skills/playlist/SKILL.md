---
name: playlist
description: Build a curated playlist on Spotify with the user's approval, verify every track, and copy it to Tidal (replacing songs missing on Tidal). Use when the user says "make me a playlist", "create a playlist of instrumental covers", "build a Spotify playlist and copy it to Tidal", "copy this playlist to Tidal", "hazme una playlist", "crea una playlist de covers instrumentales", "pasa esta playlist a tidal", "copia mi playlist de Spotify a Tidal". Run as /spotify-tidal:playlist <request>.
argument-hint: <what playlist you want, e.g. "instrumental covers with cello and sax, 40 songs">
---

# Curated playlist: Spotify first, then Tidal

User request: $ARGUMENTS

Follow these steps in order. Answer in the user's language. Never skip the approval gate in step 4.

## Security rules (always)

- NEVER read, print, grep or upload `config.yml`, `.session.yml` or any `.cache*` file.
- NEVER run `git commit` or `git push`.
- NEVER remove tracks from the user's existing libraries or playlists (editing the list you are proposing is fine). Do NOT run `--sync-favorites` unless explicitly asked (it adds songs to likes on both services).

## Quick mode (optional)

If the official Spotify connector for Claude is available (tool `generate_playlist`) and the user just wants Spotify's AI to pick the songs, offer it as the fast option. If chosen, use it, then jump to step 7 with the resulting playlist id. Otherwise continue with the curated workflow, where you choose and verify every track.

## Workflow

1. **Locate the repo.** Use `$SPOTIFY_TO_TIDAL_HOME` if set, else `~/spotify_to_tidal`; it must contain `pyproject.toml`, `tools/build_playlist.py` and `.venv`. If missing, tell the user to run `/spotify-tidal:setup` and stop. Run all commands from the repo root. `<venv python>` is `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` elsewhere.
2. **Clarify only if vague.** If the request lacks essentials, ask briefly in one message: mood/genre, instruments, reference artists, number of tracks, instrumental or with vocals, which services (Spotify only or also Tidal), and the user's country (ISO code, e.g. CO, MX, ES, US; it decides which tracks are available). Skip anything the user already said; do not interrogate if the request is already clear. Default country: US.
3. **Draft and verify (read-only).** Pick candidates, then save them as `playlists/<slug>.json` (lowercase slug, no spaces) in this format:
   ```json
   {"name": "...", "description": "...", "public": false,
    "tracks": [{"artist": "...", "title": "..."}, {"uri": "spotify:track:..."}]}
   ```
   and run the dry-run, which only searches and creates nothing:
   `SPOTIFY_MARKET=<CC> <venv python> tools/build_playlist.py playlists/<slug>.json --dry-run`
   (PowerShell: `$env:SPOTIFY_MARKET="<CC>"; ...`). Read EVERY line:
   - `OK  wanted -> matched (artists)`: drop or fix false matches: a different artist with the same surname, karaoke/tribute/"originally performed by", versions with vocals when instrumental was requested, live/remix/sped-up when not wanted.
   - `NO  artist - title`: try alternatives (correct the spelling, another performer of the same song, or a `uri` directly) and re-run.
   Repeat until every track resolves to the right recording.
4. **Propose and wait.** Present the verified list numbered and grouped in themed blocks, each line `artist - title` as found on Spotify, plus a short note of what you dropped or swapped and why. Then STOP and wait for explicit approval. If the user asks for changes, edit the JSON, re-run the dry-run and show the list again.
5. **Final check.** If the JSON changed since the last dry-run, run the dry-run once more and fix any new false matches.
6. **Create on Spotify.** Run the same command without `--dry-run`. Capture the playlist id and URL printed at the end.
7. **Copy to Tidal** (skip if the user wants Spotify only): `<venv python> -m spotify_to_tidal --uri <playlist id>`. Parse lines containing `Could not find the track`. For each one:
   - run `<venv python> tools/tidal_find.py "<artist> <title>"` (output lines: `track_id | artist - title`),
   - propose the closest replacement (same recording or same performer; respect instrumental/version constraints),
   - after the user's OK, add with `<venv python> tools/tidal_find.py --add <tidal_playlist_id> <track_id> [<track_id> ...]`.
   To get the Tidal playlist id, run from the repo root a short Python snippet: import `open_tidal_session` from `spotify_to_tidal.auth`, open the session, find the playlist in `session.user.playlists()` whose name equals the Spotify playlist name, and print only its id and name. If that fails, tell the user to copy the id from the Tidal playlist URL (`tidal.com/playlist/<id>`).
   Warn the user: tracks added by hand on Tidal can be overwritten if that playlist is synced again from Spotify; edit on Spotify first.
8. **Final report.** Give: Spotify link, track counts per service, replacements made (original -> replacement), tracks removed or skipped and why.

## Known errors

| Error | Action |
|---|---|
| `403 Insufficient client scope` | Delete the `.cache-<username>` file and re-run to re-authorize in the browser. Never pass `market=from_token`. |
| `412 Precondition Failed` on Tidal | The fork retries automatically; just wait. |
| Token expired (about 6 months) | Browser re-authorization: delete `.cache-<username>` and re-run. |
| `KeyError: 'track'` | Known upstream issue (Spotify's February 2026 field rename when reading playlists); tell the user, do not hack around it. |
| Tidal asks to log in again | Delete `.session.yml` and re-run; the user logs in via the printed link. |
