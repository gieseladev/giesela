package router

import (
	"github.com/gammazero/nexus/v3/router"
	"github.com/gammazero/nexus/v3/wamp"
)

func (r *PublicRealm) GetPublishFilter(msg *wamp.Publish) router.PublishFilter {
	return &PublishFilter{
		realm:   r,
		Message: msg,
		Wrapped: router.NewSimplePublishFilter(msg),
	}
}

type PublishFilter struct {
	realm   *PublicRealm
	Message *wamp.Publish
	Wrapped router.PublishFilter
}

func (f *PublishFilter) wrappedAllowed(sess *wamp.Session, defaultVal bool) bool {
	if f.Wrapped == nil {
		return defaultVal
	}
	return f.Wrapped.Allowed(sess)
}

func (f *PublishFilter) Allowed(sess *wamp.Session) bool {
	if !f.wrappedAllowed(sess, true) {
		return false
	}

	// TODO make sure that the session SHOULD receive the event.
	return true
}
