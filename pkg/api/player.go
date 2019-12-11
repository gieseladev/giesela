package api

import (
	"context"
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/gieseladev/giesela/pkg/rbac"
)

const ariURI = "io.ari."

func (api *API) playerEnqueue(ctx context.Context, invocation *wamp.Invocation) client.InvokeResult {
	if res := api.ensurePermission(ctx, invocation, rbac.QueueModify); res != nil {
		return *res
	}

	res, err := api.internalWAMP.Call(ctx, ariURI+"enqueue", nil, nil, nil, nil)
	if err != nil {
		return ResultFromError(err)
	}

	return client.InvokeResult{
		Args:   res.Arguments,
		Kwargs: res.ArgumentsKw,
	}
}
