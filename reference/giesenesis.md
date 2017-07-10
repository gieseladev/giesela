---
title: Giesenesis
layout: reference
---

# Giesenesis
### The rewrite
---

This rewrite took place in celebration of the [1000th GitHub commit](https://github.com/siku2/Giesela/tree/9886248288f43411e534df529c539055123550ef)
> The 1000th commit wasn't anything special. It merely features some more [Website](http://giesela.org) stuff.

The goal was to improve the queue system which is one of the three core parts of Giesela (Player, Queue, Interface) by differentiating between the different Entry-Types. Before `Giesenesis` each entry was either a `URLPlaylistEntry` or a `StreamPlaylistEntry` where the `URLPlaylistEntry` could have information that would turn it into a `SpotifyEntry` or a `TimestampEntry` and the `StreamPlaylistEntry` would have a sub-type for `radio-entries`.
With the new version Giesela knows **six** distinct entry types. There are two base-entry types, the `YoutubeEntry` and the `StreamEntry`.

## YoutubeEntry
This is the most common entry-type. It's a normal Youtube video with no more external information.
### TimestampEntry
When Giesela finds timestamps in the description or comments of a video the entry is upgraded to a `TimestampEntry` which has the same information as a `YoutubeEntry` but can distinguish between its several sub-entries.
### SpotifyEntry
When the youtube video can be found on Spotify the YoutubeEntry is upgraded to a `SpotifyEntry` which in it contains most of the information Spotify provides.

## StreamEntry
This is the base class for everything that can't be downloaded and must be streamed directly. (Twitch, Youtube Live)
### RadioStationEntry
The name is pretty self-explanatory, isn't it? When one uses the [radio]({{ site.url }}/reference/commands/radio) command, this is the result.
#### RadioSongEntry
When Giesela can find out more about the current song of a `RadioStationEntry`, said entry is upgraded to a `RadioSongEntry` which contains information about the current song.
