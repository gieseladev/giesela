package router

import (
	"errors"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/getsentry/sentry-go"
	"github.com/gieseladev/giesela/pkg/sentrywamp"
	"github.com/gieseladev/giesela/pkg/wamputil"
)

type Authorizer struct {
	r *PublicRealm
}

func NewAuthorizer(r *PublicRealm) *Authorizer {
	return &Authorizer{r: r}
}

func (a *Authorizer) Authorize(sess *wamp.Session, msg wamp.Message) (bool, error) {
	ok := false

	switch msg := msg.(type) {
	case *wamp.Call:
		return a.authorizeCall(sess, msg)
	case *wamp.Subscribe:
		return a.authorizeSubscribe(sess, msg)
	case *wamp.Cancel:
		ok = true
	case *wamp.Unsubscribe:
		ok = true
	}

	return ok, nil
}

var (
	ErrGuildIDMissing = errors.New("guild_id missing")
	ErrUserIDMissing  = errors.New("user_id missing")
)

func (a *Authorizer) getUser(sess *wamp.Session, msg wamp.Message) (string, string, bool) {
	guildID, userID, ok := userFromDict(sess.Details)
	if !ok {
		sentry.WithScope(func(s *sentry.Scope) {
			sentrywamp.ScopeAddSession(s, sess)
			sentrywamp.ScopeAddMessage(s, msg)
			sentry.CaptureMessage("user session with no user identification")
		})
	}

	return guildID, userID, ok
}

func (a *Authorizer) authorizeCall(sess *wamp.Session, call *wamp.Call) (bool, error) {
	var guildID, userID string
	if sess.HasRole(RoleUser) {
		var ok bool
		guildID, userID, ok = a.getUser(sess, call)
		if !ok {
			return false, nil
		}
	} else {
		var ok bool
		guildID, ok = wamputil.Snowflake(wamputil.PopListValue(&call.Arguments, 0))
		if !ok {
			return false, ErrGuildIDMissing
		}

		userID, ok = wamputil.Snowflake(wamputil.PopListValue(&call.Arguments, 0))
		if !ok {
			return false, ErrUserIDMissing
		}
	}

	ok, err := a.r.enforcer.HasRateLimit(guildID, userID)
	if err != nil || !ok {
		return false, err
	}

	userToDict(guildID, userID, call.Options)

	return true, nil
}

func (a *Authorizer) authorizeSubscribe(sess *wamp.Session, sub *wamp.Subscribe) (bool, error) {
	if !sess.HasRole(RoleUser) {
		return true, nil
	}

	// this should be unnecessary and is only here for debug purposes
	_, _, ok := a.getUser(sess, sub)
	if !ok {
		return false, nil
	}

	return true, nil
}
