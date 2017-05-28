---
title: Command skip
layout: reference
---
# "Now Playing" `skip`
---
### Command Structure
> `!skip [all]`

### Description
Use this command to skip the currently playing song.
When the current entry is a [timestamp-entry]({{ site.url }}/reference/entry_types/timestamp-entry) you can skip all the sub entries by providing the keyword `all`.

### Result
When there's nothing playing the command returns an Error, otherwise there's no result.
