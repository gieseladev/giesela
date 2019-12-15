package router

import (
	"github.com/gammazero/nexus/v3/router"
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/getsentry/sentry-go"
	"github.com/gieseladev/giesela/pkg/rbac"
	"github.com/gieseladev/giesela/pkg/sentrywamp"
	"github.com/gieseladev/giesela/pkg/wamputil"
)

func (r *PublicRealm) GetPublishFilter(msg *wamp.Publish) router.PublishFilter {
	return &publishFilter{
		realm:   r,
		message: msg,
		wrapped: router.NewSimplePublishFilter(msg),
	}
}

type publishFilter struct {
	realm       *PublicRealm
	message     *wamp.Publish
	wrapped     router.PublishFilter
	guildID     string
	userID      string
	permissions []rbac.Permission
}

const KeyPermissions = "perms"

func asPermissions(v interface{}) ([]rbac.Permission, error) {
	panic("implement me!")
}

func (f *publishFilter) parseMessage() {
	opts := f.message.Options

	f.guildID, _ = wamputil.Snowflake(wamputil.GetDictValue(opts, KeyGuildID))
	f.userID, _ = wamputil.Snowflake(wamputil.GetDictValue(opts, KeyUserID))

	perms, ok := wamputil.GetDictValue(opts, KeyPermissions)
	if ok {
		var err error
		f.permissions, err = asPermissions(perms)
		if err != nil {
			sentry.WithScope(func(s *sentry.Scope) {
				sentrywamp.ScopeAddMessage(s, f.message)
				sentry.AddBreadcrumb(&sentry.Breadcrumb{
					Message: "parsing required permissions for publication",
				})

				sentry.CaptureException(err)
			})
		}
	}
}

func (f *publishFilter) wrappedAllowed(sess *wamp.Session, defaultVal bool) bool {
	if f.wrapped == nil {
		return defaultVal
	}
	return f.wrapped.Allowed(sess)
}

func (f *publishFilter) Allowed(sess *wamp.Session) bool {
	if !f.wrappedAllowed(sess, true) {
		return false
	}

	if !sess.HasRole(RoleUser) {
		return true
	}

	// TODO remove these keys from the details.
	//		Not because we don't want them to be leaked, but to save bandwidth

	guildID, userID, ok := userFromDict(sess.Details)
	if !ok {
		return false
	}

	if f.guildID != "" && guildID != f.guildID {
		return false
	}

	if f.userID != "" && userID != f.userID {
		return false
	}

	ok, err := f.realm.enforcer.HasPermission(guildID, userID, f.permissions...)
	if err != nil {
		sentry.WithScope(func(s *sentry.Scope) {
			sentrywamp.ScopeAddSession(s, sess)
			sentrywamp.ScopeAddMessage(s, f.message)

			sentry.CaptureException(err)
		})

		return false
	}
	if !ok {
		return false
	}

	return true
}
