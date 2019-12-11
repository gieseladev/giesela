package wamputil

import (
	"github.com/gammazero/nexus/v3/client"
	"github.com/gammazero/nexus/v3/wamp"
)

// InvocationError is a InvokeResult that implements the error interface.
type InvocationError client.InvokeResult

// NewError creates an invocation error with an error uri and arguments.
func NewError(uri wamp.URI, args ...interface{}) InvocationError {
	return InvocationError{
		Args: args,
		Err:  uri,
	}
}

// Error implements the error interface for invocation errors.
// It returns the error's uri.
func (e InvocationError) Error() string {
	return string(e.Err)
}
