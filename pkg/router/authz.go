package router

import (
	"github.com/gammazero/nexus/v3/wamp"
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

func (a *Authorizer) authUser(sess *wamp.Session, guildID string, userID string) (bool, error) {
	// TODO find a way to return some detail
	// 		maybe we should just force the client to handle rate limits locally
	ok, err := a.r.enforcer.HasRateLimit(guildID, userID)
	if err != nil || !ok {
		return false, err
	}

	// TODO get required permissions from details (needs to be passed to func)
	ok, err = a.r.enforcer.HasPermission(guildID, userID)
	if err != nil || !ok {
		return false, err
	}

	return true, nil
}

func (a *Authorizer) authorizeCall(sess *wamp.Session, call *wamp.Call) (bool, error) {
	// TODO store guild id / user id in details instead!

	var guildID, userID string
	if sess.HasRole(RoleUser) {
		// TODO get user id and guild id from session details
	} else {
		var ok bool

		guildID, ok = wamputil.Snowflake(wamputil.PopListValue(&call.Arguments, 0))
		if !ok {
			return false, nil
		}

		userID, ok = wamputil.Snowflake(wamputil.PopListValue(&call.Arguments, 0))
		if !ok {
			return false, nil
		}
	}

	if ok, err := a.authUser(sess, guildID, userID); err != nil || !ok {
		return false, err
	}

	opts := call.Options
	if opts == nil {
		opts = wamp.Dict{}
		call.Options = opts
	}

	opts["user_id"] = userID
	opts["guild_id"] = guildID

	return true, nil
}

func (a *Authorizer) authorizeSubscribe(sess *wamp.Session, sub *wamp.Subscribe) (bool, error) {
	if !sess.HasRole(RoleUser) {
		return true, nil
	}

	// TODO check whether user is allowed to subscribe
	//		get guild_id and user_id from session
	return true, nil
}
