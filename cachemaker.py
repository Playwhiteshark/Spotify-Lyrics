import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth


# ============ CONFIG ============

try:
    from spotify_secrets import SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, PLAYLIST_URL_OR_ID
except ImportError:
    raise ImportError(
        "Missing spotify_secrets.py. Copy spotify_secrets_example.py, "
        "rename it to spotify_secrets.py, and add your Spotify client ID and secret."
    )

SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback"

SCOPE = "playlist-read-private playlist-read-collaborative"

LRCLIB_GET_URL = "https://lrclib.net/api/get"
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"

CACHE_FILE = "lyrics_cache.json"



# Be careful with this. Search fallback can make multiple LRCLIB requests per song.
WORKER_COUNT = 4

# Exact match gets a proper chance first.
MAX_EXACT_ATTEMPTS = 7
RETRY_DELAY = 0.2

# Search matches below this score will not even be shown for manual review.
# Lower it if you want more risky/weird suggestions.
MIN_REVIEW_SCORE = 45

HTTP_HEADERS = {
    "User-Agent": "SpotifyLyricsCacheMaker/1.0"
}

ALBUM_NAME_OVERRIDES = {
    ("The Cranberries", "Zombie", "Gold"): "No Need To Argue"
}


# ============ SPOTIFY ============

spAuth = SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope=SCOPE
)

sp = spotipy.Spotify(auth_manager=spAuth)


# ============ CACHE ============

def LoadCache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as cacheFile:
            return json.load(cacheFile)

    except FileNotFoundError:
        return {}

    except json.JSONDecodeError:
        print("Cache file exists but is broken. Starting with empty cache.")
        return {}


def SaveCache(cacheDict):
    with open(CACHE_FILE, "w", encoding="utf-8") as cacheFile:
        json.dump(cacheDict, cacheFile, indent=4, ensure_ascii=False)


def SaveManualSearchMatchToCache(lyricsCache, result):
    trackID = result["trackID"]

    lyricsCache[trackID] = {
        "trackName": result["trackName"],
        "artistName": result["artistName"],
        "artistNames": result["artistNames"],
        "albumName": result["albumName"],
        "lrclibAlbumName": result["matchedAlbumName"],
        "durationMS": result["durationMS"],
        "syncedLyrics": result["syncedLyrics"],
        "cachedAt": time.time(),
        "source": "manual_search",
        "matchScore": result["matchScore"],
        "matchedTrackName": result["matchedTrackName"],
        "matchedArtistName": result["matchedArtistName"],
        "matchedAlbumName": result["matchedAlbumName"],
        "matchedDuration": result["matchedDuration"],
        "durationDifference": result["durationDifference"]
    }

    SaveCache(lyricsCache)


def SaveExactMatchToCache(lyricsCache, result):
    trackID = result["trackID"]

    lyricsCache[trackID] = {
        "trackName": result["trackName"],
        "artistName": result["artistName"],
        "artistNames": result["artistNames"],
        "albumName": result["albumName"],
        "lrclibAlbumName": result["lrclibAlbumName"],
        "durationMS": result["durationMS"],
        "syncedLyrics": result["syncedLyrics"],
        "cachedAt": time.time(),
        "source": "exact"
    }

    SaveCache(lyricsCache)


# ============ FORMATTING ============

def GetDurationSeconds(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def FormatDurationSeconds(durationS):
    durationS = GetDurationSeconds(durationS)

    if durationS is None:
        return "unknown"

    minutes = durationS // 60
    seconds = durationS % 60

    return f"{minutes}:{seconds:02d}"


def FormatDurationMS(durationMS):
    if durationMS is None:
        return "unknown"

    return FormatDurationSeconds(durationMS / 1000)


def CountSyncedLyricLines(syncedLyrics):
    if not isinstance(syncedLyrics, str):
        return 0

    count = 0

    for line in syncedLyrics.splitlines():
        line = line.strip()

        if line.startswith("[") and "]" in line:
            count += 1

    return count


def GetSyncedLyricsPreview(syncedLyrics, maxLines=6):
    if not isinstance(syncedLyrics, str):
        return []

    previewLines = []

    for line in syncedLyrics.splitlines():
        line = line.strip()

        if line == "":
            continue

        previewLines.append(line)

        if len(previewLines) >= maxLines:
            break

    return previewLines


# ============ TEXT CLEANING / MATCHING ============

def HasSyncedLyrics(syncedLyrics):
    return isinstance(syncedLyrics, str) and syncedLyrics.strip() != ""


def NormalizeText(text):
    if text is None:
        return ""

    text = text.lower()
    text = unicodedata.normalize("NFKD", text)

    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", "and")

    cleanedCharacters = []

    for char in text:
        if char.isalnum() or char.isspace():
            cleanedCharacters.append(char)
        else:
            cleanedCharacters.append(" ")

    text = "".join(cleanedCharacters)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def StripVersionWords(trackName):
    cleaned = trackName

    cleaned = re.sub(
        r"\s*[\(\[].*?(remix|edit|version|remaster|remastered|live|sped up|slowed|instrumental|karaoke).*?[\)\]]",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(
        r"\s+-\s+.*?(remix|edit|mix|version|remaster|remastered|live|sped up|slowed|instrumental|karaoke).*$",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    return cleaned.strip()


def TextSimilarity(textA, textB):
    textA = NormalizeText(textA)
    textB = NormalizeText(textB)

    if textA == "" or textB == "":
        return 0.0

    if textA == textB:
        return 1.0

    if len(textA) >= 4 and len(textB) >= 4:
        if textA in textB or textB in textA:
            return 0.85

    return SequenceMatcher(None, textA, textB).ratio()


def ScoreLRCLIBResult(result, spotifyArtistNames, spotifyTrackName, spotifyDurationMS):
    if not HasSyncedLyrics(result.get("syncedLyrics")):
        return -9999

    resultTrackName = result.get("trackName", "")
    resultArtistName = result.get("artistName", "")
    resultDurationS = GetDurationSeconds(result.get("duration"))

    spotifyTrackClean = StripVersionWords(spotifyTrackName)
    resultTrackClean = StripVersionWords(resultTrackName)

    titleSimilarity = TextSimilarity(spotifyTrackClean, resultTrackClean)

    artistSimilarities = []

    for artistName in spotifyArtistNames:
        artistSimilarities.append(TextSimilarity(artistName, resultArtistName))

    joinedArtists = ", ".join(spotifyArtistNames)
    artistSimilarities.append(TextSimilarity(joinedArtists, resultArtistName))

    artistSimilarity = max(artistSimilarities) if artistSimilarities else 0.0

    score = 0.0

    score += titleSimilarity * 60
    score += artistSimilarity * 25

    spotifyDurationS = GetDurationSeconds(spotifyDurationMS / 1000)

    if resultDurationS is not None and spotifyDurationS is not None:
        durationDifference = abs(resultDurationS - spotifyDurationS)

        if durationDifference <= 2:
            score += 30
        elif durationDifference <= 5:
            score += 24
        elif durationDifference <= 10:
            score += 12
        elif durationDifference <= 20:
            score += 0
        else:
            score -= 40

    if titleSimilarity < 0.55:
        score -= 40

    return score


# ============ LRCLIB ============

def GetLRCLIBLyrics(artistName, trackName, albumName, durationMS):
    params = {
        "artist_name": artistName,
        "track_name": trackName,
        "album_name": albumName,
        "duration": durationMS // 1000
    }

    try:
        response = requests.get(
            LRCLIB_GET_URL,
            params=params,
            headers=HTTP_HEADERS,
            timeout=7
        )

    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()

    except ValueError:
        return None

    syncedLyrics = data.get("syncedLyrics")

    if HasSyncedLyrics(syncedLyrics):
        return syncedLyrics

    return None


def BuildSearchQueries(artistNames, trackName):
    queries = []
    seenQueries = set()

    strippedTrackName = StripVersionWords(trackName)

    def AddQuery(params):
        key = tuple(sorted(params.items()))

        if key in seenQueries:
            return

        seenQueries.add(key)
        queries.append(params)

    primaryArtistName = artistNames[0] if len(artistNames) > 0 else ""

    AddQuery({
        "track_name": strippedTrackName,
        "artist_name": primaryArtistName
    })

    AddQuery({
        "q": f"{strippedTrackName} {primaryArtistName}"
    })

    AddQuery({
        "q": strippedTrackName
    })

    for artistName in artistNames:
        AddQuery({
            "track_name": strippedTrackName,
            "artist_name": artistName
        })

        AddQuery({
            "q": f"{strippedTrackName} {artistName}"
        })

    if strippedTrackName != trackName:
        AddQuery({
            "track_name": trackName,
            "artist_name": primaryArtistName
        })

        AddQuery({
            "q": f"{trackName} {primaryArtistName}"
        })

        AddQuery({
            "q": trackName
        })

    return queries


def SearchLRCLIBBestCandidate(artistNames, trackName, durationMS):
    searchQueries = BuildSearchQueries(artistNames, trackName)

    bestResult = None
    bestScore = -9999

    for params in searchQueries:
        try:
            response = requests.get(
                LRCLIB_SEARCH_URL,
                params=params,
                headers=HTTP_HEADERS,
                timeout=7
            )

        except requests.RequestException:
            continue

        if response.status_code != 200:
            continue

        try:
            results = response.json()

        except ValueError:
            continue

        if not isinstance(results, list):
            continue

        for result in results:
            if not HasSyncedLyrics(result.get("syncedLyrics")):
                continue

            score = ScoreLRCLIBResult(
                result,
                artistNames,
                trackName,
                durationMS
            )

            if score > bestScore:
                bestScore = score
                bestResult = result

    return bestResult, bestScore


# ============ PLAYLIST ============

def ExtractPlaylistID(playlistInput):
    playlistInput = playlistInput.strip()

    if "open.spotify.com/playlist/" in playlistInput:
        afterPlaylist = playlistInput.split("playlist/")[1]
        playlistID = afterPlaylist.split("?")[0]
        return playlistID

    if "spotify:playlist:" in playlistInput:
        return playlistInput.split("spotify:playlist:")[1]

    return playlistInput


def GetTrackFromPlaylistItem(playlistItem):
    track = playlistItem.get("item")

    if track is None:
        track = playlistItem.get("track")

    if track is None:
        return None

    if track.get("type") != "track":
        return None

    if playlistItem.get("is_local") == True:
        return None

    if track.get("id") is None:
        return None

    return track


def GetAllPlaylistTracks(playlistID):
    tracks = []
    offset = 0
    limit = 50

    while True:
        results = sp.playlist_items(
            playlistID,
            limit=limit,
            offset=offset,
            market="from_token",
            additional_types=("track",)
        )

        items = results.get("items", [])

        print("Spotify reported total:", results.get("total"))
        print("Items in this page:", len(items))

        usableTracksThisPage = 0

        for playlistItem in items:
            track = GetTrackFromPlaylistItem(playlistItem)

            if track is None:
                continue

            tracks.append(track)
            usableTracksThisPage += 1

        print("Usable tracks this page:", usableTracksThisPage)
        print("Tracks collected so far:", len(tracks))
        print()

        if results.get("next") is None:
            break

        offset += limit

    return tracks


def BuildFrontBackTaskOrder(tracks):
    taskOrder = []
    left = 0
    right = len(tracks) - 1

    while left <= right:
        taskOrder.append((left + 1, tracks[left]))

        if left != right:
            taskOrder.append((right + 1, tracks[right]))

        left += 1
        right -= 1

    return taskOrder


# ============ WORKER ============

def GetTrackMetadata(track):
    trackID = track.get("id")

    if trackID is None:
        return None

    artistObjects = track.get("artists", [])
    artistNames = []

    for artist in artistObjects:
        artistName = artist.get("name")

        if artistName is not None:
            artistNames.append(artistName)

    if len(artistNames) == 0:
        return None

    trackName = track.get("name")

    albumObject = track.get("album", {})
    albumName = albumObject.get("name")

    durationMS = track.get("duration_ms")

    if trackName is None or albumName is None or durationMS is None:
        return None

    return {
        "trackID": trackID,
        "artistNames": artistNames,
        "artistName": artistNames[0],
        "trackName": trackName,
        "albumName": albumName,
        "durationMS": durationMS
    }


def FetchLyricsForTrack(index, totalTracks, track):
    metadata = GetTrackMetadata(track)

    if metadata is None:
        return {
            "status": "SKIPPED",
            "reason": "Bad or missing track data",
            "index": index,
            "totalTracks": totalTracks
        }

    trackID = metadata["trackID"]
    artistNames = metadata["artistNames"]
    artistName = metadata["artistName"]
    trackName = metadata["trackName"]
    spotifyAlbumName = metadata["albumName"]
    lrclibAlbumName = spotifyAlbumName
    durationMS = metadata["durationMS"]

    overrideKey = (artistName, trackName, spotifyAlbumName)

    if overrideKey in ALBUM_NAME_OVERRIDES:
        lrclibAlbumName = ALBUM_NAME_OVERRIDES[overrideKey]

    # 1. Exact match gets 7 attempts first.
    for attempt in range(1, MAX_EXACT_ATTEMPTS + 1):
        syncedLyrics = GetLRCLIBLyrics(
            artistName,
            trackName,
            lrclibAlbumName,
            durationMS
        )

        if syncedLyrics is not None:
            return {
                "status": "CACHED",
                "source": "exact",
                "index": index,
                "totalTracks": totalTracks,
                "trackID": trackID,
                "trackName": trackName,
                "artistName": artistName,
                "artistNames": artistNames,
                "albumName": spotifyAlbumName,
                "lrclibAlbumName": lrclibAlbumName,
                "durationMS": durationMS,
                "syncedLyrics": syncedLyrics,
                "attempts": attempt
            }

        if attempt < MAX_EXACT_ATTEMPTS:
            time.sleep(RETRY_DELAY)

    # 2. If exact failed, search for a possible alternative.
    bestResult, bestScore = SearchLRCLIBBestCandidate(
        artistNames,
        trackName,
        durationMS
    )

    if bestResult is not None and bestScore >= MIN_REVIEW_SCORE:
        spotifyDurationS = GetDurationSeconds(durationMS / 1000)
        matchedDurationS = GetDurationSeconds(bestResult.get("duration"))

        durationDifference = None

        if spotifyDurationS is not None and matchedDurationS is not None:
            durationDifference = abs(spotifyDurationS - matchedDurationS)

        return {
            "status": "REVIEW",
            "index": index,
            "totalTracks": totalTracks,
            "trackID": trackID,
            "trackName": trackName,
            "artistName": artistName,
            "artistNames": artistNames,
            "albumName": spotifyAlbumName,
            "durationMS": durationMS,
            "matchedTrackName": bestResult.get("trackName"),
            "matchedArtistName": bestResult.get("artistName"),
            "matchedAlbumName": bestResult.get("albumName"),
            "matchedDuration": bestResult.get("duration"),
            "durationDifference": durationDifference,
            "matchScore": bestScore,
            "syncedLyrics": bestResult.get("syncedLyrics"),
            "attempts": MAX_EXACT_ATTEMPTS
        }

    failedResult = {
        "status": "FAILED",
        "index": index,
        "totalTracks": totalTracks,
        "trackID": trackID,
        "trackName": trackName,
        "artistName": artistName,
        "artistNames": artistNames,
        "albumName": spotifyAlbumName,
        "durationMS": durationMS,
        "attempts": MAX_EXACT_ATTEMPTS
    }

    if bestResult is not None:
        failedResult["bestRejectedTrackName"] = bestResult.get("trackName")
        failedResult["bestRejectedArtistName"] = bestResult.get("artistName")
        failedResult["bestRejectedAlbumName"] = bestResult.get("albumName")
        failedResult["bestRejectedDuration"] = bestResult.get("duration")
        failedResult["bestRejectedScore"] = bestScore

    return failedResult


# ============ MANUAL REVIEW ============

def AskToCacheManualMatch(result):
    print()
    print("=" * 70)
    print(f"Manual review candidate [{result['index']}/{result['totalTracks']}]")
    print("=" * 70)

    print("Spotify track:")
    print("   Artist(s):", ", ".join(result["artistNames"]))
    print("   Track:", result["trackName"])
    print("   Album:", result["albumName"])
    print("   Duration:", FormatDurationMS(result["durationMS"]))
    print("   Spotify track ID:", result["trackID"])

    print()
    print("LRCLIB suggested match:")
    print("   Artist:", result.get("matchedArtistName"))
    print("   Track:", result.get("matchedTrackName"))
    print("   Album:", result.get("matchedAlbumName"))
    print("   Duration:", FormatDurationSeconds(result.get("matchedDuration")))
    print("   Score:", round(result.get("matchScore", 0), 1))

    if result.get("durationDifference") is not None:
        print("   Duration difference:", result["durationDifference"], "seconds")
    else:
        print("   Duration difference: unknown")

    print("   Synced lyric lines:", CountSyncedLyricLines(result.get("syncedLyrics")))

    previewLines = GetSyncedLyricsPreview(result.get("syncedLyrics"), maxLines=6)

    if len(previewLines) > 0:
        print()
        print("Synced lyrics preview:")
        for line in previewLines:
            print("   " + line)

    print()

    while True:
        answer = input("Cache this LRCLIB match for the Spotify track? [y/N]: ")
        answer = answer.strip().lower()

        if answer in ["y", "yes"]:
            return True

        if answer in ["", "n", "no"]:
            return False

        print("Please type y or n.")


# ============ MAIN ============

def main():
    lyricsCache = LoadCache()
    playlistID = ExtractPlaylistID(PLAYLIST_URL_OR_ID)

    print("Playlist input:", PLAYLIST_URL_OR_ID)
    print("Extracted playlist ID:", playlistID)
    print()

    tracks = GetAllPlaylistTracks(playlistID)

    print("Tracks found:", len(tracks))
    print("Already cached:", len(lyricsCache))
    print()

    exactCachedCount = 0
    manualApprovedCount = 0
    manualDeclinedCount = 0
    skippedCount = 0
    failedCount = 0

    manualReviewCandidates = []

    taskOrder = BuildFrontBackTaskOrder(tracks)

    tasksToRun = []
    scheduledTrackIDs = set()

    for index, track in taskOrder:
        trackID = track.get("id")

        if trackID is None:
            skippedCount += 1
            continue

        if trackID in lyricsCache:
            print(f"[{index}/{len(tracks)}] Already cached:", track.get("name"))
            skippedCount += 1
            continue

        if trackID in scheduledTrackIDs:
            print(f"[{index}/{len(tracks)}] Duplicate in playlist, skipped:", track.get("name"))
            skippedCount += 1
            continue

        scheduledTrackIDs.add(trackID)
        tasksToRun.append((index, track))

    print()
    print("New songs to check:", len(tasksToRun))
    print("Worker threads:", WORKER_COUNT)
    print("Exact attempts before fallback search:", MAX_EXACT_ATTEMPTS)
    print("Fallback search matches will be reviewed at the end.")
    print()

    with ThreadPoolExecutor(max_workers=WORKER_COUNT) as executor:
        futureToIndex = {}

        for index, track in tasksToRun:
            future = executor.submit(
                FetchLyricsForTrack,
                index,
                len(tracks),
                track
            )

            futureToIndex[future] = index

        for future in as_completed(futureToIndex):
            try:
                result = future.result()

            except Exception as error:
                index = futureToIndex.get(future, "?")
                print(f"[{index}/{len(tracks)}] Worker crashed:", repr(error))
                failedCount += 1
                continue

            status = result.get("status")
            index = result.get("index")
            totalTracks = result.get("totalTracks")

            if status == "CACHED":
                SaveExactMatchToCache(lyricsCache, result)

                print(
                    f"[{index}/{totalTracks}] Exact cached:",
                    result["artistName"],
                    "-",
                    result["trackName"],
                    f"(attempt {result['attempts']})"
                )

                exactCachedCount += 1

            elif status == "REVIEW":
                manualReviewCandidates.append(result)

                print(
                    f"[{index}/{totalTracks}] Needs review:",
                    result["artistName"],
                    "-",
                    result["trackName"],
                    "=>",
                    result.get("matchedArtistName"),
                    "-",
                    result.get("matchedTrackName"),
                    "|",
                    result.get("matchedAlbumName"),
                    "| score",
                    round(result.get("matchScore", 0), 1)
                )

            elif status == "FAILED":
                print(
                    f"[{index}/{totalTracks}] Failed:",
                    result["artistName"],
                    "-",
                    result["trackName"]
                )

                if "bestRejectedTrackName" in result:
                    print(
                        "   Best rejected match:",
                        result.get("bestRejectedArtistName"),
                        "-",
                        result.get("bestRejectedTrackName"),
                        "|",
                        result.get("bestRejectedAlbumName"),
                        "| score",
                        round(result.get("bestRejectedScore", 0), 1)
                    )

                failedCount += 1

            elif status == "SKIPPED":
                print(
                    f"[{index}/{totalTracks}] Skipped:",
                    result.get("reason", "Unknown reason")
                )

                skippedCount += 1

    manualReviewCandidates.sort(key=lambda item: item["index"])

    if len(manualReviewCandidates) > 0:
        print()
        print("=" * 70)
        print("Manual review phase")
        print("=" * 70)
        print("Exact LRCLIB search failed for these, but fallback search found possible synced lyrics.")
        print("Say y only if the suggested LRCLIB match is clearly the same song/version.")
        print()

        for result in manualReviewCandidates:
            shouldCache = AskToCacheManualMatch(result)

            if shouldCache:
                SaveManualSearchMatchToCache(lyricsCache, result)
                manualApprovedCount += 1
                print("Saved to cache.")
            else:
                manualDeclinedCount += 1
                print("Not cached.")
    else:
        print()
        print("No fallback matches needed manual review.")

    print()
    print("Done.")
    print("Exact newly cached:", exactCachedCount)
    print("Manual fallback cached:", manualApprovedCount)
    print("Manual fallback declined:", manualDeclinedCount)
    print("Skipped/already cached:", skippedCount)
    print("Failed/no usable match:", failedCount)
    print("Total cache size:", len(lyricsCache))


if __name__ == "__main__":
    main()