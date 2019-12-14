package router

import (
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/router"
	"github.com/gammazero/nexus/v3/stdlog"
	"github.com/gammazero/nexus/v3/wamp"
)

type Router struct {
	router.Router

	debug          bool
	publicRealmURI wamp.URI
}

func NewRouter(uri wamp.URI, cfg *router.Config, logger stdlog.StdLog) (*Router, error) {
	wrapped, err := router.NewRouter(cfg, logger)
	if err != nil {
		return nil, err
	}

	r := &Router{Router: wrapped, debug: cfg.Debug, publicRealmURI: uri}

	if err := r.AddRealm(RealmConfig(uri)); err != nil {
		return r, err
	}

	return r, nil
}

func (r *Router) getPublicClient() (*client.Client, error) {
	return client.ConnectLocal(r, client.Config{
		Realm:  string(r.publicRealmURI),
		Debug:  r.debug,
		Logger: r.Logger(),
	})
}
