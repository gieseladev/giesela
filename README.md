# Giesela Refresh

[![Crowdin](https://d322cqt584bo4o.cloudfront.net/giesela/localized.svg)](https://crowdin.com/project/giesela)
[![Build Status](https://travis-ci.org/GieselaDev/Giesela.svg?branch=refresh)](https://travis-ci.org/GieselaDev/Giesela)
[![license](https://img.shields.io/github/license/gieseladev/giesela.svg?branch=refresh)](https://github.com/GieselaDev/Giesela/blob/refresh/LICENSE)


## What is Refresh?
This is the `refresh` version of Giesela. What does that mean exactly? Who knows...
Anyway, this is a stripped-down, containerised version of Giesela. It's still the same
old, crappy version of Giesela that ~~we've all~~  I've grown to hate, but at least it's
containerised which - as we all know - improves everything by about 1000%...

In all seriousness though, there have been some changes [listed here](#whats-new).
While some might seem trivial, it is important to keep in mind that there are
a lot of smaller/internal changes that aren't listed which - over time - add up to
be quite important.

### Which version should I run?
~~Neither tbh~~
**This one!** The old version has reached its end-of-life and won't receive any support.


## Running
Instead of making things hard, why don't we just ignore manual setup and go straight
to something as easy as running a [Docker Container][docker-container].

Get the official image from `giesela/giesela:refresh` and just run it!


## Configuration
Configuring has never been as easy (maybe?)

### Environment Variables
`token` **required**:
    You need to set the [Discord Bot Token][discord-token] for Giesela to work.

`google_api_key` **required**:
    Api key for Google's API.
    
`command_prefix` *optional*:
    Set the prefix for messages addressed to Giesela (default "!").


### Volumes
You can mount `/giesela/data` which holds a lot of Giesela's static data
(certificates, lyrics, options, and so on).

> Keep in mind that these files will be overwritten with newer versions if there are any.
Currently this only affects `radio_stations.yml`

`/giesela/logs` holds the log files (if there even are any...)


### Secure WebSockets for Webiesela
Giesela Refresh ~~finally~~ supports SSL encryption for Webiesela. All you have to do
to enable it is place (mount) your certificate file in the `/giesela/data/cert` folder.

If you have a separate file for the private key you also need to place it in the same
folder and make sure Giesela can identify which is which. You can do this by either
naming the files `CERTIFICATE` vs `PRIVATEKEY` / `KEYFILE` or you can just give them
the suffix `.cert` vs `.key`. There are of course other possible name combinations
which Giesela understands, but I'm too lazy to name them all!


## What's new?
- Better interface
    * Interactive Messages for:
        - Lyrics
        - Queue / History
        - Playlist Editor / Entry Editor
        - Shell
        - Searching
    * Improved help/error
    * Self-updating now-playing message with built-in player control buttons
- New player with "native" support for seeking
- Using [Discord.py's Commands framework][discordpy-commands]
- Removed a bunch of commands (I know this doesn't really sound like a good thing, but
    most of these commands were useless or broken anyway)
- Optimised Entry system
- New and improved playlist system
- Newly added playlist features:
    * Playlist editors
- New radio station system which makes it easy (at least easier) to add new radio stations


[docker-container]: https://www.docker.com/what-container

[discord-token]: https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token
[discordpy-commands]: https://discordpy.readthedocs.io/en/rewrite/ext/commands/index.html "Commands Framework"