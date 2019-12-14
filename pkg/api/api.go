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

func (api *API) addUserInfo(ctx context.Context, invocation *wamp.Invocation) (context.Context, error) {
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

	user := &UserInfo{
		UserID:  userID,
		GuildID: guildID,
	}

	if hub := sentry.GetHubFromContext(ctx); hub != nil {
		hub.ConfigureScope(func(s *sentry.Scope) {
			s.SetUser(sentry.User{ID: userID})
			s.SetTag("guild", guildID)
		})
	}

	return WithUserInfo(ctx, user), nil
}

func (api *API) checkRateLimit(ctx context.Context) (bool, error) {
	user := UserInfoFromContextMust(ctx)

	allowed, err := api.enforcer.HasRateLimit(user.GuildID, user.UserID)
	if err != nil {
		return false, err
	}

	return allowed, nil
}

func (api *API) checkPermission(ctx context.Context, permissions ...rbac.Permission) (bool, error) {
	user := UserInfoFromContextMust(ctx)

	allowed, err := api.enforcer.HasPermission(user.GuildID, user.UserID, permissions...)
	if err != nil {
		return false, err
	}

	return allowed, nil
}
