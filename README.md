# Giesela Refresh

[![Crowdin](https://d322cqt584bo4o.cloudfront.net/giesela/localized.svg)](https://crowdin.com/project/giesela)
[![Build Status](https://travis-ci.org/GieselaDev/Giesela.svg?branch=refresh)](https://travis-ci.org/GieselaDev/Giesela)
[![license](https://img.shields.io/github/license/mashape/apistatus.svg)](https://github.com/GieselaDev/Giesela/blob/master/LICENSE)

## What is Refresh?
This is the `refresh` version of Giesela. What does that mean exactly? Who knows...
Anyway, this is a stripped-down, containerised version of Giesela. It's still the same
old, crappy version of Giesela that ~~we've all~~  I've grown to hate, but at least it's
containerised which -as we all know- improves everything by about 1000%...

## Running
Instead of making things hard, why don't we just ignore manual setup and go straight
to something as easy as running a [Docker Container][docker-container].

Get the official image from `giesela/giesela:refresh` and just run it!

## Configuration
Configuring has never been as easy (maybe?)

### Environment
You can set the environment variables `token` to set the [Discord Bot Token][discord-token]
and `command_prefix` to set the prefix for messages addressed to Giesela.

### Volumes
You can mount `/giesela/data` which holds the data for the configuration file,
the playlists and the lyrics (I think that's everything)

`/giesela/logs` holds the log files (if there even are any...)

### Secure Websockets for Webiesela
Giesela Refresh ~~finally~~ supports SSL encryption for Webiesela. All you have to do
to enable it is place (mount) your certificate file in the `/giesela/data/cert` folder.

If you have a separate file for the private key you also need to place it in the same
folder and make sure Giesela can identify which is which. You can do this by either
naming the files `CERTIFICATE` vs `PRIVATEKEY` / `KEYFILE` or you can just give them
the suffix `.cert` vs `.key`. There are of course other possibilities, but I'm too lazy
to name them all!

## What's new?
- Better interface
    * Interactive Messages for Lyrics, Queue
    * Improved help/error
    * Self-updating now-playing message with built-in player control buttons
- New player with "native" support for seeking
- Using [Discord.py's Commands framework][discordpy-commands]
- Removed a bunch of commands (I know this doesn't really sound like a good thing, but
    most of these commands were useless or broken anyway)


[docker-container]: https://www.docker.com/what-container

[discord-token]: https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token
[discordpy-commands]: https://discordpy.readthedocs.io/en/rewrite/ext/commands/index.html "Commands Framework"