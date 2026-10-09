#!/usr/bin/env python3

import asyncio
from .cache import failure_cache, track_match_cache
import datetime
from difflib import SequenceMatcher
from functools import partial
from typing import Callable, List, Sequence, Set, Mapping
import math
import requests
import sys
import spotipy
import tidalapi
from .tidalapi_patch import add_multiple_tracks_to_playlist, clear_tidal_playlist, get_all_favorites, get_all_playlists, get_all_playlist_tracks
import time
from tqdm.asyncio import tqdm as atqdm
from tqdm import tqdm
import traceback
import unicodedata
import math

from .type import spotify as t_spotify

def normalize(s) -> str:
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')

def simple(input_string: str) -> str:
    # only take the first part of a string before any hyphens or brackets to account for different versions
    return input_string.split('-')[0].strip().split('(')[0].strip().split('[')[0].strip()

def isrc_match(tidal_track: tidalapi.Track, spotify_track) -> bool:
    if "isrc" in spotify_track["external_ids"]:
        return tidal_track.isrc == spotify_track["external_ids"]["isrc"]
    return False

def duration_match(tidal_track: tidalapi.Track, spotify_track, tolerance=2) -> bool:
    # the duration of the two tracks must be the same to within 2 seconds
    return abs(tidal_track.duration - spotify_track['duration_ms']/1000) < tolerance

def name_match(tidal_track, spotify_track) -> bool:
    def exclusion_rule(pattern: str, tidal_track: tidalapi.Track, spotify_track: t_spotify.SpotifyTrack):
        spotify_has_pattern = pattern in spotify_track['name'].lower()
        tidal_has_pattern = pattern in tidal_track.name.lower() or (not tidal_track.version is None and (pattern in tidal_track.version.lower()))
        return spotify_has_pattern != tidal_has_pattern

    # handle some edge cases
    if exclusion_rule("instrumental", tidal_track, spotify_track): return False
    if exclusion_rule("acapella", tidal_track, spotify_track): return False
    if exclusion_rule("remix", tidal_track, spotify_track): return False

    # the simplified version of the Spotify track name must be a substring of the Tidal track name
    # Try with both un-normalized and then normalized
    simple_spotify_track = simple(spotify_track['name'].lower()).split('feat.')[0].strip()
    return simple_spotify_track in tidal_track.name.lower() or normalize(simple_spotify_track) in normalize(tidal_track.name.lower())

def artist_match(tidal: tidalapi.Track | tidalapi.Album, spotify) -> bool:
    def split_artist_name(artist: str) -> Sequence[str]:
       if '&' in artist:
           return artist.split('&')
       elif ',' in artist:
           return artist.split(',')
       else:
           return [artist]

    def get_tidal_artists(tidal: tidalapi.Track | tidalapi.Album, do_normalize=False) -> Set[str]:
        result: list[str] = []
        for artist in tidal.artists:
            if do_normalize:
                artist_name = normalize(artist.name)
            else:
                artist_name = artist.name
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip().lower()) for x in result])

    def get_spotify_artists(spotify, do_normalize=False) -> Set[str]:
        result: list[str] = []
        for artist in spotify['artists']:
            if do_normalize:
                artist_name = normalize(artist['name'])
            else:
                artist_name = artist['name']
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip().lower()) for x in result])
    # There must be at least one overlapping artist between the Tidal and Spotify track
    # Try with both un-normalized and then normalized
    if get_tidal_artists(tidal).intersection(get_spotify_artists(spotify)) != set():
        return True
    return get_tidal_artists(tidal, True).intersection(get_spotify_artists(spotify, True)) != set()

def match(tidal_track, spotify_track) -> bool:
    if not spotify_track['id']: return False
    return isrc_match(tidal_track, spotify_track) or (
        duration_match(tidal_track, spotify_track)
        and name_match(tidal_track, spotify_track)
        and artist_match(tidal_track, spotify_track)
    )

def test_album_similarity(spotify_album, tidal_album, threshold=0.6):
    return SequenceMatcher(None, simple(spotify_album['name']), simple(tidal_album.name)).ratio() >= threshold and artist_match(tidal_album, spotify_album)

async def tidal_search(spotify_track, rate_limiter, tidal_session: tidalapi.Session) -> tidalapi.Track | None:
    def _search_for_track_in_album():
        # search for album name and first album artist
        if 'album' in spotify_track and 'artists' in spotify_track['album'] and len(spotify_track['album']['artists']):
            query = simple(spotify_track['album']['name']) + " " + simple(spotify_track['album']['artists'][0]['name'])
            album_result = tidal_session.search(query, models=[tidalapi.album.Album])
            for album in album_result['albums']:
                if album.num_tracks >= spotify_track['track_number'] and test_album_similarity(spotify_track['album'], album):
                    album_tracks = album.tracks()
                    if len(album_tracks) < spotify_track['track_number']:
                        assert( not len(album_tracks) == album.num_tracks ) # incorrect metadata :(
                        continue
                    track = album_tracks[spotify_track['track_number'] - 1]
                    if match(track, spotify_track):
                        failure_cache.remove_match_failure(spotify_track['id'])
                        return track

    def _search_for_standalone_track():
        # if album search fails then search for track name and first artist
        query = simple(spotify_track['name']) + ' ' + simple(spotify_track['artists'][0]['name'])
        for track in tidal_session.search(query, models=[tidalapi.media.Track])['tracks']:
            if match(track, spotify_track):
                failure_cache.remove_match_failure(spotify_track['id'])
                return track
    await rate_limiter.acquire()
    album_search = await asyncio.to_thread( _search_for_track_in_album )
    if album_search:
        return album_search
    await rate_limiter.acquire()
    track_search = await asyncio.to_thread( _search_for_standalone_track )
    if track_search:
        return track_search

    # if none of the search modes succeeded then store the track id to the failure cache
    failure_cache.cache_match_failure(spotify_track['id'])

async def repeat_on_request_error(function, *args, remaining=5, **kwargs):
    # utility to repeat calling the function up to 5 times if an exception is thrown
    try:
        return await function(*args, **kwargs)
    except (tidalapi.exceptions.TooManyRequests, requests.exceptions.RequestException, spotipy.exceptions.SpotifyException) as e:
        if remaining:
            print(f"{str(e)} occurred, retrying {remaining} times")
        else:
            print(f"{str(e)} could not be recovered")

        if isinstance(e, requests.exceptions.RequestException) and not e.response is None:
            print(f"Response message: {e.response.text}")
            print(f"Response headers: {e.response.headers}")

        if not remaining:
            print("Aborting sync")
            print(f"The following arguments were provided:\n\n {str(args)}")
            print(traceback.format_exc())
            sys.exit(1)
        sleep_schedule = {5: 1, 4:10, 3:60, 2:5*60, 1:10*60} # sleep variable length of time depending on retry number
        time.sleep(sleep_schedule.get(remaining, 1))
        return await repeat_on_request_error(function, *args, remaining=remaining-1, **kwargs)


async def _fetch_all_from_spotify_in_chunks(fetch_function: Callable) -> List[dict]:
    output = []
    results = fetch_function(0)
    output.extend([item['track'] for item in results['items'] if item['track'] is not None])

    # Get all the remaining tracks in parallel
    if results['next']:
        offsets = [results['limit'] * n for n in range(1, math.ceil(results['total'] / results['limit']))]
        extra_results = await atqdm.gather(
            *[asyncio.to_thread(fetch_function, offset) for offset in offsets],
            desc="Fetching additional data chunks"
        )
        for extra_result in extra_results:
            output.extend([item['track'] for item in extra_result['items'] if item['track'] is not None])

    return output


async def get_tracks_from_spotify_playlist(spotify_session: spotipy.Spotify, spotify_playlist):
    def _get_tracks_from_spotify_playlist(offset: int, playlist_id: str):
        fields = "next,total,limit,items(track(name,album(name,artists),artists,track_number,duration_ms,id,external_ids(isrc))),type"
        return spotify_session.playlist_tracks(playlist_id=playlist_id, fields=fields, offset=offset)

    print(f"Loading tracks from Spotify playlist '{spotify_playlist['name']}'")
    items = await repeat_on_request_error( _fetch_all_from_spotify_in_chunks, lambda offset: _get_tracks_from_spotify_playlist(offset=offset, playlist_id=spotify_playlist["id"]))
    track_filter = lambda item: item.get('type', 'track') == 'track' # type may be 'episode' also
    sanity_filter = lambda item: ('album' in item
                                  and 'name' in item['album']
                                  and 'artists' in item['album']
                                  and len(item['album']['artists']) > 0
                                  and item['album']['artists'][0]['name'] is not None)
    return list(filter(sanity_filter, filter(track_filter, items)))

def populate_track_match_cache(spotify_tracks_: Sequence[t_spotify.SpotifyTrack], tidal_tracks_: Sequence[tidalapi.Track]):
    """ Populate the track match cache with all the existing tracks in Tidal playlist corresponding to Spotify playlist """
    def _populate_one_track_from_spotify(spotify_track: t_spotify.SpotifyTrack):
        for idx, tidal_track in list(enumerate(tidal_tracks)):
            if tidal_track.available and match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                tidal_tracks.pop(idx)
                return

    def _populate_one_track_from_tidal(tidal_track: tidalapi.Track):
        for idx, spotify_track in list(enumerate(spotify_tracks)):
            if tidal_track.available and match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                spotify_tracks.pop(idx)
                return

    # make a copy of the tracks to avoid modifying original arrays
    spotify_tracks = [t for t in spotify_tracks_]
    tidal_tracks = [t for t in tidal_tracks_]

    # first populate from the tidal tracks
    for track in tidal_tracks:
        _populate_one_track_from_tidal(track)
    # then populate from the subset of Spotify tracks that didn't match (to account for many-to-one style mappings)
    for track in spotify_tracks:
        _populate_one_track_from_spotify(track)

def get_new_spotify_tracks(spotify_tracks: Sequence[t_spotify.SpotifyTrack]) -> List[t_spotify.SpotifyTrack]:
    ''' Extracts only the tracks that have not already been seen in our Tidal caches '''
    results = []
    for spotify_track in spotify_tracks:
        if not spotify_track['id']: continue
        if not track_match_cache.get(spotify_track['id']) and not failure_cache.has_match_failure(spotify_track['id']):
            results.append(spotify_track)
    return results

def get_tracks_for_new_tidal_playlist(spotify_tracks: Sequence[t_spotify.SpotifyTrack]) -> Sequence[int]:
    ''' gets list of corresponding tidal track ids for each spotify track, ignoring duplicates '''
    output = []
    seen_tracks = set()

    for spotify_track in spotify_tracks:
        if not spotify_track['id']: continue
        tidal_id = track_match_cache.get(spotify_track['id'])
        if tidal_id:
            if tidal_id in seen_tracks:
                track_name = spotify_track['name']
                artist_names = ', '.join([artist['name'] for artist in spotify_track['artists']])
                print(f'Duplicate found: Track "{track_name}" by {artist_names} will be ignored') 
            else:
                output.append(tidal_id)
                seen_tracks.add(tidal_id)
    return output

async def _run_rate_limiter(semaphore, config: dict):
    ''' Leaky bucket algorithm for rate limiting. Periodically releases items from semaphore at rate_limit'''
    _sleep_time = config.get('max_concurrency', 10)/config.get('rate_limit', 10)/4 # aim to sleep approx time to drain 1/4 of 'bucket'
    t0 = datetime.datetime.now()
    while True:
        await asyncio.sleep(_sleep_time)
        t = datetime.datetime.now()
        dt = (t - t0).total_seconds()
        new_items = round(config.get('rate_limit', 10)*dt)
        t0 = t
        [semaphore.release() for i in range(new_items)] # leak new_items from the 'bucket'

async def spotify_search(tidal_track: tidalapi.Track, rate_limiter, spotify_session: spotipy.Spotify) -> t_spotify.SpotifyTrack | None:
    """ search Spotify for the Spotify equivalent of a given Tidal track """
    def _search():
        artist_name = tidal_track.artist.name if tidal_track.artist else ''
        query = simple(tidal_track.name) + ' ' + simple(artist_name)
        results = spotify_session.search(q=query, type='track', limit=10)
        for candidate in results['tracks']['items']:
            if match(tidal_track, candidate):
                return candidate
    await rate_limiter.acquire()
    return await asyncio.to_thread(_search)

async def search_new_tracks_on_spotify(spotify_session: spotipy.Spotify, tidal_tracks: Sequence[tidalapi.Track], playlist_name: str, config: dict):
    """ Generic function for searching Spotify for each Tidal track which doesn't already have a known match, caching successes. Does not modify anything on Spotify. """
    tracks_to_search = [t for t in tidal_tracks if t.available and track_match_cache.get_by_tidal_id(t.id) is None]
    if not tracks_to_search:
        return

    task_description = "Searching Spotify for {}/{} tracks in Tidal '{}'".format(len(tracks_to_search), len(tidal_tracks), playlist_name)
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore, config))
    search_results = await atqdm.gather( *[ repeat_on_request_error(spotify_search, t, semaphore, spotify_session) for t in tracks_to_search ], desc=task_description )
    rate_limiter_task.cancel()

    song404 = []
    for idx, tidal_track in enumerate(tracks_to_search):
        if search_results[idx]:
            track_match_cache.insert( (search_results[idx]['id'], tidal_track.id) )
        else:
            artist_name = tidal_track.artist.name if tidal_track.artist else 'unknown artist'
            song404.append(f"{tidal_track.id}: {artist_name} - {tidal_track.name}")
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find the track " + song404[-1] + color[1])
    file_name = "songs not found.txt"
    header = f"==========================\nTidal -> Spotify: {playlist_name}\n==========================\n"
    with open(file_name, "a", encoding="utf-8") as file:
        file.write(header)
        for song in song404:
            file.write(f"{song}\n")

def add_tracks_to_spotify_favorites(spotify_session: spotipy.Spotify, track_ids: Sequence[str], chunk_size: int=50):
    with tqdm(desc="Adding new tracks to Spotify favorites", total=len(track_ids)) as progress:
        for offset in range(0, len(track_ids), chunk_size):
            chunk = track_ids[offset:offset+chunk_size]
            spotify_session.current_user_saved_tracks_add(tracks=chunk)
            progress.update(len(chunk))

async def search_new_tracks_on_tidal(tidal_session: tidalapi.Session, spotify_tracks: Sequence[t_spotify.SpotifyTrack], playlist_name: str, config: dict):
    """ Generic function for searching for each item in a list of Spotify tracks which have not already been seen and adding them to the cache """
    # Extract the new tracks that do not already exist in the old tidal tracklist
    tracks_to_search = get_new_spotify_tracks(spotify_tracks)
    if not tracks_to_search:
        return

    # Search for each of the tracks on Tidal concurrently
    task_description = "Searching Tidal for {}/{} tracks in Spotify playlist '{}'".format(len(tracks_to_search), len(spotify_tracks), playlist_name)
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore, config))
    search_results = await atqdm.gather( *[ repeat_on_request_error(tidal_search, t, semaphore, tidal_session) for t in tracks_to_search ], desc=task_description )
    rate_limiter_task.cancel()

    # Add the search results to the cache
    song404 = []
    for idx, spotify_track in enumerate(tracks_to_search):
        if search_results[idx]:
            track_match_cache.insert( (spotify_track['id'], search_results[idx].id) )
        else:
            song404.append(f"{spotify_track['id']}: {','.join([a['name'] for a in spotify_track['artists']])} - {spotify_track['name']}")
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find the track " + song404[-1] + color[1])
    file_name = "songs not found.txt"
    header = f"==========================\nPlaylist: {playlist_name}\n==========================\n"
    with open(file_name, "a", encoding="utf-8") as file:
        file.write(header)
        for song in song404:
            file.write(f"{song}\n")

            
async def sync_playlist(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, spotify_playlist, tidal_playlist: tidalapi.Playlist | None, config: dict):
    """ sync given playlist to tidal """
    # Get the tracks from both Spotify and Tidal, creating a new Tidal playlist if necessary
    spotify_tracks = await get_tracks_from_spotify_playlist(spotify_session, spotify_playlist)
    if len(spotify_tracks) == 0:
        return # nothing to do
    if tidal_playlist:
        old_tidal_tracks = await get_all_playlist_tracks(tidal_playlist)
    else:
        print(f"No playlist found on Tidal corresponding to Spotify playlist: '{spotify_playlist['name']}', creating new playlist")
        tidal_playlist =  tidal_session.user.create_playlist(spotify_playlist['name'], spotify_playlist['description'])
        old_tidal_tracks = []

    # Extract the new tracks from the playlist that we haven't already seen before
    populate_track_match_cache(spotify_tracks, old_tidal_tracks)
    await search_new_tracks_on_tidal(tidal_session, spotify_tracks, spotify_playlist['name'], config)
    new_tidal_track_ids = get_tracks_for_new_tidal_playlist(spotify_tracks)

    # Update the Tidal playlist if there are changes
    old_tidal_track_ids = [t.id for t in old_tidal_tracks]
    if new_tidal_track_ids == old_tidal_track_ids:
        print("No changes to write to Tidal playlist")
    elif new_tidal_track_ids[:len(old_tidal_track_ids)] == old_tidal_track_ids:
        # Append new tracks to the existing playlist if possible
        add_multiple_tracks_to_playlist(tidal_playlist, new_tidal_track_ids[len(old_tidal_track_ids):])
    else:
        # Erase old playlist and add new tracks from scratch if any reordering occured
        clear_tidal_playlist(tidal_playlist)
        add_multiple_tracks_to_playlist(tidal_playlist, new_tidal_track_ids)

async def _get_tracks_from_spotify_favorites(spotify_session: spotipy.Spotify) -> List[dict]:
    _get_favorite_tracks = lambda offset: spotify_session.current_user_saved_tracks(offset=offset)
    tracks = await repeat_on_request_error( _fetch_all_from_spotify_in_chunks, _get_favorite_tracks)
    tracks.reverse()
    return tracks

async def _load_favorites(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session):
    """ loads favorites from both services and populates the match cache with existing overlaps """
    print("Loading favorite tracks from Spotify")
    spotify_tracks = await _get_tracks_from_spotify_favorites(spotify_session)
    print("Loading existing favorite tracks from Tidal")
    tidal_tracks = await get_all_favorites(tidal_session.user.favorites, order='DATE')
    populate_track_match_cache(spotify_tracks, tidal_tracks)
    return spotify_tracks, tidal_tracks

def _log_favorites_sync(direction: str, entries: Sequence[str]):
    """ append a timestamped record of what was added to 'favorites sync log.txt' for audit purposes """
    with open("favorites sync log.txt", "a", encoding="utf-8") as file:
        file.write(f"==========================\n{datetime.datetime.now().isoformat()} - {direction}\n==========================\n")
        for entry in entries:
            file.write(f"{entry}\n")

async def sync_favorites_tidal(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict, spotify_tracks=None, tidal_tracks=None):
    """ sync Spotify favorites to Tidal favorites. Only adds tracks, never removes any """
    if spotify_tracks is None or tidal_tracks is None:
        spotify_tracks, tidal_tracks = await _load_favorites(spotify_session, tidal_session)

    def get_new_tidal_favorites() -> List[tuple[int, str]]:
        existing_favorite_ids = set([track.id for track in tidal_tracks])
        new_favorites = []
        for spotify_track in spotify_tracks:
            match_id = track_match_cache.get(spotify_track['id'])
            if match_id and not match_id in existing_favorite_ids:
                artist_names = ', '.join([artist['name'] for artist in spotify_track['artists']])
                new_favorites.append((match_id, f"{artist_names} - {spotify_track['name']}"))
        return new_favorites

    await search_new_tracks_on_tidal(tidal_session, spotify_tracks, "Favorites", config)
    new_tidal_favorites = get_new_tidal_favorites()
    if new_tidal_favorites:
        for tidal_id, _ in tqdm(new_tidal_favorites, desc="Adding new tracks to Tidal favorites"):
            tidal_session.user.favorites.add_track(tidal_id)
        _log_favorites_sync("Spotify -> Tidal", [description for _, description in new_tidal_favorites])
    else:
        print("No new tracks to add to Tidal favorites")

async def sync_favorites_spotify(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict, spotify_tracks=None, tidal_tracks=None):
    """ sync Tidal favorites to Spotify favorites. Only adds tracks, never removes any """
    if spotify_tracks is None or tidal_tracks is None:
        spotify_tracks, tidal_tracks = await _load_favorites(spotify_session, tidal_session)

    def get_new_spotify_favorites() -> List[tuple[str, str]]:
        existing_favorite_ids = set([track['id'] for track in spotify_tracks if track['id']])
        new_favorites = []
        seen: Set[str] = set()
        for tidal_track in tidal_tracks:
            spotify_id = track_match_cache.get_by_tidal_id(tidal_track.id)
            if spotify_id and not spotify_id in existing_favorite_ids and not spotify_id in seen:
                artist_name = tidal_track.artist.name if tidal_track.artist else 'unknown artist'
                new_favorites.append((spotify_id, f"{artist_name} - {tidal_track.name}"))
                seen.add(spotify_id)
        return new_favorites

    await search_new_tracks_on_spotify(spotify_session, tidal_tracks, "Favorites", config)
    new_spotify_favorites = get_new_spotify_favorites()
    new_spotify_favorite_ids = [track_id for track_id, _ in new_spotify_favorites]
    if new_spotify_favorite_ids:
        add_tracks_to_spotify_favorites(spotify_session, new_spotify_favorite_ids)
        _log_favorites_sync("Tidal -> Spotify", [description for _, description in new_spotify_favorites])
    else:
        print("No new tracks to add to Spotify favorites")

async def sync_favorites(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    """ sync favorites in both directions between Spotify and Tidal. Only adds tracks, never removes any """
    spotify_tracks, tidal_tracks = await _load_favorites(spotify_session, tidal_session)
    await sync_favorites_tidal(spotify_session, tidal_session, config, spotify_tracks, tidal_tracks)
    await sync_favorites_spotify(spotify_session, tidal_session, config, spotify_tracks, tidal_tracks)

def sync_playlists_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, playlists, config: dict):
  for spotify_playlist, tidal_playlist in playlists:
    # sync the spotify playlist to tidal
    asyncio.run(sync_playlist(spotify_session, tidal_session, spotify_playlist, tidal_playlist, config) )

def sync_favorites_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    asyncio.run(main=sync_favorites(spotify_session=spotify_session, tidal_session=tidal_session, config=config))

def get_tidal_playlists_wrapper(tidal_session: tidalapi.Session) -> Mapping[str, tidalapi.Playlist]:
    tidal_playlists = asyncio.run(get_all_playlists(tidal_session.user))
    return {playlist.name: playlist for playlist in tidal_playlists}

def pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists: Mapping[str, tidalapi.Playlist]):
    if spotify_playlist['name'] in tidal_playlists:
      # if there's an existing tidal playlist with the name of the current playlist then use that
      tidal_playlist = tidal_playlists[spotify_playlist['name']]
      return (spotify_playlist, tidal_playlist)
    else:
      return (spotify_playlist, None)

def get_user_playlist_mappings(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    results = []
    spotify_playlists = asyncio.run(get_playlists_from_spotify(spotify_session, config))
    tidal_playlists = get_tidal_playlists_wrapper(tidal_session)
    for spotify_playlist in spotify_playlists:
        results.append( pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists) )
    return results

async def get_playlists_from_spotify(spotify_session: spotipy.Spotify, config):
    # get all the playlists from the Spotify account
    playlists = []
    print("Loading Spotify playlists")
    first_results = spotify_session.current_user_playlists()
    exclude_list = set([x.split(':')[-1] for x in config.get('excluded_playlists', [])])
    playlists.extend([p for p in first_results['items']])
    user_id = spotify_session.current_user()['id']

    # get all the remaining playlists in parallel
    if first_results['next']:
        offsets = [ first_results['limit'] * n for n in range(1, math.ceil(first_results['total']/first_results['limit'])) ]
        extra_results = await atqdm.gather( *[asyncio.to_thread(spotify_session.current_user_playlists, offset=offset) for offset in offsets ] )
        for extra_result in extra_results:
            playlists.extend([p for p in extra_result['items']])

    # filter out playlists that don't belong to us or are on the exclude list
    my_playlist_filter = lambda p: p and p['owner']['id'] == user_id
    exclude_filter = lambda p: not p['id'] in exclude_list
    return list(filter( exclude_filter, filter( my_playlist_filter, playlists )))

def get_playlists_from_config(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    # get the list of playlist sync mappings from the configuration file
    def get_playlist_ids(config):
        return [(item['spotify_id'], item['tidal_id']) for item in config['sync_playlists']]
    output = []
    for spotify_id, tidal_id in get_playlist_ids(config=config):
        try:
            spotify_playlist = spotify_session.playlist(playlist_id=spotify_id)
        except spotipy.SpotifyException as e:
            print(f"Error getting Spotify playlist {spotify_id}")
            raise e
        try:
            tidal_playlist = tidal_session.playlist(playlist_id=tidal_id)
        except Exception as e:
            print(f"Error getting Tidal playlist {tidal_id}")
            raise e
        output.append((spotify_playlist, tidal_playlist))
    return output

