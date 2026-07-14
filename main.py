import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import time
import random
import json
from parser_v1 import (
    ScrubSyncedLyrics,
    CreateLyricsAndTimestampLists
)

# ============ CONSTANTS ============

try:
    from spotify_secrets import SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET
except ImportError:
    raise ImportError(
        "Missing spotify_secrets.py. Copy spotify_secrets_example.py, "
        "rename it to spotify_secrets.py, and add your Spotify client ID and secret."
    )

SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-playback-state"

LCRLIBURL = "https://lrclib.net/api/get"

CACHE_PATH = "cache/lyrics_cache.json"

spAuth = SpotifyOAuth(
    client_id = SPOTIPY_CLIENT_ID,
    client_secret = SPOTIPY_CLIENT_SECRET,
    redirect_uri = SPOTIPY_REDIRECT_URI,
    scope = SCOPE
    )

sp = spotipy.Spotify(auth_manager=spAuth)

LYRIC_INTERVAL = 0.1      # 100 ms
SPOTIFY_INTERVAL = 2.0    # 2 seconds
TIME_RESYNC_THRESHOLD_MS = 500
LYRIC_RETRY_INTERVAL = 5.0
MAX_LYRIC_LOAD_ATTEMPTS = 6
IDLE_MESSAGE_INTERVAL = 15.0
IDLE_START_DELAY = 30.0
IDLE_MESSAGES = [
    "Waiting...",
    "Nothing to sing yet.",
    "It says 'gullible' on the ceiling.",
    "Beware the Aydin curse.",
    "Play something!",
    "What if I don't like lyrics in my car?",
    "The Bertmobile karaoke system is idle.",
    "Have you heard of The Pigeons?",
    "Horrible nicknames like Adam Cheese and Uncle Taha...",
    "Lyrics machine is taking a nap.",
    "Welcome to the Bertmobile!",
    "Imagine a cool animation here.",
    "No bangers detected.",
    "It's like a fleck!",
    "I just an Eva...",
    "Watch Dexter!"
]

# ============ VARIABLES ============

lastDisplayState = ""
idleCandidateStartTime = None
idleModeActive = False
lastIdleMessageTime = 0
lastIdleMessage = ""

# =========== FUNCTIONS ===========

def PrintStatusOnce(statusText):
    global lastDisplayState

    if statusText != lastDisplayState:
        print(statusText)
        lastDisplayState = statusText


def GetInvalidSpotifyState(stateType, error=None):
    return {
        "stateType": stateType,
        "isValidTrack": False,
        "trackID": None,
        "artistName": None,
        "trackName": None,
        "albumName": None,
        "durationMS": 0,
        "durationS": 0,
        "progressMS": 0,
        "requestTime": time.perf_counter(),
        "isPlaying": False,
        "lrclibParams": None,
        "error": error
    }


def GetSpotifyState():
    try:
        current = sp.current_playback()
    except Exception as error:
        return GetInvalidSpotifyState("SPOTIFY_ERROR", error)

    if current is None:
        return GetInvalidSpotifyState("NO_ACTIVE_SESSION")

    item = current.get("item")

    if item is None:
        return GetInvalidSpotifyState("NO_ITEM")

    if item.get("type") != "track":
        return GetInvalidSpotifyState("NOT_TRACK")

    try:
        artistName = item["artists"][0]["name"]
        trackName = item.get("name")
        albumName = item.get("album")["name"]
        durationMS = item["duration_ms"]

        # SPOTIFYSTATE FORMAT:
        return {
            "stateType": "TRACK",
            "isValidTrack": True,
            "trackID": item["id"],
            "artistName": artistName,
            "trackName": trackName,
            "albumName": albumName,
            "durationMS": durationMS,
            "durationS": durationMS // 1000,
            "progressMS": current.get("progress_ms"),
            "requestTime": time.perf_counter(),
            "isPlaying": current.get("is_playing"),

            "lrclibParams": {
                "artist_name": artistName,
                "track_name": trackName,
                "album_name": albumName,
                "duration": durationMS // 1000
            },
            "error": None
        }

    except Exception as error:
        return GetInvalidSpotifyState("BAD_TRACK_DATA", error)


def GetLCRLIBLyrics(params):
    if params is None:
        return None

    try:
        lrclibResponse = requests.get(LCRLIBURL, params=params, timeout=7)
    except requests.RequestException:
        return None

    if lrclibResponse.status_code != 200:
        return None

    try:
        data = lrclibResponse.json()
    except ValueError:
        return None

    return data.get("syncedLyrics")

def SaveCache(cacheDict):
    with open(CACHE_PATH, "w", encoding="utf-8") as cacheFile:
        json.dump(cacheDict, cacheFile, indent=4)

def LoadCache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as cacheFile:
            contents = json.load(cacheFile)
            return contents
    except FileNotFoundError:
        return {}

def GetLyricsFromCache(spotifyState):
    global lyricsCache

    trackID = spotifyState["trackID"]
    trackData = lyricsCache.get(trackID)

    return trackData

def SaveLyricsToCache(spotifyState, rawSyncedLyrics):
    global lyricsCache

    scrubbedLyricsData = ScrubSyncedLyrics(rawSyncedLyrics)

    lyricsCache[spotifyState["trackID"]] = {
        "trackName": spotifyState["trackName"],
        "artistName": spotifyState["artistName"],
        "albumName": spotifyState["albumName"],
        "lrclibAlbumName": spotifyState["albumName"],
        "durationMS": spotifyState["durationMS"],
        "cachedAt": time.time(),

        **scrubbedLyricsData
    }

    SaveCache(lyricsCache)

    return lyricsCache[spotifyState["trackID"]]

def EnsureTrackDataIsScrubbed(trackData):
    if trackData is None:
        return None

    if (
        trackData.get("scrubVersion") == 1
        and "displaySyncedLyrics" in trackData
    ):
        return trackData

    rawSyncedLyrics = trackData.get("rawSyncedLyrics")

    if rawSyncedLyrics is None:
        rawSyncedLyrics = trackData.get("syncedLyrics")

    scrubbedData = ScrubSyncedLyrics(rawSyncedLyrics)

    updatedTrackData = dict(trackData)
    updatedTrackData.pop("syncedLyrics", None)
    updatedTrackData.update(scrubbedData)

    return updatedTrackData
        

def LoadLyricsForSpotifyState(spotifyState):
    global lyricsCache

    trackData = GetLyricsFromCache(spotifyState)

    # Cached, check if scrubbed.
    if trackData is not None:
        scrubbedTrackData = EnsureTrackDataIsScrubbed(trackData)

        if scrubbedTrackData != trackData:
            lyricsCache[spotifyState["trackID"]] = scrubbedTrackData
            SaveCache(lyricsCache)

        trackData = scrubbedTrackData

    # The song is not cached, so fetch and scrub it.
    if trackData is None:
        rawSyncedLyrics = GetLCRLIBLyrics(
            spotifyState["lrclibParams"]
        )

        if rawSyncedLyrics is None:
            return [0], [""], 0, False

        trackData = SaveLyricsToCache(
            spotifyState,
            rawSyncedLyrics
        )

    displayStatus = trackData.get("displayStatus", "valid")

    if displayStatus == "unsupported_language":
        return [0], ["I can't understand that yet!"], 0, True

    displaySyncedLyrics = trackData.get("displaySyncedLyrics")

    if displaySyncedLyrics is None:
        return [0], [""], 0, False

    timestampList, lyricsList = CreateLyricsAndTimestampLists(
        displaySyncedLyrics
    )

    currentLyricIndex = GetCurrentLyricIndex(
        timestampList,
        GetSongTime(spotifyState)
    )

    return (
        timestampList,
        lyricsList,
        currentLyricIndex,
        True
    )


def midpoint(a, b):
    return a + (b - a) // 2


def GetCurrentLyricIndex(list, target):
    left = 0
    right = 0
    middle = 0
    bestIndex = 0

    right = len(list) - 1
    middle = midpoint(left, right)

    while left <= right:
        middle = midpoint(left, right)
        current = list[middle]

        if current <= target:
            bestIndex = middle
            left = middle + 1

        else:
            right = middle - 1

    return bestIndex


def GetEstimatedLyricIndex(currentIndex, timestamps, currentTime):
    while currentIndex + 1 < len(timestamps) and currentTime >= timestamps[currentIndex + 1]:
        currentIndex += 1
    return currentIndex


def GetSongTime(spotifyState):
    if spotifyState["isPlaying"] == False:
        return spotifyState["progressMS"]

    elapsedMS = (time.perf_counter() - spotifyState["requestTime"]) * 1000
    songTimeMS = spotifyState["progressMS"] + elapsedMS
    return songTimeMS

def GetIdleCandidateReason(spotifyState, hasLyrics, lyricsFailedPermanently):
    if spotifyState["stateType"] in ["NO_ACTIVE_SESSION", "NO_ITEM", "NOT_TRACK", "SPOTIFY_ERROR"]:
        return spotifyState["stateType"]

    if spotifyState["isValidTrack"] and hasLyrics == False and lyricsFailedPermanently:
        return "NO_SYNCED_LYRICS"

    if spotifyState["isValidTrack"] and spotifyState["isPlaying"] == False:
        return "PAUSED"

    return None

    return False

def GetRandomIdleMessage():
    global lastIdleMessage

    if len(IDLE_MESSAGES) == 1:
        chosenMessage = IDLE_MESSAGES[0]
    else:
        possibleMessages = []

        for message in IDLE_MESSAGES:
            if message != lastIdleMessage:
                possibleMessages.append(message)

        chosenMessage = random.choice(possibleMessages)

    lastIdleMessage = chosenMessage
    return chosenMessage

def UpdateIdleMessages(now, spotifyState, hasLyrics, lyricsFailedPermanently):
    global idleCandidateStartTime
    global idleModeActive
    global lastIdleMessageTime

    idleCandidateReason = GetIdleCandidateReason(
        spotifyState,
        hasLyrics,
        lyricsFailedPermanently
    )

    # Not idle-ish at all, so fully reset the idle countdown
    if idleCandidateReason is None:
        idleCandidateStartTime = None
        idleModeActive = False
        lastIdleMessageTime = 0
        return

    # First moment we entered any idle-ish state
    if idleCandidateStartTime is None:
        idleCandidateStartTime = now
        idleModeActive = False
        lastIdleMessageTime = 0
        return

    # We are idle-ish, but not for long enough yet
    if now - idleCandidateStartTime < IDLE_START_DELAY:
        idleModeActive = False
        lastIdleMessageTime = 0
        return

    # We have now been idle-ish for long enough
    if idleModeActive == False:
        idleModeActive = True
        lastIdleMessageTime = now
        print(GetRandomIdleMessage())
        return

    if now - lastIdleMessageTime >= IDLE_MESSAGE_INTERVAL:
        lastIdleMessageTime = now
        print(GetRandomIdleMessage())

def displayLyrics(lyric):
    lines = []

    lyric = lyric[:80] # Trim to 80 chars
    lyricLength = len(lyric)

    lineCount = (lyricLength + 19) // 20 # Zero-indexed line count. 4 lines would give lineCount of 3

    for lineNumber in range(lineCount): # Split up the lyric into lines of 20 chars
            start = 20 * lineNumber
            end = min(20 * (lineNumber + 1), lyricLength)
            
            lines.append(lyric[start:end].lstrip())

    # Display Lines
    print("")
    for line in lines:
        print(line)


# ============== MAIN ===============

spotifyState = GetSpotifyState()
lyricsCache = LoadCache() #Key = trackID, data is another dict containing lyrics only for now, but can contian other stuff

timestampList = [0]
lyricsList = [""]
currentLyricIndex = 0
hasLyrics = False

lyricLoadAttempts = 0
nextLyricRetryTime = 0
lyricsFailedPermanently = False

# If there is a session, say that lyrics are being loaded
if spotifyState["isValidTrack"]:
    PrintStatusOnce("LOADING_LYRICS")

    # Try to get packaged lyrics from LCRLIB
    lyricLoadAttempts += 1
    timestampList, lyricsList, currentLyricIndex, hasLyrics = LoadLyricsForSpotifyState(spotifyState)

    if hasLyrics:
        displayLyrics(lyricsList[currentLyricIndex])
    else: # If no lyrics, print that you're retrying, wait a little then try again.
        PrintStatusOnce("LYRICS_NOT_LOADED_RETRYING")
        nextLyricRetryTime = time.perf_counter() + LYRIC_RETRY_INTERVAL
# Otherwise print whats happening.
else:
    PrintStatusOnce(spotifyState["stateType"])

last_lyric_update = time.perf_counter()
last_spotify_check = time.perf_counter()

while True:
    now = time.perf_counter()
    UpdateIdleMessages(now, spotifyState, hasLyrics, lyricsFailedPermanently)

    if spotifyState["isValidTrack"] and hasLyrics:
        estimatedSongTimeMS = GetSongTime(spotifyState)

        if now - last_lyric_update >= LYRIC_INTERVAL:
            originalLyricIndex = currentLyricIndex
            currentLyricIndex = GetEstimatedLyricIndex(currentLyricIndex, timestampList, estimatedSongTimeMS)

            if originalLyricIndex != currentLyricIndex:
                displayLyrics(lyricsList[currentLyricIndex])

            last_lyric_update = now


    if now - last_spotify_check >= SPOTIFY_INTERVAL:
        oldSpotifyState = spotifyState
        newSpotifyState = GetSpotifyState()

        if newSpotifyState["isValidTrack"] == False:
            spotifyState = newSpotifyState
            timestampList = [0]
            lyricsList = [""]
            currentLyricIndex = 0
            hasLyrics = False

            lyricLoadAttempts = 0
            nextLyricRetryTime = 0
            lyricsFailedPermanently = False

            PrintStatusOnce(spotifyState["stateType"])


        elif oldSpotifyState["isValidTrack"] == False or newSpotifyState["trackID"] != oldSpotifyState["trackID"]:
            spotifyState = newSpotifyState

            timestampList = [0]
            lyricsList = [""]
            currentLyricIndex = 0
            hasLyrics = False

            lyricLoadAttempts = 0
            nextLyricRetryTime = 0
            lyricsFailedPermanently = False

            PrintStatusOnce("LOADING_LYRICS")

            lyricLoadAttempts += 1
            timestampList, lyricsList, currentLyricIndex, hasLyrics = LoadLyricsForSpotifyState(spotifyState)

            if hasLyrics:
                displayLyrics(lyricsList[currentLyricIndex])
            else:
                PrintStatusOnce("LYRICS_NOT_LOADED_RETRYING")
                nextLyricRetryTime = time.perf_counter() + LYRIC_RETRY_INTERVAL


        else:
            if hasLyrics == False and lyricsFailedPermanently == False:
                if now >= nextLyricRetryTime:
                    PrintStatusOnce("RETRYING_LYRICS")

                    lyricLoadAttempts += 1
                    timestampList, lyricsList, currentLyricIndex, hasLyrics = LoadLyricsForSpotifyState(newSpotifyState)

                    if hasLyrics:
                        displayLyrics(lyricsList[currentLyricIndex])

                    elif lyricLoadAttempts >= MAX_LYRIC_LOAD_ATTEMPTS:
                        lyricsFailedPermanently = True
                        PrintStatusOnce("NO_SYNCED_LYRICS")

                    else:
                        PrintStatusOnce("LYRICS_NOT_LOADED_RETRYING")
                        nextLyricRetryTime = now + LYRIC_RETRY_INTERVAL

            estimatedSongTimeMS = GetSongTime(spotifyState)
            actualSpotifyTimeMS = GetSongTime(newSpotifyState)
            timeDifferenceMS = actualSpotifyTimeMS - estimatedSongTimeMS

            if hasLyrics and abs(timeDifferenceMS) > TIME_RESYNC_THRESHOLD_MS:
                print("Time jump detected:", timeDifferenceMS, "ms")

                currentLyricIndex = GetCurrentLyricIndex(timestampList, actualSpotifyTimeMS)
                displayLyrics(lyricsList[currentLyricIndex])

            spotifyState = newSpotifyState


        last_spotify_check = now


    time.sleep(0.01)