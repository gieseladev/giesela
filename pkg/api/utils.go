package api

import (
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/getsentry/sentry-go"
	"github.com/gieseladev/giesela/pkg/wamputil"
)

// InternalErrorResult creates an invoke result representing an internal error.
func InternalErrorResult(args ...interface{}) client.InvokeResult {
	return client.InvokeResult{
		Args: args,
		Err:  gieselaURI + "error.internal",
	}
}

// AttachEventID attaches a Sentry event's id to an invoke result.
// If the event id is nil, this function is a noop.
// The event id is stored in the keyword argument "event_id".
func AttachEventID(result *client.InvokeResult, eventID *sentry.EventID) {
	if eventID == nil {
		return
	}

	result.Kwargs = wamputil.SetDictValue(result.Kwargs, "event_id", string(*eventID))
}

// WAMPErrorResult creates an invoke result representing a WAMP error.
func WAMPErrorResult(err *wamp.Error) client.InvokeResult {
	return client.InvokeResult{
		Args:   err.Arguments,
		Kwargs: err.ArgumentsKw,
		Err:    err.Error,
	}
}

// ResultFromError creates an invoke result from an error.
// Passing a nil error will cause the function to panic.
// If the error is not recognised, an internal error result is created and the
//error is reported to Sentry.
func ResultFromError(err error) client.InvokeResult {
	if err == nil {
		panic("passed nil error")
	}

	switch err := err.(type) {
	case wamputil.InvocationError:
		return client.InvokeResult(err)
	case client.RPCError:
		return WAMPErrorResult(err.Err)
	default:
		res := InternalErrorResult("internal error")
		res.Kwargs = wamputil.SetDictValue(res.Kwargs, "error", err.Error())
		AttachEventID(&res, sentry.CaptureException(err))
		return res
	}
}
