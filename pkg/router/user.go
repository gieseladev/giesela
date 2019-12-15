package router

import (
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/gieseladev/giesela/pkg/wamputil"
)

const (
	KeyUserID  = "user_id"
	KeyGuildID = "guild_id"
)

func userFromDict(dict wamp.Dict) (guildID string, userID string, ok bool) {
	guildID, ok = wamputil.Snowflake(wamputil.GetDictValue(dict, KeyGuildID))
	if !ok {
		return
	}

	userID, ok = wamputil.Snowflake(wamputil.GetDictValue(dict, KeyUserID))
	return
}

func userToDict(guildID string, userID string, dict wamp.Dict) {
	dict[KeyGuildID] = guildID
	dict[KeyUserID] = userID
}
