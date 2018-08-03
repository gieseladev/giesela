# Giesela

[![Crowdin](https://d322cqt584bo4o.cloudfront.net/giesela/localized.svg)](https://crowdin.com/project/giesela)
[![Build Status](https://travis-ci.org/GieselaDev/Giesela.svg?branch=master)](https://travis-ci.org/GieselaDev/Giesela)
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