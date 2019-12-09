package public

import (
	"context"
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
)

const ariURI = "io.ari."

func (api *API) playerEnqueue(ctx context.Context, invocation *wamp.Invocation) client.InvokeResult {

	api.internalWAMP.Call(ctx, ariURI+"enqueue", nil, nil, nil, nil)
}
