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
		ScopeAddMessage(hub.Scope(), invocation)
		ctx = sentry.SetHubOnContext(ctx, hub)

		defer h.recoverWithSentry(hub, ctx)
		return handler(ctx, invocation)
	}
}

func (h *Handler) recoverWithSentry(hub *sentry.Hub, ctx context.Context) {
	if err := recover(); err != nil {
		eventID := hub.RecoverWithContext(ctx, err)
		if eventID != nil && h.WaitForDelivery {
			hub.Flush(h.Timeout)
		}
		if h.Repanic {
			panic(err)
		}
	}
}
