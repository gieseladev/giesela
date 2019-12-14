package router

import (
	"github.com/gammazero/nexus/v3/router"
	"github.com/gammazero/nexus/v3/router/auth"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/gieseladev/giesela/pkg/rbac"
)

type PublicRealm struct {
	AuthZ    router.Authorizer
	enforcer *rbac.Enforcer
}

func NewPublicRealm() *PublicRealm {
	r := &PublicRealm{
		enforcer: nil,
	}

	r.AuthZ = NewAuthorizer(r)

	return r
}

func (r *PublicRealm) getAuthNs() []auth.Authenticator {
	return []auth.Authenticator{
		&SingleUserAuthN{},
		&MultiUserAuthN{},
	}
}

func RealmConfig(uri wamp.URI) *router.RealmConfig {
	realm := &PublicRealm{}

	return &router.RealmConfig{
		URI:                  uri,
		AllowDisclose:        true,
		Authenticators:       realm.getAuthNs(),
		Authorizer:           realm.AuthZ,
		PublishFilterFactory: realm.GetPublishFilter,
	}
}
