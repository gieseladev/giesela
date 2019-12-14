package api

import (
	"context"
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/gieseladev/giesela/pkg/wamputil"
)

const ariURI = "io.ari."

func (api *API) playerConnect(ctx context.Context, invocation *wamp.Invocation) client.InvokeResult {
	channelID, ok := wamputil.Snowflake(wamputil.GetListValue(invocation.Arguments, 0))
	if !ok {
		return InvalidArgumentResult("missing channel id")
	}

	res, err := api.internalWAMP.Call(ctx, ariURI+"connect", nil, wamp.List{channelID}, nil, nil)
	if err != nil {
		return ResultFromError(err)
	}

	return CallResult(res)
}

func (api *API) playerEnqueue(ctx context.Context, invocation *wamp.Invocation) client.InvokeResult {
	res, err := api.internalWAMP.Call(ctx, ariURI+"enqueue", nil, nil, nil, nil)
	if err != nil {
		return ResultFromError(err)
	}

	return CallResult(res)
}
