package sentrywamp

import (
	"context"
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/getsentry/sentry-go"
	"time"
)

type Handler struct {
	Repanic         bool
	WaitForDelivery bool
	Timeout         time.Duration
}

func New() *Handler {
	return &Handler{
		Timeout: time.Second * 2,
	}
}

func (h *Handler) Wrap(handler client.InvocationHandler) client.InvocationHandler {
	return func(ctx context.Context, invocation *wamp.Invocation) client.InvokeResult {
		hub := sentry.CurrentHub().Clone()
		ctx = sentry.SetHubOnContext(ctx, hub)

		defer h.recoverWithSentry(hub, ctx, invocation)
		return handler(ctx, invocation)
	}
}

func (h *Handler) recoverWithSentry(hub *sentry.Hub, ctx context.Context, invocation *wamp.Invocation) {
	if err := recover(); err != nil {
		eventID := hub.RecoverWithContext(
			context.WithValue(ctx, sentry.RequestContextKey, invocation),
			err,
		)
		if eventID != nil && h.WaitForDelivery {
			hub.Flush(h.Timeout)
		}
		if h.Repanic {
			panic(err)
		}
	}
}
