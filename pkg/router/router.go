package router

import (
	"github.com/gammazero/nexus/v3/router"
	"github.com/gammazero/nexus/v3/wamp"
)

type Router struct {
	router.Router
}

func (r *Router) AttachClient(client wamp.Peer, transportDetails wamp.Dict) error {
	panic("not yet implemented")
	return r.Router.AttachClient(client, transportDetails)
}
