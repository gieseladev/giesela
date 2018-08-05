# Giesela

[![Crowdin](https://d322cqt584bo4o.cloudfront.net/giesela/localized.svg)](https://crowdin.com/project/giesela)
[![Build Status](https://travis-ci.org/GieselaDev/Giesela.svg?branch=refresh)](https://travis-ci.org/GieselaDev/Giesela)
[![license](https://img.shields.io/github/license/mashape/apistatus.svg)](https://github.com/GieselaDev/Giesela/blob/master/LICENSE)

## Refresh
This is the `refresh` version of Giesela. What does that mean exactly? Who knows...
Anyway, this is a stripped-down, containerised version of Giesela. It's still the same
old, crappy version of Giesela that ~~we've all~~  I've grown to hate, but at least it's
containerised which almost makes it acceptable...

## Image
Get the image from `giesela/giesela:refresh`


## Configuration
Configuring has never been as easy (maybe?)

### Environment
You can set the environment variables `token` to set the [Discord Bot Token] to use
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