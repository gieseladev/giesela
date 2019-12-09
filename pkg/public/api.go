package public

import (
	"github.com/gammazero/nexus/v3/client"
	"github.com/gieseladev/giesela/pkg/rbac"
)

const gieselaURI = "io.giesela."

type API struct {
	internalWAMP *client.Client
	enforcer     *rbac.Enforcer
}

func (api *API) registerProcedures() error {
	return nil
}
