/*
Package typecast provides extended type casts.
*/
package typecast

import (
	"github.com/gammazero/nexus/v3/wamp"
	"strconv"
)

// AsString is an extended type cast for converting to a string.
var AsString = wamp.AsString

// AsInt64 is an extended type cast for converting to an integer.
var AsInt64 = wamp.AsInt64

// AsSnowflake is an extended type cast converting to a string.
// Unlike AsString it also supports integer values.
func AsSnowflake(v interface{}) (string, bool) {
	if v, ok := AsString(v); ok {
		return v, true
	}

	if v, ok := AsInt64(v); ok {
		return strconv.FormatInt(v, 10), true
	}

	return "", false
}
