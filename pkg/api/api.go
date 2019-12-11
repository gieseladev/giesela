/*
Package api contains Giesela's outward-facing API.
*/
package api

import (
	"context"
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/getsentry/sentry-go"
	"github.com/gieseladev/giesela/pkg/rbac"
	"github.com/gieseladev/giesela/pkg/wamputil"
)

const gieselaURI = "io.giesela."

type API struct {
	internalWAMP *client.Client
	enforcer     *rbac.Enforcer
}

func (api *API) registerProcedures() error {
	return nil
}

// TODO store the user info in the context!

func (api *API) getUserInfo(invocation *wamp.Invocation) (*UserInfo, error) {
	// TODO get bound userID from caller id
	_, ok := invocation.Details["caller"]
	if !ok {
		// report this because the router should already block these invocations
		// IF the registration specified "disclose_caller".
		sentry.CaptureMessage("received invocation with undisclosed caller")
		return nil, wamputil.NewError(wamp.ErrNotAuthorized, "caller must disclose itself")
	}

	userID, ok := wamputil.Snowflake(wamputil.GetListValue(invocation.Arguments, 0))
	if !ok {
		return nil, wamputil.NewError(wamp.ErrInvalidArgument, "missing user id")
	}

	guildID, ok := wamputil.Snowflake(wamputil.GetListValue(invocation.Arguments, 1))
	if !ok {
		return nil, wamputil.NewError(wamp.ErrInvalidArgument, "missing guild id")
	}

	return &UserInfo{
		UserID:  userID,
		GuildID: guildID,
	}, nil
}

func (api *API) ensurePermission(ctx context.Context, invocation *wamp.Invocation, permissions ...rbac.Permission) *client.InvokeResult {
	user, err := api.getUserInfo(invocation)
	if err != nil {
		res := ResultFromError(err)
		return &res
	}

	allowed, err := api.enforcer.HasPermission(user.GuildID, user.UserID, permissions...)
	if err != nil {
		res := InternalErrorResult("something went wrong while checking permissions")
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

func (api *API) ensureRateLimit(ctx context.Context, invocation *wamp.Invocation) *client.InvokeResult {
	// TODO get rate limits for user and check increase
	//		members have take the "strongest" rate limit from their roles.
	//		there's also the global user rate limit which applies across all guilds.
	return nil
}
