package router

import "github.com/gammazero/nexus/v3/wamp"

const (
	RoleUser      = "user"
	RoleMultiUser = "multi-user"
	RoleAPI       = "api"
)

type SingleUserAuthN struct {
}

func (s *SingleUserAuthN) AuthMethod() string {
	return "giesela-user"
}

func (s *SingleUserAuthN) Authenticate(sid wamp.ID, details wamp.Dict, client wamp.Peer) (*wamp.Welcome, error) {
	// TODO authenticate using discord oauth token
	panic("implement me")
}

type MultiUserAuthN struct {
}

func (s *MultiUserAuthN) AuthMethod() string {
	return "giesela-multiuser"
}

func (s *MultiUserAuthN) Authenticate(sid wamp.ID, details wamp.Dict, client wamp.Peer) (*wamp.Welcome, error) {
	// TODO this should work like a ticket / CR auth
	panic("implement me")
}
