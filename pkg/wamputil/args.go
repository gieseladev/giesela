package wamputil

import (
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/gieseladev/giesela/pkg/typecast"
)

// GetListValue safely gets the value at the given index from a wamp.List.
func GetListValue(list wamp.List, i int) (interface{}, bool) {
	if i >= len(list) {
		return nil, false
	}

	return list[i], true
}

// GetDictValue safely gets the value of the given key from a wamp.Dict.
func GetDictValue(dict wamp.Dict, key string) (interface{}, bool) {
	if dict == nil {
		return nil, false
	}

	v, ok := dict[key]
	return v, ok
}

// SetDictValue adds the key value pair to the dict and returns it.
func SetDictValue(dict wamp.Dict, key string, value interface{}) wamp.Dict {
	if dict == nil {
		return wamp.Dict{key: value}
	}

	dict[key] = value
	return dict
}

func Snowflake(value interface{}, ok bool) (string, bool) {
	if !ok {
		return "", false
	}

	return typecast.AsSnowflake(value)
}
