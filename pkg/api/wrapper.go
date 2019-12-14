package api

import (
	"context"
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/gieseladev/giesela/pkg/rbac"
)

func CheckUser(api *API, handler client.InvocationHandler, permissions ...rbac.Permission) client.InvocationHandler {
	return func(ctx context.Context, invocation *wamp.Invocation) client.InvokeResult {
		ctx, err := api.addUserInfo(ctx, invocation)
		if err != nil {
			return ResultFromError(err)
		}

		ok, err := api.checkRateLimit(ctx)
		if err != nil {
			res := ResultFromError(err)
			ErrorResultTrace(&res, "rate_limit_check")
			return res
		}

		if !ok {
			return client.InvokeResult{
				Err: gieselaURI + "error.rate_limit",
			}
		}

		ok, err = api.checkPermission(ctx, permissions...)
		if err != nil {
			res := ResultFromError(err)
			ErrorResultTrace(&res, "permission_check")
			return res
		}

		if !ok {
			return client.InvokeResult{
				Kwargs: wamp.Dict{"permissions": permissions},
				Err:    gieselaURI + "error.forbidden",
			}
		}

		return handler(ctx, invocation)
	}
}
