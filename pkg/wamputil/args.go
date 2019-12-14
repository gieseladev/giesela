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

func PopListValue(list *wamp.List, i int) (interface{}, bool) {
	l := *list
	lastIdx := len(l) - 1

	if len(l) == 0 {
		return nil, false
	}

	var v interface{}
	switch i {
	case 0:
		v, *list = l[0], l[1:]
		return v, true
	case -1:
		v, *list = l[lastIdx], l[:lastIdx]
		return v, true
	}

	if i < 0 || i >= len(l) {
		return nil, false
	}

	if i < len(l)-1 {
		copy(l[i:], l[i+1:])
	}

	l[lastIdx] = nil
	*list = l[:lastIdx]

	return v, true
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

func List(value interface{}, ok bool) (wamp.List, bool) {
	if !ok {
		return nil, false
	}

	return typecast.AsList(value)
}
