# Introduction

Put simply, Giesela is a musicbot for Discord. However, that term is very vague -- indeed, Giesela is a sophisticated yet elegant Discord music player system, which, along with her sister [Webiesela](https://github.com/siku2/Webiesela), forms a complete music suite. Giesela is the backend part of the project, providing the core functionality and logic. It is written in Python (3.6+) with modernity in mind, using [discord.py](https://github.com/Rapptz/discord.py) as the base API to communicate with Discord.

Giesela is fundamentally different from almost any of the other Discord musicbots that exist today. At their core, Giesela and Webiesela are designed to provide a beautiful experience for the user and giving a presence similar to music players one would use in the current day outside of Discord (think Spotify, Tidal, and the like). The goal to seamlessly bridge the divide between a standard Discord command-based system and an independent interface requires many design considerations, such as the prioritization of track metadata, immersive playlists, an advanced permission system that takes both frontend and backend into consideration, and an array of features that work under the hood to provide the user with an end result that *just works*. 

Giesela was designed with a simple question: how to make the experience of listening to music on Discord effortless, using elements that are familiar to most users today, and presenting them in a way that 'just clicks' with the everyday user. 

From a user's perspective, Giesela and Webiesela act as one unified music suite. But, Giesela is a largely sophisticated backend which holds a **lot** of cool tricks under her hood. Creating such an experience requires a new approach to many seemingly-basic concepts, thinking outside the box and asking questions at every level along the way - complete with a (necessary!) touch of crazy. The end result, put simply, is a truly unique addition to the Discord musicbot collection.

## Design Considerations 

The following is a **brief** summary of just a few of the design considerations that are critical to the project. Many of these will be touched upon in further sections for those wishing to dive deeper. 

- **Always** free and open-source, 100% of the time. Keeping the code open-source with no exceptions is an ideal held strongly by the developers of Giesela/Webiesela.

- Seamless [backend](https://github.com/siku2/Giesela) and [frontend](https://github.com/siku2/Webiesela) integration.

- Modern codebase (Python 3.6+) with utilization of efficient code throughout. Secure, thread-safe code, with proper implementation of lower-level player logic. No "leftovers" (like extra ffmpeg threads): just proper code.

- Interactive user experience (UX) that allows a user to have an immersive experience inside and outside Discord.

- Strong music metadata prioritization to provide a beautiful interface, with layers of fallback. Advanced lyric parsing with cache. Keeping this in-sync between frontend/backend at all times.

- Playlist system with a focus on UI/UX - automated mosaic and playlist art generation similar to dedicated music player applications to provide a realistic experience. Full playlist builder with sorted playlists, metadata whenever possible to provide the most accurate rendering.

- Full player browser interface on the frontend, allowing for a near-native experience (search from Spotify, YouTube and SoundCloud with a click of a button) - support for playlists and tracks.

- Permission system to sync between guild and role=based permissions. Designed with frontend interface in mind. More on this soon.
