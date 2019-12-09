package public

import (
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/getsentry/sentry-go"
	"github.com/gieseladev/giesela/pkg/rbac"
)

func InternalError(args ...interface{}) client.InvokeResult {
	return client.InvokeResult{
		Args: args,
		Err:  gieselaURI + "error.internal",
	}
}

func AttachEventID(result *client.InvokeResult, eventID *sentry.EventID) {
	if eventID == nil {
		return
	}

	if result.Kwargs == nil {
		result.Kwargs = wamp.Dict{}
	}

	result.Kwargs["event_id"] = string(*eventID)
}

func (api *API) ensurePermission(guildID string, userID string, permissions ...rbac.Permission) *client.InvokeResult {
	allowed, err := api.enforcer.HasPermission(guildID, userID, permissions...)
	if err != nil {
		res := InternalError("something went wrong while checking permissions")
		AttachEventID(&res, sentry.CaptureException(err))

		return &res
	}
	if !allowed {
		return &client.InvokeResult{
			Args:   wamp.List{"required permissions missing"},
			Kwargs: wamp.Dict{"permissions": permissions},
			Err:    gieselaURI + "error.forbidden",
		}
	}

	return nil
}
